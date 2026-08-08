#!/usr/bin/env python3
"""
CombineFinalTimeline.py
Accumulate the three stage timelines into the two final OTIO timelines.

Inputs (relative to the project root):
    03_EditPlanToOtio\\editplan.otio     -> the cut  (Video 1 + Audio 1)
    04_FinalSubtitle\\FinalSubtitle.otio -> captions (one Text clip per SRT cue)
    05_Memes\\memeeditplan.otio          -> memes    (still images with gaps)

Outputs:
    06_Final\\FinalTimelineNoCap.otio    -> cut + memes
    06_Final\\FinalTimelineWithCap.otio  -> cut + memes + captions

Track order in the output stack is bottom-to-top, the way Resolve stacks them:

    Video 1  the edit          (from editplan)
    Video 2  memes             (from memeeditplan, "Memes" track only)
    Video 3  captions          (from FinalSubtitle, WithCap output only)
    Audio 1  the edit's audio  (from editplan)

The stage files do not have to share a frame rate -- the meme converter defaults
to 30fps while the edit and captions are 60fps.  Everything is resampled to the
edit's rate (or --fps) on the way in, so the three stay in sync.

No external dependencies -- reads and writes OTIO JSON directly.

Usage:
    python CombineFinalTimeline.py
    python CombineFinalTimeline.py --fps 60
    python CombineFinalTimeline.py --no-memes
    python CombineFinalTimeline.py --dry-run
"""

import re
import json
import copy
import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional


# ─── Project layout ───────────────────────────────────────────────────────────
# .scripts/ -> 06_Final/ -> <ProjectRoot>/

FINAL_DIR    = Path(__file__).resolve().parent.parent
PROJECT_ROOT = FINAL_DIR.parent

EDIT_OTIO     = PROJECT_ROOT / "03_EditPlanToOtio" / "editplan.otio"
CAPTION_OTIO  = PROJECT_ROOT / "04_FinalSubtitle"  / "FinalSubtitle.otio"
MEME_OTIO     = PROJECT_ROOT / "05_Memes"          / "memeeditplan.otio"

OUT_NOCAP     = FINAL_DIR / "FinalTimelineNoCap.otio"
OUT_WITHCAP   = FINAL_DIR / "FinalTimelineWithCap.otio"

# Optional cold open.  Absent highlights.md, none of this runs and the output is
# exactly the plain edit.
HIGHLIGHTS_MD = FINAL_DIR / "highlights.md"
DEFAULT_INTRO = Path(r"E:\AdamsRoadTrips\.Assets\AdamRoadTrips Intro.mp4")


# ─── OTIO helpers ─────────────────────────────────────────────────────────────

def rt(value, rate) -> dict:
    return {
        "OTIO_SCHEMA": "RationalTime.1",
        "rate":        rate,
        "value":       value,
    }


def load_otio(path: Path, label: str) -> Optional[dict]:
    """Read an .otio file, returning None (with a message) if it isn't usable."""
    if not path.exists():
        print(f"  [MISS] {label:<9}: not found - {path}")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"  [ERR ] {label:<9}: not valid JSON - {e}")
        return None
    if "tracks" not in data:
        print(f"  [ERR ] {label:<9}: no 'tracks' stack - is this an OTIO timeline?")
        return None
    return data


def find_track(timeline: dict, name: str = None, kind: str = None) -> Optional[dict]:
    """
    Locate a track in a timeline's stack.

    Matches on name first (case-insensitive), then falls back to the first track
    of the requested kind.  Returns None when nothing matches.
    """
    tracks = timeline["tracks"]["children"]
    if name:
        for t in tracks:
            if t.get("name", "").strip().lower() == name.strip().lower():
                return t
    if kind:
        for t in tracks:
            if t.get("kind") == kind:
                return t
    return None


def track_frames(track: dict) -> float:
    """Sum of every child's duration, in the track's own frames."""
    return sum(c["source_range"]["duration"]["value"] for c in track["children"])


def track_rate(track: dict) -> Optional[float]:
    """The rate a track's clips are expressed in."""
    for c in track["children"]:
        return c["source_range"]["duration"]["rate"]
    return None


