"""
otio_to_ffmpeg.py — Convert editplan.otio to FFmpeg-compatible outputs.

Generates:
  1. EDL.xml  — Final Cut Pro XML (xmeml format) for interoperability
  2. .concat  — FFmpeg concat demuxer file for direct rendering
  3. .bat     — Windows batch file that runs the FFmpeg render

Usage:
  python otio_to_ffmpeg.py editplan.otio [--source-dir <dir>] [--output-dir <dir>]
"""

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from xml.dom import minidom
from pathlib import Path


def frames_to_tc(frames: float, fps: float) -> str:
    s = frames / fps
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    sf = int(sec)
    ff = int(round((sec % 1) * fps))
    return f"{h:02d}:{m:02d}:{sf:02d}:{ff:02d}"


def frames_to_sec(frames: float, fps: float) -> float:
    return frames / fps


def parse_otio(otio_path: str):
    otio_dir = os.path.dirname(os.path.abspath(otio_path))

    with open(otio_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    name = data.get("name", "Timeline")
    gst = data.get("global_start_time", {})
    fps = float(gst.get("rate", 60))

    tracks = data.get("tracks", {}).get("children", [])

    segments = []
    for track in tracks:
        kind = track.get("kind", "")
        if kind not in ("Video", "Audio"):
            continue
        for clip in track.get("children", []):
            sr = clip.get("source_range", {})
            st = sr.get("start_time", {})
            dur = sr.get("duration", {})
            src_start = float(st.get("value", 0))
            src_dur = float(dur.get("value", 0))

            media = (
                clip.get("media_references", {})
                .get("DEFAULT_MEDIA", {})
                .get("target_url", "")
            )

            # resolve relative paths: try OTIO dir, then walk up parents
            if not os.path.isabs(media):
                candidate = os.path.normpath(os.path.join(otio_dir, media))
                if not os.path.exists(candidate):
                    parent = os.path.dirname(otio_dir)
                    while True:
                        candidate = os.path.normpath(os.path.join(parent, media))
                        if os.path.exists(candidate):
                            break
                        grandparent = os.path.dirname(parent)
                        if grandparent == parent:
                            candidate = os.path.normpath(os.path.join(otio_dir, media))
                            break
                        parent = grandparent
                media = candidate

            segments.append(
                {
                    "track_kind": kind,
                    "source_url": media,
                    "start_frame": src_start,
                    "duration_frames": src_dur,
                    "end_frame": src_start + src_dur,
                    "fps": fps,
                }
            )

    if not segments:
        raise ValueError("No clips found in OTIO file")

    return name, fps, segments


def prettify_xml(elem: ET.Element) -> str:
    rough = ET.tostring(elem, encoding="unicode")
    parsed = minidom.parseString(rough.encode("utf-8"))
    return parsed.toprettyxml(indent="  ")


def write_edl_xml(segments, timeline_name, fps, output_path):
    """
    Write EDL.xml in xmeml (Final Cut Pro XML) format.
    One video track, one audio track, no transitions.
    """
    root = ET.Element("xmeml", version="4")

    seq = ET.SubElement(root, "sequence")
    ET.SubElement(seq, "name").text = timeline_name
    duration_frames = sum(s["duration_frames"] for s in segments if s["track_kind"] == "Video")

    dur_elem = ET.SubElement(seq, "duration")
    dur_elem.text = str(int(duration_frames))

    rate = ET.SubElement(seq, "rate")
    ET.SubElement(rate, "timebase").text = str(int(fps))
    ET.SubElement(rate, "ntsc").text = "FALSE"

    media_elem = ET.SubElement(seq, "media")

    # --- Video track ---
    video_elem = ET.SubElement(media_elem, "video")
    ET.SubElement(video_elem, "track")

    vsegs = [s for s in segments if s["track_kind"] == "Video"]

    # We'll write a single track with clipitems; each is a masterclip reference
    track_elem = video_elem.find("track")

    track_timeline_pos = 0  # frames, accumulated
    for i, seg in enumerate(vsegs):
        clipitem = ET.SubElement(track_elem, "clipitem")
        clipitem.set("id", f"clipitem-{i+1}")

        ET.SubElement(clipitem, "masterclipid").text = f"masterclip-{i+1}"
        ET.SubElement(clipitem, "name").text = os.path.basename(seg["source_url"])
        ET.SubElement(clipitem, "enabled").text = "TRUE"
        ET.SubElement(clipitem, "duration").text = str(int(seg["duration_frames"]))

        # start in timeline
        ET.SubElement(clipitem, "start").text = str(int(track_timeline_pos))
        ET.SubElement(clipitem, "end").text = str(int(track_timeline_pos + seg["duration_frames"]))

        # in/out in source
        ET.SubElement(clipitem, "in").text = str(int(seg["start_frame"]))
        ET.SubElement(clipitem, "out").text = str(int(seg["end_frame"]))

        file_elem = ET.SubElement(clipitem, "file")
        file_elem.set("id", f"file-{i+1}")
        ET.SubElement(file_elem, "name").text = os.path.basename(seg["source_url"])

        pathurl = ET.SubElement(file_elem, "pathurl")
        pathurl.text = f"file://localhost/{seg['source_url'].replace(os.sep, '/')}"

        rate_file = ET.SubElement(file_elem, "rate")
        ET.SubElement(rate_file, "timebase").text = str(int(fps))
        ET.SubElement(rate_file, "ntsc").text = "FALSE"

        # Sourcetrack
        sourcetrack = ET.SubElement(clipitem, "sourcetrack")
        ET.SubElement(sourcetrack, "mediatype").text = "video"
        ET.SubElement(sourcetrack, "trackindex").text = "1"

        # Link group for sync with audio
        link = ET.SubElement(clipitem, "link")
        ET.SubElement(link, "linkclipref").text = f"clipitem-{i+1}"
        ET.SubElement(link, "mediatype").text = "video"
        ET.SubElement(link, "trackindex").text = "1"
        ET.SubElement(link, "clipindex").text = "1"

        track_timeline_pos += seg["duration_frames"]

    # --- Audio track ---
    audio_elem = ET.SubElement(media_elem, "audio")
    audio_track = ET.SubElement(audio_elem, "track")
    ET.SubElement(audio_track, "trackindex").text = "2"

    asegs = [s for s in segments if s["track_kind"] == "Audio"]
    track_timeline_pos = 0
    for i, seg in enumerate(asegs):
        clipitem = ET.SubElement(audio_track, "clipitem")
        clipitem.set("id", f"aclips-{i+1}")
        ET.SubElement(clipitem, "masterclipid").text = f"amasterclip-{i+1}"
        ET.SubElement(clipitem, "name").text = os.path.basename(seg["source_url"])
        ET.SubElement(clipitem, "enabled").text = "TRUE"
        ET.SubElement(clipitem, "duration").text = str(int(seg["duration_frames"]))
        ET.SubElement(clipitem, "start").text = str(int(track_timeline_pos))
        ET.SubElement(clipitem, "end").text = str(int(track_timeline_pos + seg["duration_frames"]))
        ET.SubElement(clipitem, "in").text = str(int(seg["start_frame"]))
        ET.SubElement(clipitem, "out").text = str(int(seg["end_frame"]))

        file_elem = ET.SubElement(clipitem, "file")
        file_elem.set("id", f"afile-{i+1}")
        ET.SubElement(file_elem, "name").text = os.path.basename(seg["source_url"])

        pathurl = ET.SubElement(file_elem, "pathurl")
        pathurl.text = f"file://localhost/{seg['source_url'].replace(os.sep, '/')}"

        rate_file = ET.SubElement(file_elem, "rate")
        ET.SubElement(rate_file, "timebase").text = str(int(fps))
        ET.SubElement(rate_file, "ntsc").text = "FALSE"

        sourcetrack = ET.SubElement(clipitem, "sourcetrack")
        ET.SubElement(sourcetrack, "mediatype").text = "audio"
        ET.SubElement(sourcetrack, "trackindex").text = "1"

        link = ET.SubElement(clipitem, "link")
        ET.SubElement(link, "linkclipref").text = f"aclips-{i+1}"
        ET.SubElement(link, "mediatype").text = "audio"
        ET.SubElement(link, "trackindex").text = "2"
        ET.SubElement(link, "clipindex").text = "1"

        track_timeline_pos += seg["duration_frames"]

    xml_str = prettify_xml(root)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xml_str)
    print(f"  EDL.xml  -> {output_path}")


