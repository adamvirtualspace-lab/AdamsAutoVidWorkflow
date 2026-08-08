#!/usr/bin/env python3
"""
srt_to_otio.py

Convert an SRT subtitle file into an OpenTimelineIO (.otio) timeline made of
DaVinci Resolve-style Fusion "Text+" title clips -- one per subtitle line --
sitting on a single video track, with Gaps filling the space between cues.

The output structure (Timeline.1 / Stack.1 / Track.1 / Gap.1 / Clip.2 with a
"Rich"-kind GeneratorReference) mirrors what DaVinci Resolve itself writes
out when you export an OTIO containing Text+ clips, so the result can be
imported straight back into Resolve, or read by any OTIO-aware tool.

Timing logic
------------
DaVinci Resolve timelines conventionally start at 01:00:00:00 instead of
00:00:00:00. This script assumes your SRT timestamps were authored against
that same 1-hour offset (this is what you get if you generated the SRT from
a Resolve timeline). Every cue's frame position is therefore:

    abs_frame          = round(cue_seconds * fps)
    session_start_frame = round(start_timecode_seconds * fps)
    track_frame          = abs_frame - session_start_frame

If your SRT is zero-based instead (starts counting from 00:00:00,000), just
pass --start-tc 00:00:00:00.

Usage
-----
    python srt_to_otio.py input.srt output.otio
    python srt_to_otio.py input.srt output.otio --fps 60 --start-tc 01:00:00:00
    python srt_to_otio.py input.srt output.otio --font "Open Sans" --font-size 64 \
        --track-name "Video 1"

Only the Python standard library is required.
"""

import argparse
import copy
import html
import json
import re
import sys


# --------------------------------------------------------------------------
# SRT parsing
# --------------------------------------------------------------------------

_SRT_TIME_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")


def parse_srt_timestamp(ts: str) -> float:
    """Convert 'HH:MM:SS,mmm' (or with '.') into seconds as a float."""
    m = _SRT_TIME_RE.match(ts.strip())
    if not m:
        raise ValueError(f"Unrecognized SRT timestamp: {ts!r}")
    h, mi, s, ms = m.groups()
    ms = ms.ljust(3, "0")  # tolerate 1-2 digit millisecond fields
    return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms) / 1000.0


def timecode_to_seconds(tc: str, fps: float) -> float:
    """Convert 'HH:MM:SS:FF' or 'HH:MM:SS;FF' timecode into seconds."""
    tc = tc.strip().replace(";", ":")
    parts = tc.split(":")
    if len(parts) != 4:
        raise ValueError(f"--start-tc must look like HH:MM:SS:FF, got {tc!r}")
    h, mi, s, f = (int(p) for p in parts)
    return h * 3600 + mi * 60 + s + f / fps


def parse_srt(path: str):
    """Tolerant SRT parser.

    Returns a list of dicts: {'index': int, 'start': float, 'end': float,
    'lines': [str, ...]} sorted by start time. Handles \\r\\n line endings,
    a BOM, and blocks that are missing their numeric index line.
    """
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        raw = f.read()

    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", raw.strip())

    cues = []
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        if len(lines) < 2:
            continue

        time_line_i = None
        for i, ln in enumerate(lines):
            if "-->" in ln:
                time_line_i = i
                break
        if time_line_i is None:
            continue  # no timing info in this block, skip it

        time_line = lines[time_line_i]
        text_lines = lines[time_line_i + 1:]

        # index is whatever came before the timing line (usually one line);
        # fall back to sequential numbering if it isn't a plain integer.
        index_candidates = lines[:time_line_i]
        try:
            index = int(index_candidates[-1].strip())
        except (ValueError, IndexError):
            index = len(cues) + 1

        start_str, end_str = [p.strip() for p in time_line.split("-->")]
        end_str = end_str.split(" ")[0]  # drop any trailing cue-settings

        cues.append({
            "index": index,
            "start": parse_srt_timestamp(start_str),
            "end": parse_srt_timestamp(end_str),
            "lines": text_lines,
        })

    cues.sort(key=lambda c: c["start"])
    return cues


