import json
import ollama
import re
import sys
from pathlib import Path

MODEL = "qwen2.5-coder:3b"
CHUNK_SEC = 60  # 1 minutes per chunk

def parse_srt_segments(srt_text: str) -> list[dict]:
    segments = []
    pattern = re.compile(
        r'(\d+)\n(\d+:\d+:\d+,\d+) --> (\d+:\d+:\d+,\d+)\n((?:(?!\n\n|\n$).+\n?)*)',
        re.MULTILINE
    )
    for m in pattern.finditer(srt_text):
        segments.append({
            "id": int(m.group(1)),
            "start": m.group(2),
            "end": m.group(3),
            "text": m.group(4).strip().replace("\n", " ")
        })
    return segments


def tc_to_sec(tc: str) -> float:
    parts = tc.replace(",", ".").split(":")
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])


def sec_to_tc(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def merge_adjacent(segments: list[dict]) -> list[dict]:
    merged = []
    for seg in segments:
        if merged and merged[-1]["action"] == seg["action"]:
            merged[-1]["end_sec"] = seg["end_sec"]
            all_notes = []
            if merged[-1].get("notes"):
                all_notes.append(merged[-1]["notes"])
            if seg.get("notes"):
                all_notes.append(seg["notes"])
            unique = list(dict.fromkeys(all_notes))
            merged[-1]["notes"] = unique[0] if len(unique) == 1 else " | ".join(unique)
        else:
            merged.append({**seg})
    return merged


def format_segments_for_prompt(segments: list[dict], start_offset: float) -> str:
    lines = []
    for seg in segments:
        rel_start = seg["start_sec"] - start_offset
        rel_end = seg["end_sec"] - start_offset
        lines.append(f"[{seg['id']}] +{rel_start:.0f}s->+{rel_end:.0f}s: {seg['text']}")
    return "\n".join(lines)


def classify_chunk(segments: list[dict], chunk_idx: int, total_chunks: int) -> list[dict]:
    if not segments:
        return []
    start_offset = segments[0]["start_sec"]
    end_offset = segments[-1]["end_sec"]
    chunk_start_tc = sec_to_tc(start_offset)
    chunk_end_tc = sec_to_tc(end_offset)
    srt_text = format_segments_for_prompt(segments, start_offset)
    print(f"    Asking model for chunk {chunk_idx + 1}...", flush=True)

    prompt = f"""You are a video editor. Analyze these SRT subtitle segments (chunk {chunk_idx + 1}/{total_chunks}, {chunk_start_tc}–{chunk_end_tc}) from a gameplay video.

For each segment, decide:
- KEEP = funny/interesting/engaging — include
- CUT = boring/silence/filler — exclude
- TRIM = keep but tighten

Respond ONLY with a JSON array:
[{{"id": 1, "action": "KEEP", "notes": "reason"}}, ...]

Segments:
{srt_text}"""

    try:
        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"num_predict": 65536, "temperature": 0.2}
        )
        raw = response["message"]["content"]
    except Exception as e:
        print(f"\nOllama call failed on chunk {chunk_idx + 1}: {e}")
        sys.exit(1)

    start = raw.find("[")
    if start == -1:
        print(f"\nNo JSON in response for chunk {chunk_idx + 1}")
        return [{"id": s["id"], "action": "KEEP", "notes": "", "start_sec": s["start_sec"], "end_sec": s["end_sec"]} for s in segments]

    depth = 0
    end = start
    for i in range(start, len(raw)):
        if raw[i] == "[":
            depth += 1
        elif raw[i] == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if depth != 0:
        end = len(raw)

    try:
        decisions = json.loads(raw[start:end])
    except json.JSONDecodeError:
        # try salvaging
        last_good = raw.rfind("},")
        if last_good > start:
            try:
                decisions = json.loads(raw[start:last_good + 1] + "]")
            except json.JSONDecodeError:
                decisions = []
        else:
            decisions = []

    decision_map = {}
    for d in decisions:
        if "id" in d:
            decision_map[d["id"]] = d

    result = []
    for seg in segments:
        d = decision_map.get(seg["id"], {})
        action = d.get("action", "KEEP").upper()
        if action not in ("KEEP", "CUT", "TRIM"):
            action = "KEEP"
        result.append({
            "id": seg["id"],
            "start_sec": seg["start_sec"],
            "end_sec": seg["end_sec"],
            "action": action,
            "notes": d.get("notes", ""),
        })

    keep = sum(1 for r in result if r["action"] == "KEEP")
    cut = sum(1 for r in result if r["action"] == "CUT")
    trim = sum(1 for r in result if r["action"] == "TRIM")
    print(f"  Chunk {chunk_idx + 1}: {len(result)} segments ({keep} KEEP, {cut} CUT, {trim} TRIM)", flush=True)
    return result


