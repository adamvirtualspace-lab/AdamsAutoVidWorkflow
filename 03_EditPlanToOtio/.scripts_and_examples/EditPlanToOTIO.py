"""
EditPlanToOTIO.py — Convert editplan.md to a Resolve-compatible .otio file.

Parses the markdown edit plan, extracts KEEP segments from the summary table,
auto-detects frame rate from source filename, and writes an OTIO timeline.

Usage:
    python EditPlanToOTIO.py <editplan.md> [--output out.otio] [--source video.mp4] [--fps 60]

Example:
    python EditPlanToOTIO.py E:/MyProject/editplan.md
    python EditPlanToOTIO.py editplan.md --output timeline.otio --fps 30
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────
#  OTIO schema constants
# ──────────────────────────────────────────────────────────────────────

def _rt(rate, value):
    """RationalTime dict."""
    return {
        "OTIO_SCHEMA": "RationalTime.1",
        "rate": float(rate),
        "value": float(value),
    }


def _tr(start_rt, duration_rt):
    """TimeRange dict."""
    return {
        "OTIO_SCHEMA": "TimeRange.1",
        "duration": duration_rt,
        "start_time": start_rt,
    }


def _ext_ref(target_url):
    """ExternalReference dict (Resolve Clip.2 style)."""
    return {
        "OTIO_SCHEMA": "ExternalReference.1",
        "metadata": {},
        "name": "",
        "available_range": None,
        "available_image_bounds": None,
        "target_url": target_url,
    }


def _clip(name, source_start, source_dur, fps, clip_id, target_url):
    """Clip.2 dict with Resolve metadata."""
    return {
        "OTIO_SCHEMA": "Clip.2",
        "metadata": {"Resolve_OTIO": {"Link Group ID": clip_id}},
        "name": name,
        "source_range": _tr(_rt(fps, source_start), _rt(fps, source_dur)),
        "effects": [],
        "markers": [],
        "enabled": True,
        "color": None,
        "media_references": {"DEFAULT_MEDIA": _ext_ref(target_url)},
        "active_media_reference_key": "DEFAULT_MEDIA",
    }


def build_timeline(clips, fps, timeline_name="Timeline"):
    """Build the full OTIO Timeline.1 JSON dict with Video + Audio tracks."""
    video_track = {
        "OTIO_SCHEMA": "Track.1",
        "metadata": {"Resolve_OTIO": {"Locked": False}},
        "name": "Video 1",
        "kind": "Video",
        "source_range": None,
        "effects": [],
        "markers": [],
        "enabled": True,
        "color": None,
        "children": clips,
    }
    audio_track = {
        "OTIO_SCHEMA": "Track.1",
        "metadata": {
            "Resolve_OTIO": {
                "Audio Type": "Stereo",
                "Locked": False,
                "SoloOn": False,
            }
        },
        "name": "Audio 1",
        "kind": "Audio",
        "source_range": None,
        "effects": [],
        "markers": [],
        "enabled": True,
        "color": None,
        "children": clips,
    }
    return {
        "OTIO_SCHEMA": "Timeline.1",
        "metadata": {"Resolve_OTIO": {"Resolve OTIO Meta Version": "1.0"}},
        "name": timeline_name,
        "global_start_time": _rt(fps, 0),
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "metadata": {},
            "name": "tracks",
            "source_range": None,
            "effects": [],
            "markers": [],
            "enabled": True,
            "color": None,
            "children": [video_track, audio_track],
        },
    }


# ──────────────────────────────────────────────────────────────────────
#  Timecode parsing
# ──────────────────────────────────────────────────────────────────────

def tc_to_seconds(tc: str) -> float:
    """Convert HH:MM:SS or M:SS timecode to seconds."""
    tc = tc.strip()
    parts = tc.split(":")
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    else:
        raise ValueError(f"Cannot parse timecode: {tc}")


def tc_to_frames(tc: str, fps: float) -> int:
    return int(round(tc_to_seconds(tc) * fps))


# ──────────────────────────────────────────────────────────────────────
#  EditPlan parser
# ──────────────────────────────────────────────────────────────────────

class EditPlan:
    """Holds parsed data from an editplan.md file."""

    def __init__(self):
        self.segments = []  # list of dicts: {start, end, action, notes}
        self.source_path = None
        self.fps = 60.0
        self.timeline_name = "Timeline"
        self.clip_basename = "source.mp4"

    @property
    def keep_segments(self):
        return [s for s in self.segments if s["action"] == "KEEP"]


def parse_editplan(filepath: str) -> EditPlan:
    """Parse an editplan.md and return an EditPlan."""
    plan = EditPlan()
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()

    # --- Extract source path ---
    m = re.search(r"Source media reference:\s*`?([^`\n\r]+)`?", text)
    if m:
        plan.source_path = m.group(1).strip()
        plan.clip_basename = os.path.basename(plan.source_path)

    # --- Extract timeline name from heading ---
    m = re.search(r"^#\s+(.+?)(?:\s*-\s*Edit Plan)?\s*$", text, re.MULTILINE)
    if m:
        plan.timeline_name = m.group(1).strip()

    # --- Detect fps from source filename ---
    fps_match = re.search(r"[-_](\d+)fps", plan.clip_basename, re.IGNORECASE)
    if fps_match:
        plan.fps = float(fps_match.group(1))

    # --- Parse summary table ---
    # Look for pipe-delimited table with Keep/Cut, Start, End columns
    in_table = False
    table_header_found = False
    for line in text.splitlines():
        stripped = line.strip()

        # Detect table start: a row with | # | Keep/Cut | Start | End | ...
        if not table_header_found:
            if re.match(r"^\|\s*#\s*\|\s*Keep.*Cut\s*\|", stripped, re.IGNORECASE):
                table_header_found = True
            continue

        # Skip separator lines like |---|...|
        if re.match(r"^\|[\s\-|:]*$", stripped):
            in_table = True
            continue

        if not in_table:
            continue

        # Parse data rows
        if not stripped.startswith("|"):
            break  # end of table

        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 4:
            continue

        # cells[0] = row number, cells[1] = KEEP/CUT/TRIM, cells[2] = Start, cells[3] = End
        action = cells[1].upper().strip()
        if "KEEP" not in action and "CUT" not in action and "TRIM" not in action:
            continue

        is_keep = "KEEP" in action
        # TRIM rows that say KEEP are treated as keep; rows that say CUT or TRIM are cut

        try:
            start_tc = cells[2].strip()
            end_tc = cells[3].strip()
        except IndexError:
            continue

        # Determine if this is a keep or cut
        if "KEEP" == action:
            effective_action = "KEEP"
        elif "CUT" == action:
            effective_action = "CUT"
        elif "TRIM" == action:
            effective_action = "KEEP"  # TRIM = keep but tighten internally
        else:
            effective_action = "CUT"

        plan.segments.append(
            {
                "start": start_tc,
                "end": end_tc,
                "action": effective_action,
                "notes": cells[4].strip() if len(cells) > 4 else "",
            }
        )

    return plan


# ──────────────────────────────────────────────────────────────────────
#  OTIO writer
# ──────────────────────────────────────────────────────────────────────

def write_otio(
    plan: EditPlan,
    output_path: str,
    fps: float = None,
    source_path: str = None,
    timeline_name: str = None,
):
    """Generate an OTIO file from an EditPlan."""
    if fps is None:
        fps = plan.fps
    if source_path is None:
        source_path = plan.source_path
    if timeline_name is None:
        timeline_name = plan.timeline_name
    if not source_path:
        raise ValueError("No source media path specified. Use --source or add it to the editplan.")

    if not os.path.isabs(source_path):
        source_path = os.path.abspath(os.path.join(os.path.dirname(output_path), "..", source_path))
    clip_name = os.path.basename(source_path)

    clips = []
    for i, seg in enumerate(plan.keep_segments):
        sf = tc_to_frames(seg["start"], fps)
        ef = tc_to_frames(seg["end"], fps)
        dur = ef - sf
        if dur <= 0:
            print(f"  Warning: zero-duration segment #{i+1} ({seg['start']}–{seg['end']}), skipping")
            continue
        clips.append(_clip(clip_name, sf, dur, fps, len(clips) + 1, source_path))

    timeline = build_timeline(clips, fps, timeline_name)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(timeline, f, indent=4, ensure_ascii=False)

    total_frames = sum(c["source_range"]["duration"]["value"] for c in clips)
    total_secs = total_frames / fps
    print(f"Done: {len(clips)} clips, {int(total_frames)} frames, "
          f"{total_secs:.1f}s ({total_secs/60:.1f} min)")
    print(f"  Source: {source_path}")
    print(f"  FPS: {fps}")
    print(f"  Output: {output_path}")


# ──────────────────────────────────────────────────────────────────────
#  CLI
# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Convert editplan.md to a Resolve-compatible .otio timeline."
    )
    parser.add_argument(
        "editplan",
        help="Path to editplan.md",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output .otio path (default: <editplan_dir>/<name>_GeneratedOtio.otio)",
        default=None,
    )
    parser.add_argument(
        "--source", "-s",
        help="Source media file path (overrides editplan reference)",
        default=None,
    )
    parser.add_argument(
        "--fps",
        help="Frame rate (overrides auto-detection from filename)",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--name",
        help="Timeline name (overrides editplan title)",
        default=None,
    )

    args = parser.parse_args()

    if not os.path.isfile(args.editplan):
        print(f"Error: editplan not found: {args.editplan}", file=sys.stderr)
        sys.exit(1)

    print(f"Parsing: {args.editplan}")
    plan = parse_editplan(args.editplan)

    keep = plan.keep_segments
    cuts = [s for s in plan.segments if s["action"] == "CUT"]
    print(f"  Segments: {len(plan.segments)} total ({len(keep)} keep, {len(cuts)} cut)")

    if not keep:
        print("Error: no KEEP segments found in editplan.", file=sys.stderr)
        sys.exit(1)

    fps = args.fps or plan.fps
    source = args.source or plan.source_path
    name = args.name or plan.timeline_name

    if args.output:
        out = args.output
    else:
        edit_dir = os.path.dirname(os.path.abspath(args.editplan))
        safe_name = re.sub(r"[^\w\- ]", "", plan.timeline_name).strip().replace(" ", "_")
        out = os.path.join(edit_dir, f"{safe_name}_GeneratedOtio.otio")

    print()
    write_otio(plan, out, fps=fps, source_path=source, timeline_name=name)


if __name__ == "__main__":
    main()