# --------------------------------------------------------------------------
# OTIO building blocks
# --------------------------------------------------------------------------

def rational_time(value: float, rate: float) -> dict:
    return {"OTIO_SCHEMA": "RationalTime.1", "rate": rate, "value": float(value)}


def time_range(start_value: float, duration_value: float, rate: float) -> dict:
    return {
        "OTIO_SCHEMA": "TimeRange.1",
        "duration": rational_time(duration_value, rate),
        "start_time": rational_time(start_value, rate),
    }


def make_gap(duration_frames: int, rate: float) -> dict:
    return {
        "OTIO_SCHEMA": "Gap.1",
        "metadata": {},
        "name": "",
        "source_range": time_range(0, duration_frames, rate),
        "effects": [],
        "markers": [],
        "enabled": True,
    }


def _clip_level_effects() -> list:
    """The standard set of (mostly inert) clip-level Resolve effects that
    Resolve itself attaches to every Text+ clip. Dynamic Zoom is left
    disabled with default keyframes since it has no visual effect while off.
    """
    def eff(display_type, name, etype, enabled=True, parameters=None):
        return {
            "OTIO_SCHEMA": "Effect.1",
            "metadata": {
                "Resolve_OTIO": {
                    "Display Type": display_type,
                    "Effect Name": name,
                    "Enabled": enabled,
                    "Name": name,
                    "Parameters": parameters or [],
                    "Type": etype,
                }
            },
            "name": "",
            "effect_name": "Resolve Effect",
        }

    dynamic_zoom_params = [
        {
            "Default Parameter Value": [0.0, 0.0],
            "Key Frames": {
                "0": {"Value": [0.0, 0.0], "Variant Type": "POINTF"},
                "1000": {"Value": [0.0, 0.0], "Variant Type": "POINTF"},
            },
            "Parameter ID": "dynamicZoomCenter",
            "Parameter Value": [0.0, 0.0],
            "Variant Type": "POINTF",
        },
        {
            "Default Parameter Value": 1.0,
            "Key Frames": {
                "0": {"Value": 0.8, "Variant Type": "Double"},
                "1000": {"Value": 1.0, "Variant Type": "Double"},
            },
            "Parameter ID": "dynamicZoomScale",
            "Parameter Value": 1.0,
            "Variant Type": "Double",
            "maxValue": 100.0,
            "minValue": 0.01,
        },
    ]

    return [
        eff(1, "Transform", 2),
        eff(3, "Immersive Transform", 85),
        eff(1, "Cropping", 3),
        eff(1, "Dynamic Zoom", 59, enabled=False, parameters=dynamic_zoom_params),
        eff(1, "Composite", 1),
        eff(3, "Video Faders", 36),
    ]


def _title_html(lines, font: str, font_size: int, color: str) -> str:
    """Build the Qt rich-text HTML blob Resolve's Text+ stores its text as."""
    safe_lines = [html.escape(ln) for ln in lines] or [""]
    paragraphs = "".join(
        '<p align="center" style=" margin-top:0px; margin-bottom:0px; '
        'margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px; '
        'line-height:0; -qt-line-height-type: line-distance;">'
        f'<span style=" font-family:\'{font}\'; font-size:{font_size}pt; '
        f'color:{color};">{ln}</span></p>'
        for ln in safe_lines
    )
    return (
        '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0//EN" '
        '"http://www.w3.org/TR/REC-html40/strict.dtd">\n'
        '<html><head><meta name="qrichtext" content="1" />'
        "<style type=\"text/css\">\np, li { white-space: pre-wrap; }\n</style>"
        "</head><body style=\" font-family:'MS Shell Dlg 2'; font-size:8.25pt; "
        f'font-weight:400; font-style:normal;">{paragraphs}</body></html>'
    )


