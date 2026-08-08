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

    base = [prepare_track(edit_video, "Video 1", rate)]
    if meme_track is not None:
        base.append(prepare_track(meme_track, "Video 2", rate))
    if edit_audio is not None:
        base.append(prepare_track(edit_audio, "Audio 1", rate))

    project = PROJECT_ROOT.name

    nocap = make_timeline(f"{project} - Final (No Captions)",
                          copy.deepcopy(base), rate)

    withcap = None
    if caption_track is not None:
        cap_prepared = prepare_track(
            caption_track,
            f"Video {2 + (1 if meme_track is not None else 0)}",
            rate,
            drop_effects=args.drop_caption_effects,
        )
        # Captions ride on top, but below the audio track in the children list
        # only because kind keeps them apart in the editor anyway.
        with_tracks = copy.deepcopy(base)
        insert_at = len(with_tracks) - (1 if edit_audio is not None else 0)
        with_tracks.insert(insert_at, cap_prepared)
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
