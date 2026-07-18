#!/usr/bin/env python3
"""
md_to_meme_otio.py
Convert a meme edit plan Markdown file into an OTIO (OpenTimelineIO) timeline.

No external dependencies — generates OTIO JSON directly.

Expected .md structure:
  - H1 heading used as the timeline name
  - Header block:  **Video:** `filename.mp4` (17m 56s)
  - Notes section: meme images located in `E:\\Path\\To\\Memes\\`
                   SRT timestamps use the original ... start time (01:00:00)
  - Table columns: # | SRT Time | Subtitle Context | Meme Image | Meme Name | Duration

Usage:
    python md_to_meme_otio.py plan.md
    python md_to_meme_otio.py plan.md -o output.otio
    python md_to_meme_otio.py plan.md -o output.otio --video-path "E:/Project/video.mp4"
    python md_to_meme_otio.py plan.md --fps 24 --use-srt-duration
"""

import re
import json
import argparse
import sys
from pathlib import Path
from typing import Optional

DEFAULT_FPS = 30


# ─── OTIO JSON primitives ─────────────────────────────────────────────────────
# Matches the exact key ordering in the reference .otio files.

def rt(value: int, rate: int = DEFAULT_FPS) -> dict:
    """RationalTime node."""
    return {
        "OTIO_SCHEMA": "RationalTime.1",
        "rate":        rate,
        "value":       int(value),
    }


def tr(duration_frames: int, start_frames: int = 0, rate: int = DEFAULT_FPS) -> dict:
    """TimeRange node.  duration comes before start_time (matches OTIO serialiser)."""
    return {
        "OTIO_SCHEMA": "TimeRange.1",
        "duration":    rt(duration_frames, rate),
        "start_time":  rt(start_frames,    rate),
    }


def external_ref(url: str, avail_frames: int, rate: int = DEFAULT_FPS) -> dict:
    """ExternalReference media reference."""
    return {
        "OTIO_SCHEMA":            "ExternalReference.1",
        "metadata":               {},
        "name":                   "",
        "available_range":        tr(avail_frames, 0, rate),
        "available_image_bounds": None,
        "target_url":             url,
    }


def make_gap(duration_frames: int, rate: int = DEFAULT_FPS) -> dict:
    return {
        "OTIO_SCHEMA":  "Gap.1",
        "metadata":     {},
        "name":         "",
        "source_range": tr(duration_frames, 0, rate),
        "effects":      [],
        "markers":      [],
        "enabled":      True,
        "color":        None,
    }


def make_still_clip(name: str, url: str, display_frames: int,
                    rate: int = DEFAULT_FPS) -> dict:
    """
    Meme image clip.
    source_range.duration = how long to display the still.
    available_range.duration = 1 frame (it's a still image, not a video).
    """
    return {
        "OTIO_SCHEMA":                "Clip.2",
        "metadata":                   {},
        "name":                       name,
        "source_range":               tr(display_frames, 0, rate),
        "effects":                    [],
        "markers":                    [],
        "enabled":                    True,
        "color":                      None,
        "media_references":           {"DEFAULT_MEDIA": external_ref(url, 1, rate)},
        "active_media_reference_key": "DEFAULT_MEDIA",
    }


def make_video_clip(name: str, url: str, duration_frames: int,
                    rate: int = DEFAULT_FPS) -> dict:
    """Full-length video clip (available_range == source_range)."""
    return {
        "OTIO_SCHEMA":                "Clip.2",
        "metadata":                   {},
        "name":                       name,
        "source_range":               tr(duration_frames, 0, rate),
        "effects":                    [],
        "markers":                    [],
        "enabled":                    True,
        "color":                      None,
        "media_references":           {"DEFAULT_MEDIA": external_ref(url, duration_frames, rate)},
        "active_media_reference_key": "DEFAULT_MEDIA",
    }


def make_track(name: str, children: list, total_frames: int,
               rate: int = DEFAULT_FPS) -> dict:
    return {
        "OTIO_SCHEMA":  "Track.1",
        "metadata":     {},
        "name":         name,
        "source_range": tr(total_frames, 0, rate),
        "effects":      [],
        "markers":      [],
        "enabled":      True,
        "color":        None,
        "children":     children,
        "kind":         "Video",
    }