def resample(node, target_rate: float, source_rate: float):
    """
    Rewrite every RationalTime under `node` to target_rate, in place.

    Frame values are scaled by target/source so wall-clock timing is preserved:
    a 30fps clip at frame 90 (3.0s) becomes frame 180 at 60fps (still 3.0s).
    """
    if source_rate == target_rate:
        return node

    factor = target_rate / source_rate

    def walk(n):
        if isinstance(n, dict):
            if n.get("OTIO_SCHEMA", "").startswith("RationalTime"):
                n["value"] = round(n["value"] * factor)
                n["rate"]  = target_rate
                return
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(node)
    return node


def prepare_track(track: dict, new_name: str, target_rate: float,
                  drop_effects: bool = False) -> dict:
    """Copy a source track, rename it, and resample it onto the master rate."""
    out = copy.deepcopy(track)
    src_rate = track_rate(out)

    if src_rate and src_rate != target_rate:
        print(f"    resampling {track.get('name')!r}  {src_rate}fps -> {target_rate}fps")
        resample(out, target_rate, src_rate)

    out["name"] = new_name

    # Track-level source_range is optional; Resolve recomputes it from children.
    # Leaving a stale one behind is worse than leaving it out.
    out["source_range"] = None

    if drop_effects:
        for c in out["children"]:
            c["effects"] = []

    return out


# ─── Cold open (highlights + intro) ───────────────────────────────────────────

def parse_timestamp(ts: str) -> float:
    """HH:MM:SS[,mmm] -> seconds."""
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) != 3:
        raise ValueError(f"Cannot parse timestamp: {ts!r}")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def parse_highlights(path: Path) -> list:
    """
    Read highlights.md into a list of {idx, start, end, label} in cut-time
    seconds.  The Cut Time range IS the clip; the Duration column is a comment.
    """
    text = path.read_text(encoding="utf-8")
    row_re = re.compile(
        r"^\|\s*(\d+)\s*\|"          # 1 - index
        r"\s*([^|]+?)\s*\|"          # 2 - cut time range
        r"\s*([^|]*?)\s*\|"          # 3 - context
        r"\s*([^|]*?)\s*\|"          # 4 - label
        r"\s*([^|]*?)\s*\|",         # 5 - duration (informational)
        re.MULTILINE,
    )
    out = []
    for m in row_re.finditer(text):
        rng = m.group(2)
        if "-" not in rng:
            continue
        try:
            a, b = re.split(r"\s*-\s*", rng, maxsplit=1)
            start, end = parse_timestamp(a), parse_timestamp(b)
        except ValueError:
            continue
        if end <= start:
            print(f"  [WARN] highlight #{m.group(1)}: end is not after start "
                  f"({rng}) - skipping")
            continue
        out.append({
            "idx":   int(m.group(1)),
            "start": start,
            "end":   end,
            "label": m.group(4).strip() or f"Highlight {m.group(1)}",
        })
    return out


def slice_track(track: dict, t0_fr: float, t1_fr: float, rate: float) -> list:
    """
    Cut a sequential track between two timeline frame positions.

    Returns fresh children covering exactly [t0, t1).  Clips are trimmed by
    advancing their source start_time, so a highlight that straddles one of the
    edit's 25 cut points comes back as two clips with correct in-points rather
    than one clip with the wrong media under it.
    """
    out, cursor = [], 0
    for child in track.get("children", []):
        dur   = child["source_range"]["duration"]["value"]
        c0,c1 = cursor, cursor + dur
        cursor = c1
        if c1 <= t0_fr or c0 >= t1_fr:
            continue
        lead  = max(0, t0_fr - c0)          # trimmed off the head
        take  = min(c1, t1_fr) - max(c0, t0_fr)
        if take <= 0:
            continue
        piece = copy.deepcopy(child)
        sr    = piece["source_range"]
        sr["start_time"]["value"] = sr["start_time"]["value"] + lead
        sr["duration"]["value"]   = take
        out.append(piece)
    return out


def pad_to(children: list, total_fr: float, rate: float) -> list:
    """Append a Gap so a track's lead-in is exactly total_fr long."""
    have = sum(c["source_range"]["duration"]["value"] for c in children)
    if have < total_fr:
        children.append(make_gap(total_fr - have, rate))
    return children