def write_concat(segments, fps, output_path):
    """Write FFmpeg concat demuxer file."""
    vsegs = [s for s in segments if s["track_kind"] == "Video"]
    lines = ["ffconcat version 1.0\n"]
    for seg in vsegs:
        src = seg["source_url"]
        in_sec = frames_to_sec(seg["start_frame"], fps)
        out_sec = frames_to_sec(seg["end_frame"], fps)
        lines.append(f"file '{src}'")
        lines.append(f"inpoint {in_sec:.6f}")
        lines.append(f"outpoint {out_sec:.6f}")

    content = "\n".join(lines) + "\n"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  .concat  -> {output_path}")


def write_render_bat(concat_path, output_mp4, segments, fps, bat_path):
    """Write a Windows batch file to run FFmpeg."""
    total_frames = sum(s["duration_frames"] for s in segments if s["track_kind"] == "Video")
    total_sec = total_frames / fps
    total_min = total_sec / 60
    print(f"  Total: {int(total_frames)} frames @ {fps}fps = {total_sec:.1f}s ({total_min:.1f} min)")

    lines = [
        "@echo off",
        "",
        f"REM Render {Path(output_mp4).name} — {total_sec:.1f}s ({total_min:.1f} min) @ {fps}fps",
        f"REM Generated from {Path(concat_path).name}",
        "",
        "setlocal enabledelayedexpansion",
        "",
        'echo === Rendering with FFmpeg concat demuxer ===',
        "",
        f"ffmpeg -y -safe 0 -f concat -i \"{concat_path}\" ^",
        f"       -c:v libx264 -preset medium -crf 18 ^",
        f"       -c:a aac -b:a 192k ^",
        f"       -pix_fmt yuv420p ^",
        f"       \"{output_mp4}\"",
        "",
        'if %ERRORLEVEL% equ 0 (',
        f'    echo === Done: {output_mp4} ===',
        ') else (',
        '    echo === FFmpeg error! ===',
        ')',
        "",
        "endlocal",
    ]
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  .bat     -> {bat_path}")


