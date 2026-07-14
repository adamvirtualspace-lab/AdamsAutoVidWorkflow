import ollama
import sys
from pathlib import Path

MODEL = "qwen3.5:4b"   # change to your preferred local model

def generate_editplan(srt_path: Path, raw_path: Path) -> str:
    subtitle_text = srt_path.read_text(encoding="utf-8")
    video_path = raw_path.resolve()

    prompt = f"""You are a video editor. Below is an SRT subtitle file from a gameplay video.

Analyze the subtitles and understand the context. Decide which parts to KEEP (funny, interesting, engaging) and which to CUT (boring, silence, filler).

Write an editplan.md that follows this exact structure (matching editplan_example.md):

1. **Title heading** — e.g. `# Video Title - Edit Plan`
2. **Metadata** — source file, language, players, main mission
3. **Editing Philosophy** — bullet points of what to keep/cut
4. **Segment Cut List** — group related moments into sections with `### KEEP/CUT/TRIM - Section Name (Time range)` headings. Under each section, list individual segments as bullet points:
   `- **HH:MM:SS–HH:MM:SS** → KEEP/CUT/TRIM. Description of the moment.`
5. **Summary table** at the end with columns: `| # | Keep/Cut | Start | End | Duration | Notes |`
6. **Source media reference** line at the bottom

Rules:
- Timecodes in HH:MM:SS or H:MM:SS format.
- KEEP = include in final video. CUT = exclude. TRIM = keep but tighten.
- Cover the entire video — every second accounted for.
- Add meaningful notes explaining each decision.

Here is the subtitle content:
{subtitle_text}"""

    try:
        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={
                "num_predict": 65536,
                "temperature": 0.2,
            }
        )
        return response["message"]["content"]
    except Exception as e:
        print(f"Ollama call failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    srt = Path("../02_RawSubtitles/COMPILED_AUDIO_merged.srt")
    raw = Path("../01_RAW/COMPILED_VIDEO.mp4")
    if not srt.exists():
        print(f"SRT file not found: {srt}")
        sys.exit(1)
    if not raw.exists():
        print(f"RAW file not found: {raw}")
        sys.exit(1)
    print("Generating edit plan from subtitles...")
    result = generate_editplan(srt, raw)
    out_path = Path("editplan.md")
    out_path.write_text(result, encoding="utf-8")
    print(f"Edit plan written to {out_path.resolve()}")
