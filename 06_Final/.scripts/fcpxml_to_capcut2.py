#!/usr/bin/env python3
"""
fcpxml_to_capcut2 — convert an FCPXML timeline into a CapCut (Windows) draft folder.

This is a rewrite of fcpxml_to_capcut.py. The old script assumed ONE source file
and ONE video track: it took the media path from CONFIG["MEDIA_FILE"] (or from
the first <asset>) and stamped that single path onto every segment, so a timeline
that referenced several files came out with every clip pointing at the first one.
It also flattened every fcpxml lane onto a single CapCut track.

What this version does instead
------------------------------
  * one CapCut material per DISTINCT source file, resolved per clip from its
    <asset-clip ref="...">, so multi-footage timelines survive the round trip
  * fcpxml lanes -> CapCut tracks:
        lane 1 (or 0) -> the main video track
        lane 2,3,...  -> overlay / PIP video tracks, stacked bottom-to-top
        lane -1,-2,... -> audio tracks
    clips that overlap inside one lane are spilled onto extra tracks instead of
    silently colliding
  * still images (.jpg/.png/...) become CapCut `photo` materials, not videos,
    with a 3-hour material duration so they can be stretched on the timeline
  * audio-only assets become CapCut `music` materials on real audio tracks
  * every file is probed with ffprobe for its true width/height/duration, so
    overlays are not stretched to 1920x1080 and source in-points never exceed
    the material length (falls back to the fcpxml numbers if ffprobe is absent)
  * draft_meta_info.json / draft_virtual_store.json / key_value.json / the agent
    path record all enumerate EVERY imported file, not just the first
  * a --verify pass re-reads what was written and checks the invariants CapCut
    relies on (dangling material refs, overlapping segments on one track,
    in-points past the end of the source, missing files, ...)

Known limitation (fcpxml, not this script): OpenChatCut's exporter does not write
<adjust-transform>, so per-clip position/scale/rotation is not in the .fcpxml at
all. Overlays therefore land centred at CapCut's default fit. If a future export
does emit <adjust-transform>, this script already reads it; until then use
CONFIG["LANE_TRANSFORM"] to give a whole lane a default scale/offset.

Usage
-----
    python fcpxml_to_capcut2.py                                  # use CONFIG below
    python fcpxml_to_capcut2.py path\\to\\timeline.fcpxml          # override input
    python fcpxml_to_capcut2.py in.fcpxml --name MyProject --force
    python fcpxml_to_capcut2.py in.fcpxml --dry-run              # parse + report only

Then open CapCut; the project appears under "Projects".
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from collections import defaultdict
from fractions import Fraction

# --------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------

CONFIG = {
    # Input: the .fcpxml to convert (a bare command-line argument overrides it).
    "FCPXML_IN": r"E:\AdamsRoadTrips\ScrapMechanic\Part1\01_RAW\SM_1_01-resolveV4.fcpxml",

    # Output: the CapCut project FOLDER. Leave "" to auto-name it after the
    # fcpxml's <project name="..."> under CAPCUT_DRAFTS_ROOT.
    "OUTPUT_DIR": "",

    # CapCut's drafts root (used only when OUTPUT_DIR is empty).
    "CAPCUT_DRAFTS_ROOT": r"C:\Users\Adam\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft",

    # Path rewriting, applied to every resolved media path (case-insensitive
    # prefix match). Use it when the media has moved since the export, e.g.
    #   {"C:/Agents/OpenChatCut/.usermedia": "E:/Media/usermedia"}
    "MEDIA_MAP": {},

    # Per-lane default transform for clips that carry no <adjust-transform>.
    # Keys are fcpxml lane numbers. scale is a multiplier on CapCut's default
    # fit; x/y are in CapCut units where 1.0 == half the canvas.
    #   2: {"scale": 0.45, "x": 0.5, "y": 0.5}   # lane 2 at 45%, upper right
    "LANE_TRANSFORM": {},

    # Per-lane volume (1.0 = unchanged). Keys are lane numbers.
    "LANE_VOLUME": {},

    # Probe media with ffprobe for true width/height/duration. Strongly
    # recommended; without it images get the sequence's dimensions.
    "PROBE_MEDIA": True,

    # CapCut machine identifiers (analytics only; copied from a real project).
    "PLATFORM": {
        "os": "windows",
        "os_version": "10.0.19045",
        "app_id": 359289,
        "app_version": "9.1.0",
        "app_source": "cc",
        "device_id": "3e0526f18de4d0dd86720d70e9099462",
        "hard_disk_id": "f8eada09ec17bf26b71400c5ed35427e",
        "mac_address": "d9989fe3ccfd3ddcaf25e3126aa6d012,eb1cd2e50cae17e24a035cfa4385dbfc",
    },
}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff", ".heic", ".avif"}

# CapCut's material duration for stills: 3 hours, so a photo can be stretched
# to any timeline length.
PHOTO_MATERIAL_US = 10_800_000_000

# Segment render_index bases. The main video track keeps 0 (verified against a
# real project); every overlay track above it gets its own band, and each
# segment inside the track takes base+ordinal (the scheme CapCut uses for text).
OVERLAY_RENDER_BASE = 10000
OVERLAY_RENDER_STRIDE = 1000


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def new_id() -> str:
    """Timeline-object id, upper-cased like CapCut writes them."""
    return str(uuid.uuid4()).upper()


def new_local_id() -> str:
    """Media-pool id. CapCut keeps these lower-case."""
    return str(uuid.uuid4())


def json_dump(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json_dump(obj))


def copy_file(src: str, dst: str) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def file_url_to_path(src: str) -> str:
    """'file:///C:/a/b%20c.mp4' -> 'C:/a/b c.mp4'. Non-file URLs pass through."""
    from urllib.parse import unquote, urlparse

    if not src:
        return ""
    if not src.lower().startswith("file:"):
        return src.replace("\\", "/")
    parsed = urlparse(src)
    path = unquote(parsed.path or "")
    # file://host/... with a drive letter, or the usual file:///C:/...
    if parsed.netloc and not path.startswith("/"):
        path = f"/{parsed.netloc}{path}"
    elif parsed.netloc:
        path = f"/{parsed.netloc}{path}"
    if len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]  # /C:/x -> C:/x
    return path.replace("\\", "/")


def apply_media_map(path: str, media_map: dict) -> str:
    for old, new in (media_map or {}).items():
        o = old.replace("\\", "/").rstrip("/")
        if path.lower().startswith(o.lower()):
            return new.replace("\\", "/").rstrip("/") + path[len(o):]
    return path


# --------------------------------------------------------------------------
# FCPXML parsing
# --------------------------------------------------------------------------


class Timebase:
    """Frame <-> microsecond conversion driven by the sequence's frameDuration."""

    def __init__(self, frame_duration: str = "1/30s"):
        fd = Fraction(frame_duration.rstrip("s") or "1/30")
        if fd <= 0:
            fd = Fraction(1, 30)
        self.frame_duration = fd            # seconds per frame
        self.fps = 1 / fd                   # frames per second (Fraction)

    @property
    def fps_float(self) -> float:
        return float(self.fps)

    def parse_time(self, text: str | None) -> int:
        """fcpxml time ('6548/30s', '3s', '0s') -> whole frames."""
        if not text:
            return 0
        t = text.strip().rstrip("s")
        if not t:
            return 0
        try:
            secs = Fraction(t)
        except (ValueError, ZeroDivisionError):
            secs = Fraction(0)
        return int(round(secs / self.frame_duration))

    def frames_to_us(self, frames: int) -> int:
        """Frames -> microseconds, floored (matches how CapCut stores them)."""
        return int(frames * self.frame_duration.numerator * 1_000_000
                   // self.frame_duration.denominator)


class Asset:
    def __init__(self, aid, name, path, duration_frames, has_video, has_audio):
        self.id = aid
        self.name = name
        self.path = path                    # forward-slash absolute path
        self.duration_frames = duration_frames
        self.has_video = has_video
        self.has_audio = has_audio
        # Filled in by probe_assets()
        self.kind = "video"                 # video | photo | audio
        self.width = 0
        self.height = 0
        self.duration_us = 0
        self.file_size = 0
        self.local_material_id = new_local_id()
        self.exists = False


class Clip:
    def __init__(self, asset, lane, offset_frames, duration_frames, start_frames,
                 name, transform=None, volume=None):
        self.asset = asset
        self.lane = lane
        self.offset_frames = offset_frames
        self.duration_frames = duration_frames
        self.start_frames = start_frames
        self.name = name
        self.transform = transform or {}
        self.volume = volume

    @property
    def end_frames(self) -> int:
        return self.offset_frames + self.duration_frames


def _parse_transform(node) -> dict:
    """<adjust-transform position="x y" scale="sx sy" rotation="deg"/> -> dict.

    fcpxml position is in per-mille of the frame height; CapCut's transform unit
    is 'half the canvas', so x_capcut = x_fcp/100 * (h/w) ... close enough for a
    default: we normalise to fractions of half-width/half-height.
    """
    adj = node.find("adjust-transform")
    if adj is None:
        return {}
    out = {}
    pos = (adj.get("position") or "").split()
    if len(pos) == 2:
        try:
            out["x"] = float(pos[0]) / 50.0
            out["y"] = -float(pos[1]) / 50.0   # fcpxml +y is up, CapCut +y is down
        except ValueError:
            pass
    sc = (adj.get("scale") or "").split()
    if len(sc) >= 1:
        try:
            out["scale_x"] = float(sc[0])
            out["scale_y"] = float(sc[1]) if len(sc) > 1 else float(sc[0])
        except ValueError:
            pass
    try:
        if adj.get("rotation"):
            out["rotation"] = float(adj.get("rotation"))
    except ValueError:
        pass
    return out


def _parse_volume(node):
    adj = node.find("adjust-volume")
    if adj is None:
        return None
    raw = adj.get("amount")
    if not raw:
        return None
    raw = raw.strip()
    try:
        if raw.endswith("dB"):
            return float(10 ** (float(raw[:-2]) / 20.0))
        return float(raw)
    except ValueError:
        return None


CLIP_TAGS = ("asset-clip", "clip", "video", "audio", "ref-clip", "sync-clip", "mc-clip")


def parse_fcpxml(path: str, media_map: dict, warnings: list) -> dict:
    root = ET.parse(path).getroot()

    fmt = root.find(".//resources/format")
    if fmt is None:
        fmt = root.find(".//format")
    tb = Timebase(fmt.get("frameDuration", "1/30s") if fmt is not None else "1/30s")
    width = int(fmt.get("width", 1920)) if fmt is not None else 1920
    height = int(fmt.get("height", 1080)) if fmt is not None else 1080

    assets: dict[str, Asset] = {}
    for a in root.findall(".//resources/asset"):
        p = apply_media_map(file_url_to_path(a.get("src", "")), media_map)
        assets[a.get("id")] = Asset(
            aid=a.get("id"),
            name=a.get("name", "") or os.path.basename(p),
            path=p,
            duration_frames=tb.parse_time(a.get("duration")),
            has_video=a.get("hasVideo", "0") == "1",
            has_audio=a.get("hasAudio", "0") == "1",
        )

    proj = root.find(".//project")
    project_name = (proj.get("name") if proj is not None else "") or ""

    seq = root.find(".//sequence")
    seq_duration_frames = tb.parse_time(seq.get("duration")) if seq is not None else 0

    clips: list[Clip] = []

    def walk(node, parent_abs_offset: int, parent_start: int):
        """Collect clips. A connected clip's offset is in its parent's local
        timeline, which begins at the parent's `start`, so
        absolute = parent_abs + (offset - parent_start)."""
        for child in list(node):
            tag = child.tag
            if tag not in CLIP_TAGS and tag != "gap":
                continue
            offset = tb.parse_time(child.get("offset"))
            duration = tb.parse_time(child.get("duration"))
            start = tb.parse_time(child.get("start"))
            lane_raw = child.get("lane")
            abs_offset = parent_abs_offset + (offset - parent_start)

            if tag == "gap":
                name = child.get("name", "")
                if name.startswith("MG:"):
                    warnings.append(
                        f"skipped unrendered motion graphic {name!r} at "
                        f"{abs_offset / tb.fps_float:.2f}s "
                        "(export_motion_graphic_prores first, then re-export)")
                walk(child, abs_offset, start)
                continue

            ref = child.get("ref")
            asset = assets.get(ref) if ref else None
            if asset is None:
                warnings.append(f"skipped <{tag}> with unknown ref {ref!r}")
                walk(child, abs_offset, start)
                continue
            if duration <= 0:
                warnings.append(f"skipped zero-length clip {child.get('name', '')!r}")
                continue

            lane = int(lane_raw) if lane_raw not in (None, "") else 1
            clips.append(Clip(
                asset=asset,
                lane=lane,
                offset_frames=abs_offset,
                duration_frames=duration,
                start_frames=start,
                name=child.get("name", "") or asset.name,
                transform=_parse_transform(child),
                volume=_parse_volume(child),
            ))
            # nested lane children (a clip anchored to another clip)
            walk(child, abs_offset, start)

    spine = root.find(".//spine")
    if spine is not None:
        walk(spine, 0, 0)

    return {
        "timebase": tb,
        "width": width,
        "height": height,
        "project_name": project_name,
        "assets": assets,
        "clips": clips,
        "sequence_duration_frames": seq_duration_frames,
    }


# --------------------------------------------------------------------------
# Media probing
# --------------------------------------------------------------------------


def ffprobe(path: str) -> dict | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode != 0:
            return None
        return json.loads(out.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def probe_assets(tl: dict, probe: bool, warnings: list) -> None:
    tb: Timebase = tl["timebase"]
    for asset in tl["assets"].values():
        ext = os.path.splitext(asset.path)[1].lower()
        asset.exists = os.path.isfile(asset.path)
        if asset.exists:
            try:
                asset.file_size = os.path.getsize(asset.path)
            except OSError:
                pass
        else:
            warnings.append(f"media file not found (CapCut will show it offline): {asset.path}")

        # Classify: images first (extension is the only reliable signal, an
        # image reports hasVideo=1 in fcpxml just like a movie).
        if ext in IMAGE_EXTS:
            asset.kind = "photo"
        elif asset.has_video:
            asset.kind = "video"
        else:
            asset.kind = "audio"

        # Defaults straight from the fcpxml, overwritten by ffprobe below.
        asset.width, asset.height = tl["width"], tl["height"]
        asset.duration_us = tb.frames_to_us(asset.duration_frames)

        if not (probe and asset.exists):
            continue
        info = ffprobe(asset.path)
        if not info:
            warnings.append(f"ffprobe failed, using fcpxml metadata for {asset.path}")
            continue

        vstream = next((s for s in info.get("streams", [])
                        if s.get("codec_type") == "video"), None)
        astream = next((s for s in info.get("streams", [])
                        if s.get("codec_type") == "audio"), None)
        if vstream:
            asset.width = int(vstream.get("width") or asset.width)
            asset.height = int(vstream.get("height") or asset.height)
            # A still reports one video stream with no real duration.
            if asset.kind != "photo" and not astream and ext in IMAGE_EXTS:
                asset.kind = "photo"
        if not vstream and asset.kind != "audio":
            asset.kind = "audio"
        asset.has_audio = asset.has_audio and astream is not None

        if asset.kind != "photo":
            try:
                secs = float(info.get("format", {}).get("duration") or 0)
            except (TypeError, ValueError):
                secs = 0.0
            probed_us = int(secs * 1_000_000)
            # Keep whichever is longer: a source in-point near the tail must
            # stay inside the material or CapCut clamps the clip.
            asset.duration_us = max(asset.duration_us, probed_us)


# --------------------------------------------------------------------------
# Track layout
# --------------------------------------------------------------------------


def split_overlaps(clips: list[Clip], warnings: list, lane: int) -> list[list[Clip]]:
    """Greedily pack clips into as few non-overlapping rows as possible."""
    rows: list[list[Clip]] = []
    for clip in sorted(clips, key=lambda c: (c.offset_frames, c.duration_frames)):
        for row in rows:
            if row[-1].end_frames <= clip.offset_frames:
                row.append(clip)
                break
        else:
            rows.append([clip])
    if len(rows) > 1:
        warnings.append(
            f"lane {lane} had overlapping clips; spilled onto {len(rows)} CapCut tracks")
    return rows


def build_tracks(clips: list[Clip], warnings: list) -> list[dict]:
    """fcpxml lanes -> ordered CapCut track descriptors (bottom video first)."""
    by_lane: dict[int, list[Clip]] = defaultdict(list)
    for c in clips:
        by_lane[c.lane].append(c)

    video_lanes = sorted(l for l in by_lane if l >= 0)
    audio_lanes = sorted((l for l in by_lane if l < 0), reverse=True)  # -1, -2, ...

    tracks: list[dict] = []
    for lane in video_lanes:
        for row in split_overlaps(by_lane[lane], warnings, lane):
            kinds = {c.asset.kind for c in row}
            tracks.append({
                "kind": "audio" if kinds == {"audio"} else "video",
                "lane": lane,
                "clips": row,
            })
    for lane in audio_lanes:
        for row in split_overlaps(by_lane[lane], warnings, lane):
            tracks.append({"kind": "audio", "lane": lane, "clips": row})

    # Stack index only counts video tracks (audio tracks live in their own area).
    stack = 0
    for t in tracks:
        if t["kind"] == "video":
            t["stack"] = stack
            stack += 1
        else:
            t["stack"] = 0
    return tracks


# --------------------------------------------------------------------------
# Material factories (schemas verified against a real CapCut 9.1 project)
# --------------------------------------------------------------------------


def make_video_material(mat_id, asset, is_photo: bool) -> dict:
    return {
        "id": mat_id,
        "unique_id": "",
        "type": "photo" if is_photo else "video",
        "duration": PHOTO_MATERIAL_US if is_photo else asset.duration_us,
        "path": asset.path,
        "media_path": "",
        "local_id": "",
        "has_audio": bool(asset.has_audio) and not is_photo,
        "reverse_path": "",
        "intensifies_path": "",
        "reverse_intensifies_path": "",
        "intensifies_audio_path": "",
        "cartoon_path": "",
        "width": asset.width,
        "height": asset.height,
        "category_id": "",
        "category_name": "local",
        "material_id": "",
        "material_name": os.path.basename(asset.path) or asset.name,
        "material_url": "",
        "crop": {
            "upper_left_x": 0.0, "upper_left_y": 0.0,
            "upper_right_x": 1.0, "upper_right_y": 0.0,
            "lower_left_x": 0.0, "lower_left_y": 1.0,
            "lower_right_x": 1.0, "lower_right_y": 1.0,
        },
        "crop_ratio": "free",
        "audio_fade": None,
        "crop_scale": 1.0,
        "extra_type_option": 0,
        "stable": {"stable_level": 0, "matrix_path": "", "time_range": {"start": 0, "duration": 0}},
        "matting": {
            "flag": 0, "path": "", "interactiveTime": [],
            "has_use_quick_brush": False, "strokes": [], "has_use_quick_eraser": False,
            "expansion": 0, "feather": 0, "reverse": False, "custom_matting_id": "",
            "enable_matting_stroke": False, "is_clould": False, "mask_video_path": "",
            "cloud_product_fps": 0.0,
        },
        "source": 0,
        "source_platform": 0,
        "formula_id": "",
        "check_flag": 62978047,
        "video_algorithm": {
            "algorithms": [], "time_range": None, "path": "",
            "gameplay_configs": [], "ai_in_painting_config": [],
            "complement_frame_config": None, "motion_blur_config": None,
            "deflicker": None, "noise_reduction": None, "quality_enhance": None,
            "super_resolution": None, "ai_background_configs": [],
            "smart_complement_frame": None, "aigc_generate": None,
            "aigc_generate_list": [], "mouth_shape_driver": None,
            "ai_expression_driven": None, "ai_motion_driven": None,
            "image_interpretation": None,
            "story_video_modify_video_config": {
                "task_id": "", "is_overwrite_last_video": False,
                "tracker_task_id": "", "generate_id": "", "generate_card_id": "",
            },
            "skip_algorithm_index": [],
        },
        "is_unified_beauty_mode": False,
        "is_set_beauty_mode": False,
        "object_locked": None,
        "smart_motion": None,
        "multi_camera_info": None,
        "freeze": None,
        "picture_from": "none",
        "picture_set_category_id": "",
        "picture_set_category_name": "",
        "team_id": "",
        "local_material_id": asset.local_material_id,
        "origin_material_id": "",
        "request_id": "",
        "has_sound_separated": False,
        "is_text_edit_overdub": False,
        "is_ai_generate_content": False,
        "aigc_type": "none",
        "is_copyright": False,
        "aigc_history_id": "",
        "aigc_item_id": "",
        "local_material_from": "",
        "smart_match_info": None,
        "beauty_face_preset_infos": [],
        "beauty_body_preset_id": "",
        "beauty_face_auto_preset": {"preset_id": "", "name": "", "rate_map": "", "scene": ""},
        "beauty_face_auto_preset_infos": [],
        "beauty_body_auto_preset": None,
        "live_photo_timestamp": -1,
        "live_photo_cover_path": "",
        "content_feature_info": None,
        "corner_pin": None,
        "surface_trackings": [],
        "video_mask_stroke": {
            "resource_id": "", "path": "", "type": "", "color": "", "size": 0.0,
            "alpha": 0.0, "distance": 0.0, "texture": 0.0,
            "horizontal_shift": 0.0, "vertical_shift": 0.0,
        },
        "video_mask_shadow": {
            "resource_id": "", "path": "", "color": "", "alpha": 0.0,
            "blur": 0.0, "distance": 0.0, "angle": 0.0,
        },
        "pre_applied_vip_materials": [],
        "workflow_node_id": "",
    }


def make_audio_material(mat_id, asset) -> dict:
    return {
        "id": mat_id,
        "type": "extract_music",
        "name": os.path.basename(asset.path) or asset.name,
        "path": asset.path,
        "duration": asset.duration_us,
        "app_id": 0,
        "category_id": "",
        "category_name": "local",
        "check_flag": 1,
        "copyright_limit_type": "none",
        "effect_id": "",
        "formula_id": "",
        "intensifies_path": "",
        "is_ai_clone_tone": False,
        "is_text_edit_overdub": False,
        "is_ugc": False,
        "local_material_id": asset.local_material_id,
        "music_id": "",
        "query": "",
        "request_id": "",
        "resource_id": "",
        "search_id": "",
        "source_from": "",
        "source_platform": 0,
        "team_id": "",
        "text_id": "",
        "tone_category_id": "",
        "tone_category_name": "",
        "tone_effect_id": "",
        "tone_effect_name": "",
        "tone_platform": "",
        "tone_second_category_id": "",
        "tone_second_category_name": "",
        "tone_speaker": "",
        "tone_type": "",
        "video_id": "",
        "wave_points": [],
    }


def make_speed(mid):
    return {"id": mid, "type": "speed", "mode": 0, "speed": 1.0, "curve_speed": None}


def make_placeholder_info(mid):
    return {"id": mid, "type": "placeholder_info", "meta_type": "none",
            "res_path": "", "res_text": "", "error_path": "", "error_text": ""}


def make_canvas(mid):
    return {"id": mid, "type": "canvas_color", "color": "", "blur": 0.0,
            "image": "", "album_image": "", "image_id": "", "image_name": "",
            "source_platform": 0, "team_id": ""}


def make_sound_channel_mapping(mid):
    return {"id": mid, "type": "", "audio_channel_mapping": 0, "is_config_open": False}


def make_material_color(mid):
    return {"id": mid, "is_color_clip": False, "is_gradient": False, "solid_color": "",
            "gradient_colors": [], "gradient_percents": [], "gradient_angle": 90.0,
            "width": 0.0, "height": 0.0}


def make_vocal_separation(mid):
    return {"id": mid, "type": "vocal_separation", "choice": 0, "removed_sounds": [],
            "time_range": None, "production_path": "", "final_algorithm": "", "enter_from": ""}


def make_beats(mid):
    return {
        "id": mid, "type": "beats", "mode": 404, "gear": 404, "gear_count": 0,
        "enable_ai_beats": False, "user_beats": [], "user_delete_ai_beats": None,
        "ai_beats": {"beat_speed_infos": [], "beats_path": "", "beats_url": "",
                     "melody_path": "", "melody_percents": [0.0], "melody_url": ""},
    }


def make_materials_dict() -> dict:
    keys = [
        "flowers", "videos", "tail_leaders", "audios", "images", "texts",
        "effects", "stickers", "canvases", "transitions", "audio_effects",
        "audio_fades", "beats", "material_animations", "placeholders",
        "placeholder_infos", "speeds", "common_mask", "chromas",
        "text_templates", "realtime_denoises", "audio_pannings",
        "audio_pitch_shifts", "video_trackings", "hsl", "drafts",
        "color_curves", "hsl_curves", "primary_color_wheels",
        "log_color_wheels", "video_effects", "ai_text_effects",
        "audio_balances", "handwrites", "manual_deformations",
        "manual_beautys", "plugin_effects", "sound_channel_mappings",
        "green_screens", "shapes", "material_colors", "digital_humans",
        "digital_human_model_dressing", "smart_crops", "ai_translates",
        "audio_track_indexes", "loudnesses", "vocal_beautifys",
        "vocal_separations", "smart_relights", "time_marks",
        "multi_language_refs", "video_shadows", "video_strokes",
        "video_radius",
    ]
    return {k: [] for k in keys}


# --------------------------------------------------------------------------
# Segment factories
# --------------------------------------------------------------------------


def make_visual_segment(seg_id, mat_id, extra_refs, src_start, src_dur,
                        tgt_start, tgt_dur, render_index, track_render_index,
                        transform, volume) -> dict:
    scale_x = transform.get("scale_x", 1.0)
    scale_y = transform.get("scale_y", scale_x)
    return {
        "id": seg_id,
        "source_timerange": {"start": src_start, "duration": src_dur},
        "target_timerange": {"start": tgt_start, "duration": tgt_dur},
        "render_timerange": {"start": 0, "duration": 0},
        "desc": "",
        "state": 0,
        "speed": 1.0,
        "is_loop": False,
        "is_tone_modify": False,
        "reverse": False,
        "intensifies_audio": False,
        "cartoon": False,
        "volume": volume,
        "last_nonzero_volume": volume if volume > 0 else 1.0,
        "clip": {
            "scale": {"x": scale_x, "y": scale_y},
            "rotation": transform.get("rotation", 0.0),
            "transform": {"x": transform.get("x", 0.0), "y": transform.get("y", 0.0)},
            "flip": {"vertical": False, "horizontal": False},
            "alpha": transform.get("alpha", 1.0),
        },
        "uniform_scale": {"on": abs(scale_x - scale_y) < 1e-9, "value": scale_x},
        "material_id": mat_id,
        "extra_material_refs": extra_refs,
        "render_index": render_index,
        "keyframe_refs": [],
        "enable_lut": True,
        "enable_adjust": True,
        "enable_hsl": False,
        "visible": True,
        "group_id": "",
        "enable_color_curves": True,
        "enable_hsl_curves": True,
        "track_render_index": track_render_index,
        "hdr_settings": {"mode": 1, "intensity": 1.0, "nits": 1000},
        "enable_color_wheels": True,
        "track_attribute": 0,
        "is_placeholder": False,
        "template_id": "",
        "enable_smart_color_adjust": False,
        "template_scene": "default",
        "common_keyframes": [],
        "caption_info": None,
        "responsive_layout": {
            "enable": False, "target_follow": "", "size_layout": 0,
            "horizontal_pos_layout": 0, "vertical_pos_layout": 0,
        },
        "enable_color_match_adjust": False,
        "enable_color_correct_adjust": False,
        "enable_adjust_mask": False,
        "raw_segment_id": "",
        "lyric_keyframes": None,
        "enable_video_mask": True,
        "digital_human_template_group_id": "",
        "color_correct_alg_result": "",
        "source": "segmentsourcenormal",
        "enable_mask_stroke": False,
        "enable_mask_shadow": False,
        "enable_color_adjust_pro": False,
        "segment_color_tag": "",
    }


def make_audio_segment(seg_id, mat_id, extra_refs, src_start, src_dur,
                       tgt_start, tgt_dur, volume) -> dict:
    return {
        "id": seg_id,
        "material_id": mat_id,
        "extra_material_refs": extra_refs,
        "source_timerange": {"start": src_start, "duration": src_dur},
        "target_timerange": {"start": tgt_start, "duration": tgt_dur},
        "render_timerange": {"start": 0, "duration": 0},
        "desc": "",
        "state": 0,
        "speed": 1.0,
        "volume": volume,
        "last_nonzero_volume": volume if volume > 0 else 1.0,
        "is_loop": False,
        "is_tone_modify": False,
        "reverse": False,
        "intensifies_audio": False,
        "cartoon": False,
        "clip": None,
        "uniform_scale": None,
        "render_index": 0,
        "track_render_index": 0,
        "track_attribute": 0,
        "keyframe_refs": [],
        "common_keyframes": [],
        "caption_info": None,
        "visible": True,
        "group_id": "",
        "enable_lut": False,
        "enable_adjust": False,
        "enable_hsl": False,
        "enable_color_curves": True,
        "enable_hsl_curves": True,
        "enable_color_wheels": True,
        "enable_video_mask": True,
        "enable_mask_stroke": False,
        "enable_mask_shadow": False,
        "enable_smart_color_adjust": False,
        "enable_color_match_adjust": False,
        "enable_color_correct_adjust": False,
        "enable_color_adjust_pro": False,
        "enable_adjust_mask": False,
        "is_placeholder": False,
        "template_id": "",
        "template_scene": "default",
        "responsive_layout": {
            "enable": False, "target_follow": "", "size_layout": 0,
            "horizontal_pos_layout": 0, "vertical_pos_layout": 0,
        },
        "raw_segment_id": "",
        "lyric_keyframes": None,
        "digital_human_template_group_id": "",
        "color_correct_alg_result": "",
        "source": "segmentsourcenormal",
        "segment_color_tag": "",
        "hdr_settings": None,
    }


# --------------------------------------------------------------------------
# draft_content.json
# --------------------------------------------------------------------------


def build_draft_content(timeline_id, tracks_json, materials, tb: Timebase,
                        width, height, duration_us, platform) -> dict:
    return {
        "id": timeline_id,
        "version": 360000,
        "new_version": "179.0.0",
        "name": "",
        "duration": duration_us,
        "create_time": 0,
        "update_time": 0,
        "fps": round(tb.fps_float, 6),
        "is_drop_frame_timecode": False,
        "color_space": 0,
        "config": {
            "video_mute": False,
            "record_audio_last_index": 1,
            "extract_audio_last_index": 1,
            "original_sound_last_index": 1,
            "subtitle_recognition_id": "",
            "subtitle_taskinfo": [],
            "lyrics_recognition_id": "",
            "lyrics_taskinfo": [],
            "subtitle_sync": True,
            "lyrics_sync": True,
            "voice_change_sync": False,
            "sticker_max_index": 1,
            "adjust_max_index": 1,
            "material_save_mode": 0,
            "export_range": None,
            "maintrack_adsorb": True,
            "combination_max_index": 1,
            "attachment_info": [],
            "zoom_info_params": None,
            "system_font_list": [],
            "multi_language_mode": "none",
            "multi_language_main": "none",
            "multi_language_current": "none",
            "multi_language_list": [],
            "subtitle_keywords_config": None,
            "use_float_render": False,
        },
        "canvas_config": {"ratio": "original", "width": width, "height": height,
                          "background": None},
        "tracks": tracks_json,
        "group_container": None,
        "materials": materials,
        "keyframes": {
            "videos": [], "audios": [], "texts": [], "stickers": [],
            "filters": [], "adjusts": [], "handwrites": [], "effects": [],
        },
        "keyframe_graph_list": [],
        "platform": platform,
        "last_modified_platform": platform,
        "mutable_config": None,
        "cover": None,
        "retouch_cover": None,
        "extra_info": None,
        "relationships": [],
        "mixed_track_mode_on": False,
        "render_index_track_mode_on": True,
        "free_render_index_mode_on": False,
        "static_cover_image_path": "",
        "source": "default",
        "time_marks": None,
        "path": "",
        "lyrics_effects": [],
        "uneven_animation_template_info": {
            "composition": "", "content": "", "order": "", "sub_template_info_list": [],
        },
        "draft_type": "video",
        "smart_ads_info": {"page_from": "", "routine": "", "draft_url": ""},
        "function_assistant_info": {
            "smart_rec_applied": False, "fixed_rec_applied": False,
            "auto_adjust": False, "auto_adjust_segid_list": [],
            "color_correction": False, "color_correction_segid_list": [],
            "enhance_quality": False, "smooth_slow_motion": False,
            "deflicker_segid_list": [], "video_noise_segid_list": [],
            "enhance_quality_segid_list": [], "smart_segid_list": [],
            "retouch": False, "retouch_segid_list": [], "enhande_voice": False,
            "enhance_voice_segid_list": [], "audio_noise_segid_list": [],
            "auto_caption": False, "auto_caption_segid_list": [],
            "auto_caption_template_id": "", "caption_opt": False,
            "caption_opt_segid_list": [], "eye_correction": False,
            "eye_correction_segid_list": [], "normalize_loudness": False,
            "normalize_loudness_segid_list": [],
            "normalize_loudness_audio_denoise_segid_list": [],
            "auto_adjust_fixed": False, "auto_adjust_fixed_value": 50.0,
            "color_correction_fixed": False, "color_correction_fixed_value": 50.0,
            "normalize_loudness_fixed": False, "enhande_voice_fixed": False,
            "retouch_fixed": False, "enhance_quality_fixed": False,
            "smooth_slow_motion_fixed": False,
            "fps": {"num": 0, "den": 1},
        },
    }


# --------------------------------------------------------------------------
# Static side files
# --------------------------------------------------------------------------


ATTACHMENT_PC_COMMON = {
    "ai_packaging_infos": [],
    "ai_packaging_report_info": {
        "caption_id_list": [], "commercial_material": "", "material_source": "",
        "method": "", "page_from": "", "style": "", "task_id": "", "text_style": "",
        "tos_id": "", "video_category": "",
    },
    "broll": {
        "ai_packaging_infos": [],
        "ai_packaging_report_info": {
            "caption_id_list": [], "commercial_material": "", "material_source": "",
            "method": "", "page_from": "", "style": "", "task_id": "", "text_style": "",
            "tos_id": "", "video_category": "",
        },
    },
    "commercial_music_category_ids": [],
    "pc_feature_flag": 0,
    "recognize_tasks": [],
    "reference_lines_config": {"horizontal_lines": [], "is_lock": False,
                               "is_visible": False, "vertical_lines": []},
    "safe_area_type": 0,
    "template_item_infos": [],
    "unlock_template_ids": [],
}

ATTACHMENT_PC_TIMELINE = {
    "reference_lines_config": {"horizontal_lines": [], "is_lock": False,
                               "is_visible": False, "vertical_lines": []},
    "safe_area_type": 0,
}

ATTACHMENT_GEN_AI_INFO = {
    "gen_ai": {
        "ai_func_config": {
            "ai_common_configs": [], "ai_effect_configs": [],
            "ai_func_list": [], "aigc_generation_configs": [],
        },
        "cc_agent_info": {
            "agent_stringent_section_id_list": [], "agent_stringent_used_tool_list": [],
            "click_cnt": 0, "consume_credits_function_list": [],
            "conversation_ids": [], "generate_success_cnt": 0,
            "is_agent_stringent_used": False, "is_agent_used": True,
            "local_section_id_list": [], "real_skill_list": [],
            "request_cnt": 0, "request_from": [], "tool_list": [],
            "user_select_skill_list": [],
        },
        "id": "", "scene": "", "version": "1.0.0",
    }
}

ATTACHMENT_EDITING = {
    "editing_draft": {
        "ai_remove_filter_words": {"enter_source": "", "right_id": ""},
        "ai_shorts_info": {"report_params": "", "type": 0},
        "cover_extra_info": {
            "draft_id": "", "position": 0, "select_segment_id": "",
            "select_segment_source_start": 0, "select_segment_target_start": 0,
            "slot_image_path": "",
            "slot_info_config": {"slot_image_path": "", "used_video_algorithm_configs": []},
            "type": 1, "video_draft_source": -1,
        },
        "crop_info_extra": {"crop_mirror_type": 0, "crop_rotate": 0.0, "crop_rotate_total": 0.0},
        "digital_human_template_to_video_info": {"has_upload_material": False, "template_type": 0},
        "draft_used_recommend_function": "",
        "edit_type": 0,
        "eye_correct_enabled_multi_face_time": 0,
        "has_adjusted_render_layer": False,
        "image_ai_chat_info": {
            "before_chat_edit": False, "draft_modify_time": 0, "generate_type": "",
            "inspiration_item_id": "", "inspiration_item_name": "",
            "keyword_content": "", "keyword_id": "", "keyword_name": "",
            "keyword_type": "", "message_id": "", "model_name": "",
            "need_restore": False, "picture_id": "", "prompt_content": "",
            "prompt_from": "", "sugs_info": [],
        },
        "image_ai_template_info": {"first_draw_type": "", "inspiration_id": "", "request_id": ""},
        "is_open_expand_player": False,
        "is_template_text_ai_generate": False,
        "is_use_adjust": False,
        "is_use_ai_expand": False,
        "is_use_ai_image": False,
        "is_use_ai_remove": False,
        "is_use_ai_video": False,
        "is_use_audio_separation": False,
        "is_use_chroma_key": False,
        "is_use_curve_speed": False,
        "is_use_digital_human": False,
        "is_use_edit_multi_camera": False,
        "is_use_lip_sync": False,
        "is_use_lock_object": False,
        "is_use_loudness_unify": False,
        "is_use_noise_reduction": False,
        "is_use_one_click_beauty": False,
        "is_use_one_click_ultra_hd": False,
        "is_use_retouch_face": False,
        "is_use_smart_adjust_color": False,
        "is_use_smart_body_beautify": False,
        "is_use_smart_motion": False,
        "is_use_subtitle_recognition": False,
        "is_use_text_to_audio": False,
        "material_edit_session": {"material_edit_info": [], "session_id": "", "session_time": 0},
        "paste_segment_list": [],
        "profile_entrance_type": "",
        "publish_enter_from": "",
        "publish_type": "",
        "single_function_type": 0,
        "text_convert_case_types": [],
        "version": "1.0.0",
        "video_recording_create_draft": "",
    }
}

EMPTY_PLATFORM = {
    "app_id": 0, "app_source": "", "app_version": "", "device_id": "",
    "hard_disk_id": "", "mac_address": "", "os": "", "os_version": "",
}


def make_template_tmp(width, height, fps) -> dict:
    return {
        "canvas_config": {"background": None, "height": height, "ratio": "original", "width": width},
        "color_space": -1,
        "config": {
            "adjust_max_index": 1, "attachment_info": [], "combination_max_index": 1,
            "export_range": None, "extract_audio_last_index": 1,
            "lyrics_recognition_id": "", "lyrics_sync": True, "lyrics_taskinfo": [],
            "maintrack_adsorb": True, "material_save_mode": 0,
            "multi_language_current": "none", "multi_language_list": [],
            "multi_language_main": "none", "multi_language_mode": "none",
            "original_sound_last_index": 1, "record_audio_last_index": 1,
            "sticker_max_index": 1, "subtitle_keywords_config": None,
            "subtitle_recognition_id": "", "subtitle_sync": True,
            "subtitle_taskinfo": [], "system_font_list": [], "use_float_render": False,
            "video_mute": False, "voice_change_sync": False, "zoom_info_params": None,
        },
        "cover": None,
        "create_time": 0,
        "draft_type": "video",
        "duration": 0,
        "extra_info": None,
        "fps": fps,
        "free_render_index_mode_on": False,
        "function_assistant_info": {
            "audio_noise_segid_list": [], "auto_adjust": False, "auto_adjust_fixed": False,
            "auto_adjust_fixed_value": 50.0, "auto_adjust_segid_list": [],
            "auto_caption": False, "auto_caption_segid_list": [],
            "auto_caption_template_id": "", "caption_opt": False,
            "caption_opt_segid_list": [], "color_correction": False,
            "color_correction_fixed": False, "color_correction_fixed_value": 50.0,
            "color_correction_segid_list": [], "deflicker_segid_list": [],
            "enhance_quality": False, "enhance_quality_fixed": False,
            "enhance_quality_segid_list": [], "enhance_voice_segid_list": [],
            "enhande_voice": False, "enhande_voice_fixed": False,
            "eye_correction": False, "eye_correction_segid_list": [],
            "fixed_rec_applied": False, "fps": {"den": 1, "num": 0},
            "normalize_loudness": False, "normalize_loudness_audio_denoise_segid_list": [],
            "normalize_loudness_fixed": False, "normalize_loudness_segid_list": [],
            "retouch": False, "retouch_fixed": False, "retouch_segid_list": [],
            "smart_rec_applied": False, "smart_segid_list": [], "smooth_slow_motion": False,
            "smooth_slow_motion_fixed": False, "video_noise_segid_list": [],
        },
        "group_container": None,
        "id": new_id(),
        "is_drop_frame_timecode": False,
        "keyframe_graph_list": [],
        "keyframes": {
            "adjusts": [], "audios": [], "effects": [], "filters": [],
            "handwrites": [], "stickers": [], "texts": [], "videos": [],
        },
        "last_modified_platform": dict(EMPTY_PLATFORM),
        "lyrics_effects": [],
        "materials": make_materials_dict(),
        "mixed_track_mode_on": False,
        "mutable_config": None,
        "name": "",
        "new_version": "75.0.0",
        "path": "",
        "platform": dict(EMPTY_PLATFORM),
        "relationships": [],
        "render_index_track_mode_on": False,
        "retouch_cover": None,
        "smart_ads_info": {"draft_url": "", "page_from": "", "routine": ""},
        "source": "default",
        "static_cover_image_path": "",
        "time_marks": None,
        "tracks": [],
        "uneven_animation_template_info": {
            "composition": "", "content": "", "order": "", "sub_template_info_list": [],
        },
        "update_time": 0,
        "version": 360000,
    }


def make_meta_info(project_dir, draft_id, project_name, assets, none_material_id,
                   now_s, now_us, duration_us) -> dict:
    """draft_materials type 0 gets one entry per DISTINCT imported file."""
    entries = [{
        "ai_group_type": "", "create_time": now_s, "duration": 33333, "enter_from": 0,
        "extra_info": "", "file_Path": "", "height": 0, "id": none_material_id,
        "import_time": now_s, "import_time_ms": now_us, "item_source": 1,
        "material_color_tag": "", "md5": "", "metetype": "none",
        "roughcut_time_range": {"duration": 33333, "start": 0},
        "sub_time_range": {"duration": -1, "start": -1}, "type": 0, "width": 0,
    }]
    metetype = {"video": "video", "photo": "photo", "audio": "music"}
    for asset in assets:
        dur = 5_000_000 if asset.kind == "photo" else asset.duration_us
        entries.append({
            "ai_group_type": "", "create_time": now_s, "duration": dur,
            "enter_from": 0, "extra_info": os.path.basename(asset.path) or asset.name,
            "file_Path": asset.path,
            "height": asset.height if asset.kind != "audio" else 0,
            "id": asset.local_material_id, "import_time": now_s,
            "import_time_ms": now_us, "item_source": 1, "material_color_tag": "",
            "md5": "", "metetype": metetype[asset.kind],
            "roughcut_time_range": {"duration": dur, "start": 0},
            "sub_time_range": {"duration": -1, "start": -1}, "type": 0,
            "width": asset.width if asset.kind != "audio" else 0,
        })
    materials_size = sum(a.file_size for a in assets)
    return {
        "cloud_draft_cover": False,
        "cloud_draft_sync": False,
        "cloud_package_completed_time": "",
        "draft_cloud_capcut_purchase_info": "",
        "draft_cloud_last_action_download": False,
        "draft_cloud_package_type": "",
        "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": "draft_cover.jpg",
        "draft_deeplink_url": "",
        "draft_enterprise_info": {
            "draft_enterprise_extra": "", "draft_enterprise_id": "",
            "draft_enterprise_name": "", "enterprise_material": [],
        },
        "draft_fold_path": project_dir.replace("\\", "/"),
        "draft_id": draft_id,
        "draft_is_ae_produce": False,
        "draft_is_ai_packaging_used": False,
        "draft_is_ai_shorts": False,
        "draft_is_ai_translate": False,
        "draft_is_article_video_draft": False,
        "draft_is_cloud_temp_draft": False,
        "draft_is_from_deeplink": "false",
        "draft_is_invisible": False,
        "draft_is_pippit_draft": False,
        "draft_is_web_article_video": False,
        "draft_materials": [
            {"type": 0, "value": entries},
            {"type": 1, "value": []},
            {"type": 2, "value": []},
            {"type": 3, "value": []},
            {"type": 6, "value": []},
            {"type": 7, "value": []},
            {"type": 8, "value": []},
        ],
        "draft_materials_copied_info": [],
        "draft_name": project_name,
        "draft_need_rename_folder": False,
        "draft_new_version": "",
        "draft_removable_storage_device": "",
        "draft_root_path": os.path.dirname(os.path.normpath(project_dir)),
        "draft_segment_extra_info": [],
        "draft_timeline_materials_size_": materials_size,
        "draft_type": "",
        "draft_web_article_video_enter_from": "",
        "pippit_avatar_url": "",
        "pippit_extra_info": "",
        "pippit_id": "",
        "pippit_user_name": "",
        "tm_draft_cloud_completed": "",
        "tm_draft_cloud_entry_id": -1,
        "tm_draft_cloud_modified": 0,
        "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_space_id": -1,
        "tm_draft_cloud_user_id": -1,
        "tm_draft_create": now_us,
        "tm_draft_modified": now_us,
        "tm_draft_removed": 0,
        "tm_duration": duration_us,
    }


def make_virtual_store(local_material_ids) -> dict:
    return {
        "draft_materials": [],
        "draft_virtual_store": [
            {
                "type": 0,
                "value": [{
                    "creation_time": 0, "display_name": "", "filter_type": 0, "id": "",
                    "import_time": 0, "import_time_us": 0, "material_color_tag": "",
                    "sort_sub_type": 0, "sort_type": 0, "subdraft_filter_type": 0,
                }],
            },
            {"type": 1, "value": [{"child_id": mid, "parent_id": ""} for mid in local_material_ids]},
            {"type": 2, "value": []},
        ],
    }


def kv_master(material_id, material_name) -> dict:
    return {
        "Tiktok_music_is_avaliable": False,
        "add_to_timeline_before_download": False,
        "commerce_template_cate": "", "commerce_template_pay_status": "",
        "commerce_template_pay_type": "", "enter_from": "", "filter_category": "",
        "filter_detail": "", "is_brand": 0, "is_favorite": False,
        "is_from_artist_shop": 0, "is_limited": False, "is_similar_music": False,
        "is_vip": "0", "keywordSource": "", "materialCategory": "media",
        "materialId": material_id, "materialName": material_name,
        "materialSubcategory": "local", "materialSubcategoryId": "",
        "materialThirdcategory": "Import", "materialThirdcategoryId": "",
        "material_copyright": "", "material_is_purchased": "", "music_source": "",
        "original_song_id": "", "original_song_name": "", "pgc_id": "",
        "pgc_name": "", "previewed": 0, "previewed_before_added": 0,
        "rank": "0", "rec_id": "", "requestId": "", "right_block_type": "",
        "right_count_type": "", "right_is_trial": "", "right_oneoff_mix_type": "",
        "right_trial_limit_left": "", "right_trial_mode": "", "right_trial_type": "",
        "role": "", "searchId": "", "searchKeyword": "",
        "special_effect_loading_type": "", "team_id": "", "template_author_id": "",
        "template_drafts_price": 0, "template_duration": 0,
        "template_fragment_cnt": 0, "template_need_purcahse": True,
        "template_pay_type": "", "template_type": "", "template_use_cnt": 0,
        "textTemplateVersion": "",
    }


def kv_segment(seg_id, material_id, material_name) -> dict:
    return {
        "filter_category": "", "filter_detail": "", "is_brand": 0,
        "is_from_artist_shop": 0, "is_vip": "0", "keywordSource": "",
        "materialCategory": "media", "materialId": material_id,
        "materialName": material_name, "materialSubcategory": "local",
        "materialSubcategoryId": "", "materialThirdcategory": "Import",
        "materialThirdcategoryId": "", "material_copyright": "",
        "material_is_purchased": "", "rank": "0", "rec_id": "", "requestId": "",
        "role": "", "searchId": "", "searchKeyword": "",
        "segmentId": seg_id, "team_id": "", "textTemplateVersion": "",
    }


def make_project_json(project_id, timeline_id, now_us) -> dict:
    return {
        "config": {
            "color_space": -1, "mixed_track_mode_on": False,
            "render_index_track_mode_on": False, "use_float_render": False,
        },
        "create_time": now_us,
        "id": project_id,
        "main_timeline_id": timeline_id,
        "timelines": [{
            "create_time": now_us, "id": timeline_id, "is_marked_delete": False,
            "name": "Timeline 01", "update_time": now_us,
        }],
        "update_time": now_us,
        "version": 0,
    }


def make_timeline_layout(timeline_id) -> dict:
    return {
        "dockItems": [{
            "dockIndex": 0, "ratio": 1,
            "timelineIds": [timeline_id], "timelineNames": ["Timeline 01"],
        }],
        "layoutOrientation": 1,
    }


# --------------------------------------------------------------------------
# mini_draft (undo/redo cache)
# --------------------------------------------------------------------------


def make_mini_segment(seg, asset, aux, track_index, segment_index,
                      is_photo, is_audio) -> dict:
    """Compact mirror of one segment. CapCut rebuilds this cache on the first
    edit; what matters is that ids, track/segment indices and time ranges agree
    with draft_content.json."""
    base = {
        "__is_complete": True,
        "id": seg["id"],
        "segment_index": segment_index,
        "track_index": track_index,
        "source_time_range": {
            "duration": seg["source_timerange"]["duration"],
            "id": new_id(),
            "start": seg["source_timerange"]["start"],
        },
        "target_time_range": {
            "duration": seg["target_timerange"]["duration"],
            "id": new_id(),
            "start": seg["target_timerange"]["start"],
        },
        "render_timerange": {"duration": 0, "id": new_id(), "start": 0},
        "render_index": seg.get("render_index", 0),
        "track_render_index": seg.get("track_render_index", 0),
        "track_attribute": 0,
        "speed": {"curve_speed": None, "id": aux["speed"], "mode": 0, "speed": 1.0,
                  "type": "speed"},
        "volume": seg.get("volume", 1.0),
        "last_nonzero_volume": seg.get("last_nonzero_volume", 1.0),
        "state": 0,
        "reverse": False,
        "is_loop": False,
        "is_placeholder": False,
        "is_tone_modify": False,
        "intensifies_audio": False,
        "visible": True,
        "runtime_visible": True,
        "group_id": "",
        "desc": "",
        "raw_segment_id": "",
        "segment_color_tag": "",
        "template_id": "",
        "template_scene": 0,
        "source": 0,
        "sound_channel_mapping": {
            "audio_channel_mapping": 0, "id": aux["scm"], "is_config_open": False, "type": "",
        },
        "vocal_separation": {
            "choice": 0, "enter_from": "", "final_algorithm": "",
            "id": aux["vsep"], "production_path": "", "removed_sounds": [],
            "time_range": None, "type": "vocal_separation",
        },
    }

    if is_audio:
        base.update({
            "type": "segment_audio",
            "material": {
                "app_id": 0, "category_id": "", "category_name": "local",
                "check_flag": 1, "duration": asset.duration_us,
                "id": seg["material_id"], "local_material_id": asset.local_material_id,
                "music_id": "", "name": os.path.basename(asset.path) or asset.name,
                "path": asset.path, "source_platform": 0, "team_id": "",
                "type": "extract_music", "wave_points": [],
            },
            "beat": {"id": aux.get("beats", ""), "type": "beats"},
        })
        return base

    base.update({
        "type": "segment_video",
        "ai_matting": 0,
        "alpha": seg["clip"]["alpha"],
        "cartoon": False,
        "clip": {
            "bounding_box": [],
            "flip": {"horizontal": False, "id": new_id(), "vertical": False},
            "id": new_id(),
            "rotation": seg["clip"]["rotation"],
            "scale": {"id": new_id(), "x": seg["clip"]["scale"]["x"],
                      "y": seg["clip"]["scale"]["y"]},
            "transform": {"id": new_id(), "x": seg["clip"]["transform"]["x"],
                          "y": seg["clip"]["transform"]["y"]},
        },
        "background": {
            "album_image": "", "blur": 0.0, "color": "", "id": aux["canvas"],
            "image": "", "image_id": "", "image_name": "", "source_platform": 0,
            "team_id": "", "type": "canvas_color",
        },
        "crop": {
            "id": new_id(), "lower_left_x": 0.0, "lower_left_y": 1.0,
            "lower_right_x": 1.0, "lower_right_y": 1.0, "upper_left_x": 0.0,
            "upper_left_y": 0.0, "upper_right_x": 1.0, "upper_right_y": 0.0,
        },
        "crop_ratio": 0,
        "crop_scale": 1.0,
        "enable_mask_shadow": False,
        "enable_mask_stroke": False,
        "enable_video_mask": True,
        "hdr_settings": {"id": new_id(), "intensity": 1.0, "mode": 1, "nits": 1000},
        "material": {
            "aigc_type": 0, "category_id": "", "category_name": "local",
            "check_flag": 62978047,
            "duration": PHOTO_MATERIAL_US if is_photo else asset.duration_us,
            "has_audio": bool(asset.has_audio) and not is_photo,
            "height": asset.height, "id": seg["material_id"],
            "local_material_id": asset.local_material_id,
            "material_id": "", "material_name": os.path.basename(asset.path) or asset.name,
            "material_url": "", "media_path": "", "path": asset.path,
            "picture_from": 0, "source": 0, "source_platform": 0, "team_id": "",
            "type": "photo" if is_photo else "video", "unique_id": "",
            "width": asset.width,
        },
        "material_color": {
            "gradient_angle": 90.0, "gradient_colors": [], "gradient_percents": [],
            "height": 0.0, "id": aux["mcolor"], "is_color_clip": False,
            "is_gradient": False, "solid_color": "", "type": "", "width": 0.0,
        },
        "matting": {
            "blendColor": "", "blendMode": 0, "cloud_product_fps": 0.0,
            "copiedSegmentId": "", "custom_matting_id": "",
            "enable_matting_stroke": False, "expansion": 0, "feather": 0,
            "flag": 0, "has_use_quick_brush": False, "has_use_quick_eraser": False,
            "id": new_id(), "interactiveTime": [], "isCopiedMask": True,
            "is_clould": False, "mask_video_path": "", "path": "", "reverse": False,
            "strokes": None,
        },
        "placeholder_info": {
            "error_path": "", "error_text": "", "id": aux["placeholder"],
            "meta_type": 0, "res_path": "", "res_text": "", "type": "placeholder_info",
        },
        "stable": {
            "id": new_id(), "matrix_path": "", "stable_level": 0,
            "time_range": {"duration": 0, "id": new_id(), "start": 0},
        },
        "uniform_scale": {"id": new_id(), "on": seg["uniform_scale"]["on"],
                          "value": seg["uniform_scale"]["value"]},
    })
    return base


def make_mini_draft(timeline_id, tracks_json, mini_segments, duration_us,
                    fps, width, height, now_s, now_us) -> dict:
    return {
        "base_mini_draft_has_ack": True,
        "mini_draft_data": {
            "draft": {
                "canvas_config": {"background": None, "height": height, "ratio": 0,
                                  "width": width},
                "canvas_scale": {"x": 1.0, "y": 1.0},
                "color_space": 0,
                "config": {"export_range": None, "maintrack_adsorb": True,
                           "video_mute": False, "zoom_info_params": None},
                "create_time": 0,
                "duration": duration_us,
                "fps": fps,
                "id": timeline_id,
                "name": "",
                "new_version": "179.0.0",
                "tracks": [
                    {"attribute": 0, "id": t["id"],
                     "segments": [s["id"] for s in t["segments"]]}
                    for t in tracks_json
                ],
                "update_time": 0,
            },
            "header": {
                "action_name": "",
                "draft_id": timeline_id,
                "index": len(mini_segments),
                "mini_draft_version": 0,
                "timestamp": now_s,
                "timestamp_ms": now_us,
                "type": "minidraft",
            },
            "material_drafts": [],
            "segments": mini_segments,
        },
    }


# --------------------------------------------------------------------------
# Cover image
# --------------------------------------------------------------------------


def make_cover(output_dir, clips, tb: Timebase, width, height, warnings) -> None:
    jpg = os.path.join(output_dir, "draft_cover.jpg")
    os.makedirs(output_dir, exist_ok=True)
    source = next((c for c in clips if c.asset.kind == "video" and c.asset.exists), None)
    if source is None:
        source = next((c for c in clips if c.asset.exists), None)
    if source is not None:
        seek = max(0.0, tb.frames_to_us(source.start_frames) / 1_000_000.0)
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(seek), "-i", source.asset.path,
                 "-frames:v", "1", "-vf", f"scale={width}:{height}", "-q:v", "2", jpg],
                check=True, capture_output=True, timeout=120,
            )
            if os.path.isfile(jpg) and os.path.getsize(jpg) > 0:
                return
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        from PIL import Image
        Image.new("RGB", (width, height), (10, 10, 10)).save(jpg, "JPEG", quality=85)
    except Exception:
        with open(jpg, "wb") as f:
            f.write(b"")
        warnings.append("could not render draft_cover.jpg (install ffmpeg or Pillow)")


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------