def print_ffmpeg_command(concat_path, output_mp4):
    print(
        f"\nFFmpeg command to render:\n"
        f"  ffmpeg -y -safe 0 -f concat -i \"{concat_path}\" "
        f"-c:v libx264 -preset medium -crf 18 "
        f"-c:a aac -b:a 192k "
        f"-pix_fmt yuv420p \"{output_mp4}\""
    )


def main():
    parser = argparse.ArgumentParser(
        description="Convert editplan.otio to EDL.xml + FFmpeg concat for rendering."
    )
    parser.add_argument("otio", help="Path to the .otio file (e.g. editplan.otio)")
    parser.add_argument(
        "--output-dir",
        "-o",
        help="Output directory (default: same as .otio file)",
        default=None,
    )
    parser.add_argument(
        "--source-dir",
        "-s",
        help="Source media directory (prefix for source_urls, default: current dir)",
        default="",
    )
    parser.add_argument(
        "--output-mp4",
        help="Output MP4 filename (default: <timeline_name>.mp4)",
        default=None,
    )
    parser.add_argument(
        "--no-bat",
        action="store_true",
        help="Skip generating .bat file (useful when bat is the pipeline)",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.otio):
        print(f"Error: file not found: {args.otio}", file=sys.stderr)
        sys.exit(1)

    print(f"Parsing: {args.otio}")
    timeline_name, fps, segments = parse_otio(args.otio)
    print(f"  Timeline: {timeline_name}")
    print(f"  FPS: {fps}")
    print(f"  Clips: {len([s for s in segments if s['track_kind'] == 'Video'])} video")

    out_dir = args.output_dir or os.path.dirname(os.path.abspath(args.otio))
    os.makedirs(out_dir, exist_ok=True)

    base = Path(args.otio).stem  # e.g. "editplan"

    edl_xml_path = os.path.join(out_dir, f"{base}_EDL.xml")
    concat_path = os.path.join(out_dir, f"{base}.concat")
    bat_path = os.path.join(out_dir, f"{base}_render.bat")

    safe_name = re.sub(r"[^\w\- ]", "", timeline_name).strip().replace(" ", "_")
    output_mp4 = args.output_mp4 or os.path.join(out_dir, f"{safe_name}.mp4")

    print()
    write_edl_xml(segments, timeline_name, fps, edl_xml_path)

    print()
    write_concat(segments, fps, concat_path)

    if not args.no_bat:
        print()
        write_render_bat(concat_path, output_mp4, segments, fps, bat_path)

    print()
    print_ffmpeg_command(concat_path, output_mp4)

    print(f"\nRun the batch file or ffmpeg command above to render.")


if __name__ == "__main__":
    main()