def make_timeline(name: str, tracks: list, total_frames: int,
                  rate: int = DEFAULT_FPS) -> dict:
    return {
        "OTIO_SCHEMA": "Timeline.1",
        "metadata":    {},
        "name":        name,
        "global_start_time": None,
        "tracks": {
            "OTIO_SCHEMA":  "Stack.1",
            "metadata":     {},
            "name":         "tracks",
            "source_range": tr(total_frames, 0, rate),
            "effects":      [],
            "markers":      [],
            "enabled":      True,
            "color":        None,
            "children":     tracks,
        },
    }


# ─── Markdown parsing ─────────────────────────────────────────────────────────

def parse_timestamp(ts: str) -> float:
    """
    Parse a timestamp string to seconds (float).
    Accepts: HH:MM:SS  or  HH:MM:SS,mmm  or  HH:MM:SS.mmm
    """
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) != 3:
        raise ValueError(f"Cannot parse timestamp: {ts!r}")
    h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    return h * 3600 + m * 60 + s


def parse_meme_plan(text: str) -> dict:
    """
    Parse a meme edit plan .md file into a structured dict.

    Extracts:
        timeline_name       (str)  — from H1 heading
        video_file          (str)  — filename from **Video:** header
        video_duration_secs (int)  — total seconds from **Video:** header
        meme_dir            (str)  — forward-slash path, no trailing slash
        srt_offset_secs     (float)— SRT t=0 in absolute seconds (e.g. 3600.0 for 01:00:00)
        memes               (list) — sorted by srt_start
    """

    # ── Timeline name ─────────────────────────────────────────────────────
    h1 = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    timeline_name = h1.group(1).strip() if h1 else "Memes"

    # ── Video header: **Video:** `file.mp4` (17m 56s) ────────────────────
    vid_m = re.search(
        r"\*\*Video:\*\*\s+`([^`]+)`\s+\((\d+)m\s+(\d+)s\)",
        text
    )
    if vid_m:
        video_file        = vid_m.group(1).strip()
        video_dur_secs    = int(vid_m.group(2)) * 60 + int(vid_m.group(3))
    else:
        video_file        = "video.mp4"
        video_dur_secs    = 0

    # ── Meme image directory from Notes ──────────────────────────────────
    #    e.g.  All meme images located in `E:\Foo\Memes\`
    dir_m = re.search(r"meme images located in\s+`([^`]+)`", text, re.IGNORECASE)
    if dir_m:
        meme_dir = dir_m.group(1).strip().replace("\\", "/").rstrip("/")
    else:
        meme_dir = ""

    # ── SRT offset from Notes ─────────────────────────────────────────────
    #    e.g.  SRT timestamps use the original ... start time (01:00:00)
    off_m = re.search(
        r"start\s+time\s*\(\s*(\d+:\d+:\d+(?:[.,]\d+)?)\s*\)",
        text, re.IGNORECASE
    )
    srt_offset: Optional[float] = parse_timestamp(off_m.group(1)) if off_m else None

    # ── Table rows ────────────────────────────────────────────────────────
    # | # | HH:MM:SS - HH:MM:SS | subtitle | image.ext | Meme Name | Xs |
    row_re = re.compile(
        r"^\|\s*(\d+)\s*\|"         # col 1 — row index
        r"\s*([^|]+?)\s*\|"          # col 2 — SRT time range
        r"\s*([^|]+?)\s*\|"          # col 3 — subtitle context
        r"\s*([^|]+?)\s*\|"          # col 4 — meme image filename
        r"\s*([^|]+?)\s*\|"          # col 5 — meme name / label
        r"\s*(\d+)s\s*\|",           # col 6 — duration in whole seconds
        re.MULTILINE,
    )

    memes = []
    for m in row_re.finditer(text):
        srt_range = m.group(2).strip()
        ts_parts  = re.split(r"\s*-\s*", srt_range, maxsplit=1)
        srt_start = parse_timestamp(ts_parts[0])
        srt_end   = parse_timestamp(ts_parts[1]) if len(ts_parts) > 1 else None

        memes.append({
            "idx":           int(m.group(1)),
            "srt_start":     srt_start,
            "srt_end":       srt_end,
            "subtitle":      m.group(3).strip().strip('"'),
            "meme_image":    m.group(4).strip(),
            "meme_name":     m.group(5).strip(),
            "duration_secs": int(m.group(6)),
        })

    memes.sort(key=lambda x: x["srt_start"])

    # Auto-detect offset if not found in Notes
    if srt_offset is None:
        if memes:
            srt_offset = memes[0]["srt_start"]
            print(f"  [INFO] SRT offset auto-detected from first meme: "
                  f"{srt_offset:.0f}s  ({_fmt_ts(srt_offset)})")
        else:
            srt_offset = 0.0

    return {
        "timeline_name":        timeline_name,
        "video_file":           video_file,
        "video_duration_secs":  video_dur_secs,
        "meme_dir":             meme_dir,
        "srt_offset_secs":      srt_offset,
        "memes":                memes,
    }