def make_gap(duration_frames: float, rate: float) -> dict:
    return {
        "OTIO_SCHEMA":  "Gap.1",
        "metadata":     {},
        "name":         "",
        "source_range": {
            "OTIO_SCHEMA": "TimeRange.1",
            "duration":    rt(round(duration_frames), rate),
            "start_time":  rt(0.0, rate),
        },
        "effects": [], "markers": [], "enabled": True, "color": None,
    }


def make_media_clip(name: str, url: str, dur_fr: float, rate: float) -> dict:
    return {
        "OTIO_SCHEMA":  "Clip.2",
        "metadata":     {},
        "name":         name,
        "source_range": {
            "OTIO_SCHEMA": "TimeRange.1",
            "duration":    rt(round(dur_fr), rate),
            "start_time":  rt(0.0, rate),
        },
        "effects": [], "markers": [], "enabled": True, "color": None,
        "media_references": {
            "DEFAULT_MEDIA": {
                "OTIO_SCHEMA":            "ExternalReference.1",
                "metadata":               {},
                "name":                   "",
                "available_range":        {
                    "OTIO_SCHEMA": "TimeRange.1",
                    "duration":    rt(round(dur_fr), rate),
                    "start_time":  rt(0.0, rate),
                },
                "available_image_bounds": None,
                "target_url":             url,
            }
        },
        "active_media_reference_key": "DEFAULT_MEDIA",
    }