def _rich_text_generator_params(title_html: str, position) -> list:
    return [
        {
            "Display Type": 0,
            "Effect Name": "Rich Text",
            "Enabled": True,
            "Name": "Rich Text",
            "Parameters": [
                {
                    "Default Parameter Value": "Title",
                    "Parameter ID": "rich text",
                    "Parameter Value": "Title",
                    "Variant Type": "String",
                },
                {"Parameter ID": "title blob", "Title HTML": title_html},
                {
                    "Default Parameter Value": 4,
                    "Parameter ID": "anchor",
                    "Parameter Value": 4,
                    "Variant Type": "UInt",
                },
                {
                    "Default Parameter Value": [0.5, 0.5],
                    "Key Frames": {},
                    "Parameter ID": "position",
                    "Parameter Value": [position[0], position[1]],
                    "Variant Type": "POINTF",
                },
                {
                    "Default Parameter Value": 1.0,
                    "Key Frames": {},
                    "Parameter ID": "transformationZoomX",
                    "Parameter Value": 1.0,
                    "Variant Type": "Double",
                    "maxValue": 4.0,
                    "minValue": 0.25,
                },
                {
                    "Default Parameter Value": 1.0,
                    "Key Frames": {},
                    "Parameter ID": "transformationZoomY",
                    "Parameter Value": 1.0,
                    "Variant Type": "Double",
                    "maxValue": 4.0,
                    "minValue": 0.25,
                },
                {
                    "Default Parameter Value": True,
                    "Parameter ID": "transformationZoomLink",
                    "Parameter Value": True,
                    "Variant Type": "Bool",
                },
                {
                    "Default Parameter Value": 0.0,
                    "Key Frames": {},
                    "Parameter ID": "transformationRotationAngle",
                    "Parameter Value": 0.0,
                    "Variant Type": "Double",
                    "maxValue": 100000.0,
                    "minValue": -100000.0,
                },
            ],
            "Type": 24,
        },
        {
            "Display Type": 1,
            "Effect Name": "Drop Shadow",
            "Enabled": True,
            "Name": "Drop Shadow",
            "Parameters": [
                {
                    "Default Parameter Value": "#000000",
                    "Parameter ID": "shadow color",
                    "Parameter Value": "#000000",
                    "Variant Type": "Color",
                },
                {
                    "Default Parameter Value": [0.0, 0.0],
                    "Key Frames": {},
                    "Parameter ID": "shadow offset",
                    "Parameter Value": [0.0, 0.0],
                    "Variant Type": "POINTF",
                },
                {
                    "Default Parameter Value": 20,
                    "Key Frames": {},
                    "Parameter ID": "shadow",
                    "Parameter Value": 20,
                    "Variant Type": "Int",
                    "maxValue": 100.0,
                    "minValue": 1.0,
                },
                {
                    "Default Parameter Value": 75,
                    "Key Frames": {},
                    "Parameter ID": "shadow opacity",
                    "Parameter Value": 75,
                    "Variant Type": "Int",
                    "maxValue": 100.0,
                    "minValue": 0.0,
                },
            ],
            "Type": 8,
        },
        {
            "Display Type": 1,
            "Effect Name": "Stroke",
            "Enabled": True,
            "Name": "Stroke",
            "Parameters": [
                {
                    "Default Parameter Value": "#ffffff",
                    "Parameter ID": "strokeColor",
                    "Parameter Value": "#ffffff",
                    "Variant Type": "Color",
                },
                {
                    "Default Parameter Value": 1,
                    "Parameter ID": "strokeSize",
                    "Parameter Value": 1,
                    "Variant Type": "Int",
                    "maxValue": 16.0,
                    "minValue": 0.0,
                },
                {
                    "Default Parameter Value": False,
                    "Parameter ID": "strokeOutsideOnly",
                    "Parameter Value": False,
                    "Variant Type": "Bool",
                },
            ],
            "Type": 28,
        },
        {
            "Display Type": 1,
            "Effect Name": "Background",
            "Enabled": True,
            "Name": "Background",
            "Parameters": [
                {
                    "Default Parameter Value": "#000000",
                    "Parameter ID": "backgroundColor",
                    "Parameter Value": "#000000",
                    "Variant Type": "Color",
                },
                {
                    "Default Parameter Value": "#000000",
                    "Parameter ID": "backgroundOutlineColor",
                    "Parameter Value": "#000000",
                    "Variant Type": "Color",
                },
                {
                    "Default Parameter Value": 0,
                    "Key Frames": {},
                    "Parameter ID": "backgroundOutlineWidth",
                    "Parameter Value": 0,
                    "Variant Type": "Int",
                    "maxValue": 30.0,
                    "minValue": 0.0,
                },
                {
                    "Default Parameter Value": 0.9,
                    "Key Frames": {},
                    "Parameter ID": "backgroundWidth",
                    "Parameter Value": 0.9,
                    "Variant Type": "Double",
                    "maxValue": 2.0,
                    "minValue": 0.0,
                },
                {
                    "Default Parameter Value": 0.0,
                    "Key Frames": {},
                    "Parameter ID": "backgroundHeight",
                    "Parameter Value": 0.0,
                    "Variant Type": "Double",
                    "maxValue": 2.0,
                    "minValue": 0.0,
                },
                {
                    "Default Parameter Value": 0.037037037037037038,
                    "Key Frames": {},
                    "Parameter ID": "backgroundCornerRadius",
                    "Parameter Value": 0.037037037037037038,
                    "Variant Type": "Double",
                    "maxValue": 1.0,
                    "minValue": 0.0,
                },
                {
                    "Default Parameter Value": [0.0, 0.0],
                    "Key Frames": {},
                    "Parameter ID": "backgroundCenter",
                    "Parameter Value": [0.0, 0.0],
                    "Variant Type": "POINTF",
                },
                {
                    "Default Parameter Value": 50,
                    "Key Frames": {},
                    "Parameter ID": "backgroundOpacity",
                    "Parameter Value": 50,
                    "Variant Type": "Int",
                    "maxValue": 100.0,
                    "minValue": 0.0,
                },
            ],
            "Type": 27,
        },
    ]