def verify(project_dir: str) -> list[str]:
    """Re-read what was written and check the invariants CapCut relies on."""
    problems: list[str] = []
    content_path = os.path.join(project_dir, "draft_content.json")
    with open(content_path, encoding="utf-8") as f:
        draft = json.load(f)

    material_index = {}
    for bucket, items in draft["materials"].items():
        for m in items:
            if m.get("id"):
                material_index[m["id"]] = (bucket, m)

    seen_segment_ids = set()
    max_end = 0
    for ti, track in enumerate(draft["tracks"]):
        prev_end = -1
        for si, seg in enumerate(track["segments"]):
            if seg["id"] in seen_segment_ids:
                problems.append(f"duplicate segment id {seg['id']}")
            seen_segment_ids.add(seg["id"])

            if seg["material_id"] not in material_index:
                problems.append(
                    f"track {ti} segment {si}: material_id {seg['material_id']} not in materials")
            for ref in seg["extra_material_refs"]:
                if ref not in material_index:
                    problems.append(
                        f"track {ti} segment {si}: extra_material_ref {ref} not in materials")

            tgt = seg["target_timerange"]
            if tgt["duration"] <= 0:
                problems.append(f"track {ti} segment {si}: non-positive duration")
            if tgt["start"] < prev_end:
                problems.append(
                    f"track {ti} segment {si}: overlaps the previous segment "
                    f"({tgt['start']} < {prev_end})")
            prev_end = tgt["start"] + tgt["duration"]
            max_end = max(max_end, prev_end)

            mat = material_index.get(seg["material_id"], (None, {}))[1]
            src = seg.get("source_timerange") or {}
            if mat and src and mat.get("duration"):
                src_end = src["start"] + src["duration"]
                if src_end > mat["duration"] + 1:
                    problems.append(
                        f"track {ti} segment {si}: source in/out {src_end}us runs past "
                        f"the material ({mat['duration']}us) — CapCut will clamp it")

    if draft["duration"] != max_end:
        problems.append(f"draft duration {draft['duration']} != last segment end {max_end}")

    missing = sorted({m["path"] for _, m in material_index.values()
                      if m.get("path") and not os.path.isfile(m["path"])})
    for p in missing:
        problems.append(f"media file missing on disk: {p}")

    # key_value / meta / virtual store coverage
    with open(os.path.join(project_dir, "key_value.json"), encoding="utf-8") as f:
        kv = json.load(f)
    for sid in seen_segment_ids:
        if sid not in kv:
            problems.append(f"key_value.json has no entry for segment {sid}")
            break

    with open(os.path.join(project_dir, "draft_meta_info.json"), encoding="utf-8") as f:
        meta = json.load(f)
    meta_ids = {v["id"] for grp in meta["draft_materials"] if grp["type"] == 0
                for v in grp["value"]}
    with open(os.path.join(project_dir, "draft_virtual_store.json"), encoding="utf-8") as f:
        vstore = json.load(f)
    store_ids = {v["child_id"] for grp in vstore["draft_virtual_store"]
                 if grp["type"] == 1 for v in grp["value"]}
    local_ids = {m.get("local_material_id") for _, m in material_index.values()
                 if m.get("local_material_id")}
    for lid in sorted(local_ids - meta_ids):
        problems.append(f"local_material_id {lid} missing from draft_meta_info.json")
    for lid in sorted(local_ids - store_ids):
        problems.append(f"local_material_id {lid} missing from draft_virtual_store.json")

    return problems


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def convert(fcpxml_path, output_dir, config, force=False, dry_run=False) -> str | None:
    warnings: list[str] = []

    print(f"Reading {fcpxml_path}")
    tl = parse_fcpxml(fcpxml_path, config.get("MEDIA_MAP") or {}, warnings)
    tb: Timebase = tl["timebase"]
    width, height = tl["width"], tl["height"]
    clips: list[Clip] = tl["clips"]
    if not clips:
        print("Error: no clips found in the spine")
        return None

    probe_assets(tl, bool(config.get("PROBE_MEDIA", True)), warnings)

    used_assets = []
    for c in clips:
        if c.asset not in used_assets:
            used_assets.append(c.asset)

    tracks = build_tracks(clips, warnings)

    print(f"  {tb.fps_float:g} fps  {width}x{height}")
    print(f"  {len(clips)} clips across {len(tracks)} CapCut tracks, "
          f"{len(used_assets)} distinct source files")
    for a in used_assets:
        n = sum(1 for c in clips if c.asset is a)
        print(f"    [{a.kind:5}] {n:3}x  {os.path.basename(a.path)}  "
              f"{a.width}x{a.height}  {a.duration_us / 1e6:.2f}s"
              f"{'' if a.exists else '   *** MISSING ***'}")

    if dry_run:
        for w in warnings:
            print(f"  warning: {w}")
        return None

    # --- build the timeline -------------------------------------------------
    timeline_id = new_id()
    materials = make_materials_dict()
    tracks_json = []
    mini_segments = []
    key_value = {}
    lane_transform = {int(k): v for k, v in (config.get("LANE_TRANSFORM") or {}).items()}
    lane_volume = {int(k): float(v) for k, v in (config.get("LANE_VOLUME") or {}).items()}
    has_audio_track = False

    for track_index, track in enumerate(tracks):
        track_id = new_id()
        is_audio_track = track["kind"] == "audio"
        has_audio_track = has_audio_track or is_audio_track
        stack = track["stack"]
        render_base = 0 if (is_audio_track or stack == 0) else \
            OVERLAY_RENDER_BASE + (stack - 1) * OVERLAY_RENDER_STRIDE
        segments = []

        for ordinal, clip in enumerate(track["clips"]):
            asset = clip.asset
            seg_id = new_id()
            mat_id = new_id()
            aux = {
                "speed": new_id(),
                "placeholder": new_id(),
                "canvas": new_id(),
                "scm": new_id(),
                "mcolor": new_id(),
                "vsep": new_id(),
                "beats": new_id(),
            }
            is_photo = asset.kind == "photo"
            is_audio = asset.kind == "audio"

            tgt_start = tb.frames_to_us(clip.offset_frames)
            tgt_dur = tb.frames_to_us(clip.duration_frames)
            src_start = 0 if is_photo else tb.frames_to_us(clip.start_frames)
            src_dur = tgt_dur

            # Never let the in/out run past the material or CapCut clamps it.
            mat_dur = PHOTO_MATERIAL_US if is_photo else asset.duration_us
            if mat_dur and src_start + src_dur > mat_dur:
                over = src_start + src_dur - mat_dur
                warnings.append(
                    f"{os.path.basename(asset.path)} @ {tgt_start / 1e6:.2f}s: source "
                    f"in/out ran {over / 1e6:.3f}s past the file, pulled the in-point back")
                src_start = max(0, src_start - over)

            volume = lane_volume.get(clip.lane, 1.0)
            if clip.volume is not None:
                volume = clip.volume

            if is_audio:
                materials["audios"].append(make_audio_material(mat_id, asset))
                materials["speeds"].append(make_speed(aux["speed"]))
                materials["beats"].append(make_beats(aux["beats"]))
                materials["sound_channel_mappings"].append(
                    make_sound_channel_mapping(aux["scm"]))
                materials["vocal_separations"].append(make_vocal_separation(aux["vsep"]))
                seg = make_audio_segment(
                    seg_id, mat_id,
                    [aux["speed"], aux["beats"], aux["scm"], aux["vsep"]],
                    src_start, src_dur, tgt_start, tgt_dur, volume,
                )
            else:
                transform = dict(lane_transform.get(clip.lane, {}))
                if "scale" in transform:
                    transform.setdefault("scale_x", float(transform["scale"]))
                    transform.setdefault("scale_y", float(transform["scale"]))
                transform.update(clip.transform)   # explicit XML wins over the lane default
                materials["videos"].append(make_video_material(mat_id, asset, is_photo))
                materials["speeds"].append(make_speed(aux["speed"]))
                materials["placeholder_infos"].append(make_placeholder_info(aux["placeholder"]))
                materials["canvases"].append(make_canvas(aux["canvas"]))
                materials["sound_channel_mappings"].append(
                    make_sound_channel_mapping(aux["scm"]))
                materials["material_colors"].append(make_material_color(aux["mcolor"]))
                materials["vocal_separations"].append(make_vocal_separation(aux["vsep"]))
                seg = make_visual_segment(
                    seg_id, mat_id,
                    [aux["speed"], aux["placeholder"], aux["canvas"], aux["scm"],
                     aux["mcolor"], aux["vsep"]],
                    src_start, src_dur, tgt_start, tgt_dur,
                    render_base if render_base == 0 else render_base + ordinal,
                    stack, transform, volume,
                )

            segments.append(seg)
            key_value[seg_id] = kv_segment(
                seg_id, asset.local_material_id, os.path.basename(asset.path) or asset.name)
            mini_segments.append(make_mini_segment(
                seg, asset, aux, track_index, ordinal, is_photo, is_audio))

        tracks_json.append({
            "id": track_id,
            "type": "audio" if is_audio_track else "video",
            "segments": segments,
            "flag": 0,
            "attribute": 0,
            "name": "",
            "is_default_name": True,
        })

    duration_us = max(
        (s["target_timerange"]["start"] + s["target_timerange"]["duration"]
         for t in tracks_json for s in t["segments"]),
        default=0,
    )

    for asset in used_assets:
        key_value[asset.local_material_id] = kv_master(
            asset.local_material_id, os.path.basename(asset.path) or asset.name)

    platform = config["PLATFORM"]
    draft_content = build_draft_content(timeline_id, tracks_json, materials, tb,
                                        width, height, duration_us, platform)

    now_s = int(time.time())
    now_us = now_s * 1_000_000
    project_name = os.path.basename(os.path.normpath(output_dir))
    none_material_id = new_local_id()

    meta_info = make_meta_info(output_dir, new_id(), project_name, used_assets,
                               none_material_id, now_s, now_us, duration_us)
    virtual_store = make_virtual_store(
        [none_material_id] + [a.local_material_id for a in used_assets])
    project_json = make_project_json(new_id(), timeline_id, now_us)
    timeline_layout = make_timeline_layout(timeline_id)
    mini_draft = make_mini_draft(timeline_id, tracks_json, mini_segments, duration_us,
                                 round(tb.fps_float, 6), width, height, now_s, now_us)
    template_tmp = make_template_tmp(width, height, round(tb.fps_float, 6))

    # --- write --------------------------------------------------------------
    if os.path.isdir(output_dir) and os.listdir(output_dir) and not force:
        print(f"Error: {output_dir} already exists and is not empty. "
              "Re-run with --force to overwrite it.")
        return None
    if os.path.isdir(output_dir) and force:
        shutil.rmtree(output_dir)

    tl_dir = os.path.join(output_dir, "Timelines", timeline_id)
    patch_dir = os.path.join(tl_dir, "attachment", "patch")
    common_att = os.path.join(tl_dir, "common_attachment")

    write_json(os.path.join(output_dir, "draft_content.json"), draft_content)
    copy_file(os.path.join(output_dir, "draft_content.json"),
              os.path.join(output_dir, "draft_content.json.bak"))
    copy_file(os.path.join(output_dir, "draft_content.json"),
              os.path.join(output_dir, "template-2.tmp"))

    write_json(os.path.join(output_dir, "draft_meta_info.json"), meta_info)
    write_json(os.path.join(output_dir, "key_value.json"), key_value)
    write_json(os.path.join(output_dir, "draft_virtual_store.json"), virtual_store)
    write_json(os.path.join(output_dir, "timeline_layout.json"), timeline_layout)
    write_json(os.path.join(output_dir, "attachment_pc_common.json"), ATTACHMENT_PC_COMMON)
    write_json(os.path.join(output_dir, "draft_agency_config.json"), {
        "is_auto_agency_enabled": False, "is_auto_agency_popup": False,
        "is_single_agency_mode": False, "marterials": None,
        "use_converter": False, "video_resolution": 720,
    })
    write_json(os.path.join(output_dir, "performance_opt_info.json"), {
        "manual_cancle_precombine_segs": None, "need_auto_precombine_segs": None,
    })
    write_json(os.path.join(output_dir, "common_attachment", "attachment_gen_ai_info.json"),
               ATTACHMENT_GEN_AI_INFO)
    write_json(os.path.join(output_dir, "common_attachment", "attachment_pc_timeline.json"),
               ATTACHMENT_PC_TIMELINE)

    for empty in ("draft_biz_config.json", ".locked"):
        with open(os.path.join(output_dir, empty), "w", encoding="utf-8") as f:
            f.write("")

    with open(os.path.join(output_dir, "draft_settings"), "w", encoding="utf-8") as f:
        f.write(
            "[General]\n"
            f"draft_create_time={now_s}\n"
            f"draft_last_edit_time={now_s}\n"
            "real_edit_seconds=1\n"
            "real_edit_keys=1\n"
            "cloud_last_modify_platform=windows\n"
        )

    agent_dir = os.path.join(output_dir, "agent")
    os.makedirs(agent_dir, exist_ok=True)
    with open(os.path.join(agent_dir, str(random.randint(10 ** 17, 10 ** 18 - 1))),
              "w", encoding="utf-8") as f:
        f.write(json_dump({"infos": [{"last_modify_time": now_s, "path": a.path}
                                     for a in used_assets]}))

    write_json(os.path.join(output_dir, "Timelines", "project.json"), project_json)
    copy_file(os.path.join(output_dir, "Timelines", "project.json"),
              os.path.join(output_dir, "Timelines", "project.json.bak"))

    write_json(os.path.join(tl_dir, "draft_content.json"), draft_content)
    copy_file(os.path.join(tl_dir, "draft_content.json"),
              os.path.join(tl_dir, "draft_content.json.bak"))
    copy_file(os.path.join(tl_dir, "draft_content.json"),
              os.path.join(tl_dir, "template-2.tmp"))
    write_json(os.path.join(tl_dir, "template.tmp"), template_tmp)
    write_json(os.path.join(tl_dir, "attachment_editing.json"), ATTACHMENT_EDITING)
    write_json(os.path.join(tl_dir, "attachment_pc_common.json"), ATTACHMENT_PC_COMMON)
    write_json(os.path.join(patch_dir, "patch.json"), {"patch_data": []})
    write_json(os.path.join(patch_dir, "mini_draft.json"), mini_draft)
    write_json(os.path.join(common_att, "attachment_action_scene.json"),
               {"action_scene": {"removed_segments": [], "segment_infos": []}})
    write_json(os.path.join(common_att, "attachment_gen_ai_info.json"), ATTACHMENT_GEN_AI_INFO)
    write_json(os.path.join(common_att, "attachment_pc_timeline.json"), ATTACHMENT_PC_TIMELINE)
    write_json(os.path.join(common_att, "attachment_plugin_draft.json"),
               {"plugin_draft": {"plugin_segments": [], "version": "1.0.0"}})
    write_json(os.path.join(common_att, "attachment_script_video.json"), {
        "script_video": {
            "attachment_valid": False, "language": "", "overdub_recover": [],
            "overdub_sentence_ids": [], "parts": [], "subtitle_sync": False,
            "translate_segments": [], "translate_type": "", "version": "1.0.0",
        }
    })

    for folder in ["adjust_mask", "matting", "qr_upload", "smart_crop", "subdraft",
                   os.path.join("Resources", "audioAlg"),
                   os.path.join("Resources", "videoAlg"),
                   os.path.join("Resources", "digitalHuman", "audio"),
                   os.path.join("Resources", "digitalHuman", "bsinfo"),
                   os.path.join("Resources", "digitalHuman", "video")]:
        os.makedirs(os.path.join(output_dir, folder), exist_ok=True)

    make_cover(output_dir, tracks[0]["clips"] if tracks else clips, tb, width, height, warnings)
    copy_file(os.path.join(output_dir, "draft_cover.jpg"),
              os.path.join(tl_dir, "draft_cover.jpg"))

    # --- report -------------------------------------------------------------
    print(f"\nWrote {output_dir}")
    print(f"  timeline_id = {timeline_id}")
    for i, t in enumerate(tracks_json):
        lane = tracks[i]["lane"]
        role = "main" if (t["type"] == "video" and tracks[i]["stack"] == 0) else \
               ("overlay" if t["type"] == "video" else "audio")
        print(f"  track {i}: {t['type']:5} {role:7} (fcpxml lane {lane:>2})  "
              f"{len(t['segments'])} segments")
    print(f"  duration = {duration_us}us ({duration_us / 1e6:.2f}s)")

    if has_audio_track:
        warnings.append(
            "this timeline has audio-only tracks; the CapCut audio schema here is "
            "reconstructed rather than copied from a reference project — check the "
            "audio track once CapCut opens the project")

    problems = verify(output_dir)
    if problems:
        print("\nVerification found issues:")
        for p in problems:
            print(f"  ! {p}")
    else:
        print("\nVerification passed (materials, track layout, source ranges, media paths).")

    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  - {w}")

    print("\nOpen CapCut — the project appears under Projects.")
    return output_dir


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert an FCPXML timeline to a CapCut draft.")
    ap.add_argument("fcpxml", nargs="?", help="input .fcpxml (defaults to CONFIG)")
    ap.add_argument("-o", "--output", help="output project folder (full path)")
    ap.add_argument("-n", "--name", help="project name; folder under the drafts root")
    ap.add_argument("--drafts-root", help="CapCut drafts root folder")
    ap.add_argument("--media-map", action="append", default=[], metavar="OLD=NEW",
                    help="rewrite a media path prefix (repeatable)")
    ap.add_argument("--no-probe", action="store_true", help="skip ffprobe")
    ap.add_argument("--force", action="store_true", help="overwrite an existing project folder")
    ap.add_argument("--dry-run", action="store_true", help="parse and report, write nothing")
    ap.add_argument("--verify", metavar="PROJECT_DIR",
                    help="only verify an existing CapCut project folder")
    args = ap.parse_args()

    if args.verify:
        problems = verify(args.verify)
        if problems:
            print("Issues:")
            for p in problems:
                print(f"  ! {p}")
            sys.exit(1)
        print("Verification passed.")
        return

    config = dict(CONFIG)
    if args.no_probe:
        config["PROBE_MEDIA"] = False
    if args.drafts_root:
        config["CAPCUT_DRAFTS_ROOT"] = args.drafts_root
    if args.media_map:
        mm = dict(config.get("MEDIA_MAP") or {})
        for pair in args.media_map:
            old, _, new = pair.partition("=")
            if not new:
                print(f"Error: --media-map needs OLD=NEW, got {pair!r}")
                sys.exit(2)
            mm[old] = new
        config["MEDIA_MAP"] = mm

    fcpxml_path = args.fcpxml or config["FCPXML_IN"]
    if not os.path.isfile(fcpxml_path):
        print(f"Error: fcpxml not found: {fcpxml_path}")
        sys.exit(1)

    output_dir = args.output or config.get("OUTPUT_DIR") or ""
    if not output_dir:
        root = config.get("CAPCUT_DRAFTS_ROOT") or ""
        if not root:
            print("Error: no --output and no CAPCUT_DRAFTS_ROOT")
            sys.exit(1)
        if args.name:
            folder = args.name
        else:
            try:
                folder = parse_fcpxml(fcpxml_path, {}, [])["project_name"]
            except ET.ParseError as exc:
                print(f"Error: could not parse {fcpxml_path}: {exc}")
                sys.exit(1)
            folder = folder or os.path.splitext(os.path.basename(fcpxml_path))[0]
        output_dir = os.path.join(root, folder)

    result = convert(fcpxml_path, output_dir, config,
                     force=args.force, dry_run=args.dry_run)
    if result is None and not args.dry_run:
        sys.exit(1)


if __name__ == "__main__":
    main()