def probe_duration(path: Path) -> Optional[float]:
    """Seconds via ffprobe, or None when ffprobe isn't around."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30,
        )
        if out.returncode == 0 and out.stdout.strip():
            return float(out.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def make_timeline(name: str, tracks: list, rate: float) -> dict:
    return {
        "OTIO_SCHEMA": "Timeline.1",
        "metadata":    {},
        "name":        name,
        "global_start_time": rt(0.0, rate),
        "tracks": {
            "OTIO_SCHEMA":  "Stack.1",
            "metadata":     {},
            "name":         "tracks",
            "source_range": None,
            "effects":      [],
            "markers":      [],
            "enabled":      True,
            "color":        None,
            "children":     tracks,
        },
    }


def build_cold_open(video, memes, audio, captions, rate: float, args) -> int:
    """
    Prepend [highlight 1..n][intro] to every track, in place.

    Each highlight is lifted straight out of the assembled tracks, so a moment
    that has a meme or caption over it brings them along at the same relative
    position.  The intro is video-only, so the other tracks get a gap under it.

    Returns the lead-in length in frames.
    """
    highlights = parse_highlights(HIGHLIGHTS_MD)
    if not highlights:
        print(f"  [WARN] {HIGHLIGHTS_MD.name} has no usable rows - "
              f"skipping the cold open")
        return 0

    edit_frames = sum(c["source_range"]["duration"]["value"]
                      for c in video["children"])

    # ── Intro ─────────────────────────────────────────────────────────────
    intro_path = Path(args.intro) if args.intro else DEFAULT_INTRO
    intro_fr = 0
    if intro_path.exists():
        secs = args.intro_duration or probe_duration(intro_path)
        if secs is None:
            print(f"  [WARN] could not probe {intro_path.name} and no "
                  f"--intro-duration given - assuming 4s")
            secs = 4.0
        intro_fr = round(secs * rate)
    else:
        print(f"  [WARN] intro not found, cold open will have no intro:\n"
              f"         {intro_path}")

    # ── Slice the highlights out before anything is mutated ───────────────
    tracks = [t for t in (video, memes, audio, captions) if t is not None]
    lead = {id(t): [] for t in tracks}
    total_hl = 0

    print(f"  cold open:")
    for h in highlights:
        t0, t1 = round(h["start"] * rate), round(h["end"] * rate)
        if t0 >= edit_frames:
            print(f"    [WARN] #{h['idx']} {h['label']!r} starts past the end "
                  f"of the edit ({_fmt_ts(h['start'])}) - skipping")
            continue
        t1 = min(t1, edit_frames)
        span = t1 - t0
        for t in tracks:
            pad_to(lead[id(t)], total_hl, rate)          # align to this slot
            lead[id(t)].extend(slice_track(t, t0, t1, rate))
            pad_to(lead[id(t)], total_hl + span, rate)   # exact span, no drift
        total_hl += span
        carried = sum(
            1 for c in slice_track(memes, t0, t1, rate)
            if c["OTIO_SCHEMA"].startswith("Clip")) if memes is not None else 0
        print(f"    #{h['idx']}  {_fmt_ts(h['start'])} - {_fmt_ts(h['end'])}  "
              f"{span / rate:>5.1f}s  {h['label']}"
              f"{f'  (+{carried} meme)' if carried else ''}")

    if total_hl == 0 and intro_fr == 0:
        return 0

    # ── Intro sits after the highlights, video only ───────────────────────
    if intro_fr:
        video_lead = lead[id(video)]
        video_lead.append(make_media_clip(intro_path.stem, str(intro_path),
                                          intro_fr, rate))
        for t in tracks:
            if t is video:
                continue
            pad_to(lead[id(t)], total_hl + intro_fr, rate)
        print(f"    intro  {intro_fr / rate:>5.1f}s  {intro_path.name}")

    lead_in = total_hl + intro_fr

    # ── Prepend ───────────────────────────────────────────────────────────
    for t in tracks:
        pad_to(lead[id(t)], lead_in, rate)
        t["children"] = lead[id(t)] + t["children"]

    print(f"    lead-in total {_fmt_ts(lead_in / rate)} "
          f"({lead_in} frames) - everything after it shifts right")
    return lead_in


# ─── Reporting ────────────────────────────────────────────────────────────────

def _fmt_ts(secs: float) -> str:
    h = int(secs) // 3600
    m = (int(secs) % 3600) // 60
    s = int(secs) % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def describe(label: str, track: dict) -> float:
    """Print a one-line summary of a track and return its length in seconds."""
    rate   = track_rate(track) or 0
    frames = track_frames(track)
    secs   = frames / rate if rate else 0
    clips  = sum(1 for c in track["children"] if c["OTIO_SCHEMA"].startswith("Clip"))
    gaps   = sum(1 for c in track["children"] if c["OTIO_SCHEMA"].startswith("Gap"))
    print(f"  {label:<10}: {clips:>5} clips  {gaps:>5} gaps  "
          f"{rate:g}fps  {_fmt_ts(secs)}")
    return secs


def write_timeline(timeline: dict, path: Path) -> None:
    path.write_text(json.dumps(timeline, indent=4, ensure_ascii=False),
                    encoding="utf-8")
    size_kb = path.stat().st_size / 1024
    names   = [t["name"] for t in timeline["tracks"]["children"]]
    print(f"  [OK] {path.name}")
    print(f"       tracks: {', '.join(names)}")
    print(f"       {size_kb:,.1f} KB")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Combine the stage timelines into the two final OTIO files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python CombineFinalTimeline.py
  python CombineFinalTimeline.py --fps 60
  python CombineFinalTimeline.py --no-memes
  python CombineFinalTimeline.py --dry-run
        """
    )
    ap.add_argument("--fps", type=float, default=None,
                    help="Master frame rate (default: taken from the edit timeline)")
    ap.add_argument("--no-memes", dest="no_memes", action="store_true",
                    help="Skip the meme track even if memeeditplan.otio exists")
    ap.add_argument("--drop-caption-effects", dest="drop_caption_effects",
                    action="store_true",
                    help="Strip Resolve effects from the caption clips")
    ap.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="Report what would be combined without writing files")
    ap.add_argument("--no-intro", dest="no_intro", action="store_true",
                    help="Skip the cold open even if highlights.md exists")
    ap.add_argument("--intro", default=None,
                    help=f"Intro video (default: {DEFAULT_INTRO})")
    ap.add_argument("--intro-duration", dest="intro_duration", type=float,
                    default=None,
                    help="Intro length in seconds (default: probed with ffprobe)")
    args = ap.parse_args()

    print(f"  project root : {PROJECT_ROOT}")
    print()

    # ── Load the stages ───────────────────────────────────────────────────
    print("Reading stage timelines...")
    edit_tl    = load_otio(EDIT_OTIO,    "edit")
    caption_tl = load_otio(CAPTION_OTIO, "captions")
    meme_tl    = None if args.no_memes else load_otio(MEME_OTIO, "memes")

    if edit_tl is None:
        print("\n[ERROR] The edit timeline is required - run step 03 first.",
              file=sys.stderr)
        sys.exit(1)

    edit_video = find_track(edit_tl, name="Video 1", kind="Video")
    edit_audio = find_track(edit_tl, name="Audio 1", kind="Audio")

    if edit_video is None:
        print("\n[ERROR] No video track found in the edit timeline.", file=sys.stderr)
        sys.exit(1)

    # ── Master rate ───────────────────────────────────────────────────────
    rate = args.fps or track_rate(edit_video) or 60.0
    print(f"\n  master rate  : {rate:g} fps"
          f"{'  (from --fps)' if args.fps else '  (from the edit)'}")
    print()

    # ── Summarise what we have ────────────────────────────────────────────
    print("Contents:")
    edit_secs = describe("edit", edit_video)
    if edit_audio:
        describe("edit audio", edit_audio)

    meme_track = None
    if meme_tl:
        # The meme timeline carries a dummy "Video" track alongside "Memes"; that
        # one only exists to give the plan a length, so it is deliberately dropped.
        meme_track = find_track(meme_tl, name="Memes")
        if meme_track is None:
            print("  [WARN] memes    : no 'Memes' track found - skipping")
        else:
            meme_secs = describe("memes", meme_track)
            if meme_secs > edit_secs + 1:
                print(f"  [WARN] memes run {_fmt_ts(meme_secs - edit_secs)} past the "
                      f"end of the edit - check the **Video:** duration in "
                      f"memeeditplan.md")

    caption_track = None
    if caption_tl:
        caption_track = find_track(caption_tl, name="Video 1", kind="Video")
        if caption_track is None:
            print("  [WARN] captions : no video track found - skipping")
        else:
            cap_secs = describe("captions", caption_track)
            if cap_secs > edit_secs + 1:
                print(f"  [WARN] captions run {_fmt_ts(cap_secs - edit_secs)} past "
                      f"the end of the edit - was the SRT made from this cut?")

    # ── Assemble, bottom track first ──────────────────────────────────────
    print("\nAssembling...")

    video_prep = prepare_track(edit_video, "Video 1", rate)
    memes_prep = (prepare_track(meme_track, "Video 2", rate)
                  if meme_track is not None else None)
    audio_prep = (prepare_track(edit_audio, "Audio 1", rate)
                  if edit_audio is not None else None)
    cap_prep = None
    if caption_track is not None:
        cap_prep = prepare_track(
            caption_track,
            f"Video {2 + (1 if meme_track is not None else 0)}",
            rate,
            drop_effects=args.drop_caption_effects,
        )

    # ── Cold open ─────────────────────────────────────────────────────────
    # Built here rather than as a separate prepend pass: a standalone prepend
    # could be run twice and stack two intros.  As part of assembly it simply
    # cannot happen -- every run rebuilds from the stage files.
    if not args.no_intro and HIGHLIGHTS_MD.exists():
        build_cold_open(video_prep, memes_prep, audio_prep, cap_prep, rate, args)
    elif not args.no_intro:
        print(f"  (no {HIGHLIGHTS_MD.name} - skipping the cold open)")

    project = PROJECT_ROOT.name

    base = [video_prep]
    if memes_prep is not None:
        base.append(memes_prep)
    if audio_prep is not None:
        base.append(audio_prep)

    nocap = make_timeline(f"{project} - Final (No Captions)",
                          copy.deepcopy(base), rate)

    withcap = None
    if cap_prep is not None:
        # Captions ride on top; they sit before the audio track in the children
        # list only for tidiness -- kind keeps them apart in the editor anyway.
        with_tracks = copy.deepcopy(base)
        insert_at = len(with_tracks) - (1 if audio_prep is not None else 0)
        with_tracks.insert(insert_at, copy.deepcopy(cap_prep))
        withcap = make_timeline(f"{project} - Final (With Captions)",
                                with_tracks, rate)

    if args.dry_run:
        print("\n(Dry run - no files written.)")
        return

    # ── Write ─────────────────────────────────────────────────────────────
    print()
    write_timeline(nocap, OUT_NOCAP)
    if withcap is not None:
        write_timeline(withcap, OUT_WITHCAP)
    else:
        print(f"  [SKIP] {OUT_WITHCAP.name} - no caption track available")

    print("\nDone.")


if __name__ == "__main__":
    main()