def make_title_clip(lines, duration_frames: int, rate: float, *, font: str,
                     font_size: int, color: str, position) -> dict:
    title_html = _title_html(lines, font, font_size, color)
    name = " ".join(lines).strip() or "Text"

    return {
        "OTIO_SCHEMA": "Clip.2",
        "metadata": {"Resolve_OTIO": {}},
        "name": "Text",
        "source_range": time_range(0, duration_frames, rate),
        "effects": _clip_level_effects(),
        "markers": [],
        "enabled": True,
        "media_references": {
            "DEFAULT_MEDIA": {
                "OTIO_SCHEMA": "GeneratorReference.1",
                "metadata": {"Resolve_OTIO": {"Generator Type": "Rich"}},
                "name": "Text",
                "available_range": None,
                "available_image_bounds": None,
                "generator_kind": "Rich",
                "parameters": {
                    "Resolve_OTIO": _rich_text_generator_params(title_html, position)
                },
            }
        },
        "active_media_reference_key": "DEFAULT_MEDIA",
    }


# --------------------------------------------------------------------------
# Timeline assembly
# --------------------------------------------------------------------------

def build_timeline(cues, *, fps: float, session_start_seconds: float,
                    track_name: str, font: str, font_size: int, color: str,
                    position, add_audio_track: bool = True):
    session_start_frame = round(session_start_seconds * fps)

    children = []
    cursor = 0  # current frame position within the track

    for cue in cues:
        abs_start_frame = round(cue["start"] * fps)
        abs_end_frame = round(cue["end"] * fps)
        track_start_frame = abs_start_frame - session_start_frame
        duration_frames = abs_end_frame - abs_start_frame

        if duration_frames <= 0:
            print(f"  [!] skipping cue #{cue['index']} (start >= end)", file=sys.stderr)
            continue

        gap_frames = track_start_frame - cursor
        if gap_frames > 0:
            children.append(make_gap(gap_frames, fps))
            cursor += gap_frames
        elif gap_frames < 0:
            # overlapping cues: clamp the previous element instead of going
            # backwards, since a real timeline can't have negative gaps.
            print(f"  [!] cue #{cue['index']} overlaps the previous cue by "
                  f"{-gap_frames} frame(s); starting it immediately after "
                  f"instead of overlapping.", file=sys.stderr)

        children.append(make_title_clip(
            cue["lines"], duration_frames, fps,
            font=font, font_size=font_size, color=color, position=position,
        ))
        cursor += duration_frames

    track = {
        "OTIO_SCHEMA": "Track.1",
        "metadata": {"Resolve_OTIO": {"Locked": False}},
        "name": track_name,
        "source_range": None,
        "effects": [],
        "markers": [],
        "enabled": True,
        "children": children,
        "kind": "Video",
    }

    stack_children = [track]

    if add_audio_track:
        total_frames = int(sum(
            c["source_range"]["duration"]["value"] for c in children
        ))
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
            "source_range": None,
            "effects": [],
            "markers": [],
            "enabled": True,
            "children": [make_gap(total_frames, fps)] if total_frames > 0 else [],
            "kind": "Audio",
        }
        stack_children.append(audio_track)

    stack = {
        "OTIO_SCHEMA": "Stack.1",
        "metadata": {},
        "name": "",
        "source_range": None,
        "effects": [],
        "markers": [],
        "enabled": True,
        "children": stack_children,
    }

    timeline = {
        "OTIO_SCHEMA": "Timeline.1",
        "metadata": {"Resolve_OTIO": {"Resolve OTIO Meta Version": "1.0"}},
        "name": "",
        "global_start_time": rational_time(session_start_frame, fps),
        "tracks": stack,
    }
    return timeline


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Convert an SRT subtitle file into a DaVinci Resolve-style "
                    "Text+ title-clip OTIO timeline.")
    ap.add_argument("srt", help="Path to the input .srt file")
    ap.add_argument("otio", help="Path to write the output .otio file")
    ap.add_argument("--fps", type=float, default=60.0,
                    help="Timeline frame rate (default: 60)")
    ap.add_argument("--start-tc", default="01:00:00:00",
                    help="Timeline start timecode that your SRT times are "
                         "offset against (default: 01:00:00:00, Resolve's "
                         "usual default). Use 00:00:00:00 for a zero-based SRT.")
    ap.add_argument("--track-name", default="Video 1",
                    help="Name of the video track (default: 'Video 1')")
    ap.add_argument("--font", default="Open Sans", help="Font family for the titles")
    ap.add_argument("--font-size", type=int, default=64, help="Font size in points")
    ap.add_argument("--color", default="#ffffff", help="Text color, e.g. #ffffff")
    ap.add_argument("--position-x", type=float, default=0.5,
                    help="Horizontal text position, 0-1 (default: 0.5, centered)")
    ap.add_argument("--position-y", type=float, default=0.20370370149612428,
                    help="Vertical text position, 0-1 (default matches a "
                         "typical Resolve lower-third-ish placement)")
    ap.add_argument("--no-audio-track", action="store_true",
                    help="Don't add an empty 'Audio 1' track (Resolve adds "
                         "one by default on new timelines; included by default "
                         "for structural parity).")
    args = ap.parse_args()

    cues = parse_srt(args.srt)
    if not cues:
        print("No subtitle cues were found in the SRT file.", file=sys.stderr)
        sys.exit(1)

    session_start_seconds = timecode_to_seconds(args.start_tc, args.fps)

    timeline = build_timeline(
        cues,
        fps=args.fps,
        session_start_seconds=session_start_seconds,
        track_name=args.track_name,
        font=args.font,
        font_size=args.font_size,
        color=args.color,
        position=(args.position_x, args.position_y),
        add_audio_track=not args.no_audio_track,
    )

    with open(args.otio, "w", encoding="utf-8") as f:
        json.dump(timeline, f, indent=4)

    n_clips = sum(1 for c in timeline["tracks"]["children"][0]["children"]
                  if c["OTIO_SCHEMA"] == "Clip.2")
    print(f"Wrote {n_clips} title clip(s) from {len(cues)} SRT cue(s) -> {args.otio}")


if __name__ == "__main__":
    main()