def generate_editplan(srt_path: Path, raw_path: Path) -> str:
    subtitle_text = srt_path.read_text(encoding="utf-8")
    video_path = raw_path.resolve()
    raw_segments = parse_srt_segments(subtitle_text)

    # Compute end times
    for seg in raw_segments:
        seg["start_sec"] = tc_to_sec(seg["start"])
        seg["end_sec"] = tc_to_sec(seg["end"])

    total_dur = raw_segments[-1]["end_sec"] if raw_segments else 0
    print(f"Total duration: {sec_to_tc(total_dur)}, {len(raw_segments)} segments", flush=True)

    # Split into chunks — cap at MAX_SEGMENTS_PER_CHUNK
    MAX_SEG = 40
    chunks = []
    current_chunk = []
    chunk_end = CHUNK_SEC
    for seg in raw_segments:
        if current_chunk and (seg["start_sec"] >= chunk_end or len(current_chunk) >= MAX_SEG):
            chunks.append(current_chunk)
            current_chunk = []
            chunk_end += CHUNK_SEC
        current_chunk.append(seg)
    if current_chunk:
        chunks.append(current_chunk)

    print(f"Processing {len(chunks)} chunks of ~{CHUNK_SEC // 60} min each...", flush=True)
    all_classified = []
    partial_path = Path("editplan_partial.md")
    for i, chunk in enumerate(chunks):
        print(f"  Chunk {i + 1}/{len(chunks)}: {len(chunk)} segments ({sec_to_tc(chunk[0]['start_sec'])}–{sec_to_tc(chunk[-1]['end_sec'])})", flush=True)
        result = classify_chunk(chunk, i, len(chunks))
        all_classified.extend(result)

        # Append chunk to partial progress file
        with partial_path.open("a", encoding="utf-8") as f:
            f.write(f"\n## Chunk {i + 1}/{len(chunks)} ({sec_to_tc(chunk[0]['start_sec'])}–{sec_to_tc(chunk[-1]['end_sec'])})\n\n")
            for r in result:
                f.write(f"- **{sec_to_tc(r['start_sec'])}–{sec_to_tc(r['end_sec'])}** → {r['action']}. {r['notes']}\n")
        print(f"  -> Appended to {partial_path.name}", flush=True)

    print(f"\nAll chunks complete. Building final editplan...", flush=True)

    # Short TRIM segments (<6s) become KEEP — not worth trimming
    for seg in all_classified:
        if seg["action"] == "TRIM" and (seg["end_sec"] - seg["start_sec"]) < 6:
            seg["action"] = "KEEP"
            seg["notes"] = seg.get("notes", "") + " (too short to trim)"

    merged = merge_adjacent(all_classified)

    # Remove segments <1s (display rounding issues)
    merged = [s for s in merged if (s["end_sec"] - s["start_sec"]) >= 1.0]

    # Build section-based format
    section_items = []
    current_action = None
    for seg in merged:
        if seg["action"] != current_action:
            section_items.append({"action": seg["action"], "segments": [seg]})
            current_action = seg["action"]
        else:
            section_items[-1]["segments"].append(seg)

    section_lines = []
    for sec in section_items:
        first = sec["segments"][0]
        last = sec["segments"][-1]
        s_start = sec_to_tc(first["start_sec"])
        s_end = sec_to_tc(last["end_sec"])
        section_lines.append(f"### {sec['action']} ({s_start}–{s_end})")
        for seg in sec["segments"]:
            start = sec_to_tc(seg["start_sec"])
            end = sec_to_tc(seg["end_sec"])
            note = seg.get("notes", "")
            section_lines.append(f"- **{start}–{end}** → {seg['action']}. {note}")
        section_lines.append("")

    section_text = "\n".join(section_lines).strip()

    # Build summary table
    table_rows = []
    for i, seg in enumerate(merged, 1):
        dur = seg["end_sec"] - seg["start_sec"]
        dur_m = int(dur // 60)
        dur_s = int(dur % 60)
        dur_str = f"{dur_m}:{dur_s:02d}"
        note = seg.get("notes", "")
        table_rows.append(
            f"| {i} | {seg['action']} | {sec_to_tc(seg['start_sec'])} | {sec_to_tc(seg['end_sec'])} | {dur_str} | {note} |"
        )
    table = "\n".join(table_rows)

    keep = sum(s["end_sec"] - s["start_sec"] for s in merged if s["action"] == "KEEP")
    cut = sum(s["end_sec"] - s["start_sec"] for s in merged if s["action"] == "CUT")
    trim = sum(s["end_sec"] - s["start_sec"] for s in merged if s["action"] == "TRIM")

    editplan = f"""# {raw_path.stem} - Edit Plan

**Source:** {raw_path.name}
**Language:** Indonesian
**Duration:** {sec_to_tc(total_dur)}
Source media reference: `{video_path}`

---

## Editing Philosophy
- Keep fun banter, laugh moments, chaos, and interesting gameplay commentary.
- Cut long silences, repetitive filler, menu navigation with no commentary.
- Cut or trim stretches of silent driving.

---

## Segment Cut List

{section_text}

---

## Summary: Cut List (by timecode)

| # | Keep/Cut | Start | End | Duration | Notes |
|---|----------|-------|-----|----------|-------|
{table}

**Total keep:** {sec_to_tc(keep)} | **Total cut:** {sec_to_tc(cut)} | **Total trim:** {sec_to_tc(trim)} | **Original:** {sec_to_tc(total_dur)}
"""
    return editplan


if __name__ == "__main__":
    srt = Path("../02_RawSubtitles/COMPILED_AUDIO_merged.srt")
    raw = Path("../01_RAW/COMPILED_VIDEO.mp4")
    if not srt.exists():
        print(f"SRT file not found: {srt}")
        sys.exit(1)
    if not raw.exists():
        print(f"RAW file not found: {raw}")
        sys.exit(1)
    print("Generating edit plan from subtitles...", flush=True)
    result = generate_editplan(srt, raw)
    out_path = Path("editplan.md")
    out_path.write_text(result, encoding="utf-8")
    print(f"Edit plan written to {out_path.resolve()}", flush=True)