# ─── OTIO builder ─────────────────────────────────────────────────────────────

def build_meme_otio(
    plan:                dict,
    fps:                 int            = DEFAULT_FPS,
    video_path_override: Optional[str]  = None,
    use_srt_duration:    bool           = False,
) -> dict:
    """
    Build an OTIO timeline dict from a parsed meme plan.

    Memes track layout (sequential children):
        [optional leading Gap]
        [Clip] [Gap] [Clip] [Gap] ... [Clip]
        [optional trailing Gap]

    Each Clip's track-start-position is computed as:
        (meme.srt_start - srt_offset) * fps

    Gaps fill the spaces between clips to maintain absolute positioning.

    Args:
        plan:                Parsed plan dict from parse_meme_plan().
        fps:                 Output frame rate.
        video_path_override: If set, used as the video track URL instead of
                             deriving it from the meme_dir + video_file.
        use_srt_duration:    If True, display duration = (srt_end - srt_start)
                             instead of the Duration column value.
    """
    rate      = fps
    srt_off   = plan["srt_offset_secs"]
    total_fr  = round(plan["video_duration_secs"] * rate)
    meme_dir  = plan["meme_dir"]

    # ── Resolve video URL ─────────────────────────────────────────────────
    if video_path_override:
        video_url = video_path_override.replace("\\", "/")
    elif meme_dir:
        # Derive by stripping the last path component ("Memes") from meme_dir
        parent    = "/".join(meme_dir.split("/")[:-1])
        video_url = f"{parent}/{plan['video_file']}"
    else:
        video_url = plan["video_file"]

    # ── Video track ───────────────────────────────────────────────────────
    video_track = make_track(
        "Video",
        [make_video_clip(plan["video_file"], video_url, total_fr, rate)],
        total_fr,
        rate,
    )

    # ── Memes track ───────────────────────────────────────────────────────
    children  = []
    cursor_fr = 0   # current write-head position in the track (frames)

    for meme in plan["memes"]:
        # Absolute frame position of this meme's start in the output timeline
        meme_start_fr = round((meme["srt_start"] - srt_off) * rate)

        # Display duration in frames
        if use_srt_duration and meme["srt_end"] is not None:
            dur_fr = max(1, round((meme["srt_end"] - meme["srt_start"]) * rate))
        else:
            dur_fr = max(1, meme["duration_secs"] * rate)

        # Gap before this clip
        gap_fr = meme_start_fr - cursor_fr
        if gap_fr < 0:
            print(
                f"  [WARN] Meme #{meme['idx']} '{meme['meme_name']}': "
                f"overlaps previous clip by {-gap_fr} frames — skipping gap."
            )
            gap_fr = 0
        if gap_fr > 0:
            children.append(make_gap(gap_fr, rate))

        # Meme clip
        url = f"{meme_dir}/{meme['meme_image']}" if meme_dir else meme["meme_image"]
        children.append(make_still_clip(meme["meme_name"], url, dur_fr, rate))

        cursor_fr = meme_start_fr + dur_fr

    # Trailing gap to fill the rest of the timeline
    trail_fr = total_fr - cursor_fr
    if trail_fr > 0:
        children.append(make_gap(trail_fr, rate))
    elif trail_fr < 0:
        print(
            f"  [WARN] Memes track overruns video timeline by {-trail_fr} frames "
            f"({-trail_fr / rate:.2f}s). Last meme or video duration may need adjusting."
        )

    meme_track = make_track("Memes", children, total_fr, rate)

    return make_timeline(plan["timeline_name"], [video_track, meme_track], total_fr, rate)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_ts(secs: float) -> str:
    """Format seconds as HH:MM:SS for display."""
    h  = int(secs) // 3600
    m  = (int(secs) % 3600) // 60
    s  = int(secs) % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _print_plan_summary(plan: dict, fps: int) -> None:
    """Pretty-print what was parsed."""
    total_fr = round(plan["video_duration_secs"] * fps)
    off      = plan["srt_offset_secs"]
    print(f"\n  Timeline  : {plan['timeline_name']}")
    print(f"  Video     : {plan['video_file']}  "
          f"({plan['video_duration_secs']}s = {plan['video_duration_secs']//60}m "
          f"{plan['video_duration_secs']%60}s  →  {total_fr} frames @ {fps}fps)")
    print(f"  SRT offset: {off:.0f}s  ({_fmt_ts(off)})")
    print(f"  Meme dir  : {plan['meme_dir'] or '(not found in Notes)'}")
    print(f"  Memes     : {len(plan['memes'])} entries\n")

    print(f"  {'#':>3}  {'Start':>8}  {'Dur':>5}  {'Image':<35}  Name")
    print(f"  {'-'*3}  {'-'*8}  {'-'*5}  {'-'*35}  {'-'*30}")
    for m in plan["memes"]:
        rel = m["srt_start"] - plan["srt_offset_secs"]
        print(
            f"  {m['idx']:>3}  {_fmt_ts(rel):>8}  {m['duration_secs']:>4}s"
            f"  {m['meme_image']:<35}  {m['meme_name']}"
        )
    print()


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a meme edit plan .md to an OTIO timeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python md_to_meme_otio.py plan.md
  python md_to_meme_otio.py plan.md -o SR01_memes.otio
  python md_to_meme_otio.py plan.md --video-path "E:/AdamsRoadTrips/SR01/video.mp4"
  python md_to_meme_otio.py plan.md --fps 24 --use-srt-duration
        """
    )
    parser.add_argument(
        "input_md",
        help="Path to the meme edit plan .md file"
    )
    parser.add_argument(
        "-o", "--output",
        help="Output .otio file path (default: same name as input with .otio extension)"
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=DEFAULT_FPS,
        help=f"Frame rate for the OTIO timeline (default: {DEFAULT_FPS})"
    )
    parser.add_argument(
        "--video-path",
        dest="video_path",
        help="Override the video file URL in the OTIO output "
             "(default: derived from meme dir + video filename in the .md)"
    )
    parser.add_argument(
        "--use-srt-duration",
        dest="use_srt_duration",
        action="store_true",
        help="Use (srt_end − srt_start) as meme display duration "
             "instead of the explicit Duration column value"
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Parse and preview the plan without writing any files"
    )
    args = parser.parse_args()

    # ── Read input ────────────────────────────────────────────────────────
    md_path = Path(args.input_md)
    if not md_path.exists():
        print(f"[ERROR] File not found: '{md_path}'", file=sys.stderr)
        sys.exit(1)

    text = md_path.read_text(encoding="utf-8")

    # ── Parse ─────────────────────────────────────────────────────────────
    print(f"Parsing '{md_path.name}'...")
    try:
        plan = parse_meme_plan(text)
    except Exception as e:
        print(f"[ERROR] Parse failed: {e}", file=sys.stderr)
        sys.exit(1)

    _print_plan_summary(plan, args.fps)

    if not plan["memes"]:
        print("[ERROR] No meme entries found — check the table format.", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print("(Dry run — no file written.)")
        return

    # ── Build OTIO ────────────────────────────────────────────────────────
    print(f"Building OTIO ({args.fps} fps)...")
    otio = build_meme_otio(
        plan,
        fps=args.fps,
        video_path_override=args.video_path,
        use_srt_duration=args.use_srt_duration,
    )

    # ── Write output ──────────────────────────────────────────────────────
    out_path = Path(args.output) if args.output else md_path.with_suffix(".otio")
    out_path.write_text(
        json.dumps(otio, indent=4, ensure_ascii=False),
        encoding="utf-8",
    )

    # Quick sanity check: count clips in output
    out_text  = out_path.read_text(encoding="utf-8")
    clip_count = out_text.count('"OTIO_SCHEMA": "Clip.2"')
    gap_count  = out_text.count('"OTIO_SCHEMA": "Gap.1"')
    print(
        f"  Written {len(plan['memes'])} meme clips + "
        f"{gap_count} gaps  →  {out_path}"
    )
    print(f"\n[OK] '{out_path}'  ({out_path.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
