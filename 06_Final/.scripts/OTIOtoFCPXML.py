#!/usr/bin/env python3
"""
OTIOtoFCPXML.py
Convert the final OTIO timelines into Resolve-importable .fcpxml files.

    06_Final\\FinalTimelineNoCap.otio    ->  06_Final\\FinalTimelineNoCap.fcpxml
    06_Final\\FinalTimelineWithCap.otio  ->  06_Final\\FinalTimelineWithCap.fcpxml

How the OTIO stack maps onto FCPXML:

    Video 1  the edit     ->  the spine (primary storyline) as <asset-clip>
    Audio 1  the edit     ->  folded into those asset-clips (see below)
    Video 2  memes        ->  connected <video> clips on lane 1
    Video 3  captions     ->  connected <title> clips on lane 2

FCPXML has no notion of parallel video tracks the way OTIO does -- everything
above the primary storyline is a *connected clip* hanging off a spine item, with
its offset expressed in that parent's local time.  So each meme and caption is
attached to whichever edit clip is under it when it starts.

The edit's Audio 1 track is a Resolve link-group mirror of Video 1 (identical
ranges, identical media), so it is not emitted separately -- the asset-clips
carry their own audio.  If the two ever stop matching, the script says so and
writes the audio as connected clips on lane -1 instead.

Caption text is recovered from the Text+ "title blob" that srt_to_otio.py
writes -- a Qt rich-text HTML fragment -- and re-emitted as real FCPXML title
text, so the captions arrive in Resolve as editable titles rather than
placeholders.

No external dependencies -- writes the XML directly.

Usage:
    python OTIOtoFCPXML.py
    python OTIOtoFCPXML.py --version 1.10
    python OTIOtoFCPXML.py --no-titles
    python OTIOtoFCPXML.py FinalTimelineWithCap.otio -o custom.fcpxml
"""

import re
import json
import html
import argparse
import sys
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape, quoteattr

FINAL_DIR = Path(__file__).resolve().parent.parent

DEFAULT_INPUTS = [
    FINAL_DIR / "FinalTimelineNoCap.otio",
    FINAL_DIR / "FinalTimelineWithCap.otio",
]

# Resolve ships this as its stock title generator.
TITLE_EFFECT_UID = (
    ".../Titles.localized/Build In Out.localized/"
    "Basic Title.localized/Basic Title.moti"
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}


# ─── Time helpers ─────────────────────────────────────────────────────────────

def frame_duration(rate: float) -> str:
    """FCPXML frameDuration string for a frame rate."""
    ntsc = {
        23.976: "1001/24000s", 23.98: "1001/24000s",
        29.97:  "1001/30000s",
        47.952: "1001/48000s",
        59.94:  "1001/60000s",
        119.88: "1001/120000s",
    }
    key = round(rate, 3)
    if key in ntsc:
        return ntsc[key]
    if abs(rate - round(rate)) < 1e-6:
        return f"1/{int(round(rate))}s"
    # Fall back to a rational approximation
    f = Fraction(1 / rate).limit_denominator(120000)
    return f"{f.numerator}/{f.denominator}s"


def tval(frames: float, rate: float) -> str:
    """
    Express a frame count as an FCPXML rational time string.

    FCPXML wants times as exact rationals ("1001/30000s"), never decimals --
    decimal seconds are where round-tripping drifts.
    """
    frames = int(round(frames))
    if frames == 0:
        return "0s"
    key = round(rate, 3)
    ntsc = {23.976: (1001, 24000), 23.98: (1001, 24000), 29.97: (1001, 30000),
            47.952: (1001, 48000), 59.94: (1001, 60000), 119.88: (1001, 120000)}
    if key in ntsc:
        num, den = ntsc[key]
        f = Fraction(frames * num, den)
    else:
        f = Fraction(frames, int(round(rate)))
    if f.denominator == 1:
        return f"{f.numerator}s"
    return f"{f.numerator}/{f.denominator}s"


def file_url(path: str) -> str:
    """Windows path -> file:/// URL."""
    p = path.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", p):
        p = "/" + p
    return "file://" + quote(p, safe="/:")


# ─── OTIO reading ─────────────────────────────────────────────────────────────

def is_clip(node: dict) -> bool:
    return node.get("OTIO_SCHEMA", "").startswith("Clip")


def clip_url(clip: dict) -> str:
    ref = clip.get("media_references", {}).get(
        clip.get("active_media_reference_key", "DEFAULT_MEDIA"), {})
    return ref.get("target_url", "") or ""


def caption_text(clip: dict) -> str:
    """
    Pull the human-readable caption out of a Resolve Text+ generator.

    srt_to_otio.py stores the cue as a Qt rich-text HTML blob under the
    'title blob' parameter; each <p> is one line of the cue.
    """
    ref = clip.get("media_references", {}).get("DEFAULT_MEDIA", {})
    params = (ref.get("parameters") or {}).get("Resolve_OTIO") or []
    for group in params:
        for p in group.get("Parameters", []):
            if p.get("Parameter ID") == "title blob":
                blob = p.get("Title HTML", "")
                paras = re.findall(r"<p[^>]*>(.*?)</p>", blob, re.DOTALL)
                lines = []
                for para in paras:
                    spans = re.findall(r"<span[^>]*>(.*?)</span>", para, re.DOTALL)
                    text = "".join(spans) if spans else para
                    text = re.sub(r"<[^>]+>", "", text)
                    lines.append(html.unescape(text).strip())
                lines = [ln for ln in lines if ln]
                if lines:
                    return "\n".join(lines)
    return clip.get("name", "") or ""


def flatten(track: dict, rate: float) -> list:
    """
    Walk a track's children and return placed clips.

    Returns a list of dicts: start (frames on the timeline), duration, src_start
    (in-point in the media), url, name, clip.
    """
    out, cursor = [], 0
    for child in track.get("children", []):
        dur = child["source_range"]["duration"]["value"]
        if is_clip(child):
            out.append({
                "start":     cursor,
                "duration":  dur,
                "src_start": child["source_range"]["start_time"]["value"],
                "url":       clip_url(child),
                "name":      child.get("name", "") or "Clip",
                "clip":      child,
            })
        cursor += dur
    return out


def track_rate(track: dict) -> float:
    for c in track.get("children", []):
        return c["source_range"]["duration"]["rate"]
    return 0.0


def tracks_match(a: dict, b: dict) -> bool:
    """True when two tracks are frame-identical mirrors of each other."""
    ca, cb = a.get("children", []), b.get("children", [])
    if len(ca) != len(cb):
        return False
    for x, y in zip(ca, cb):
        if x["source_range"] != y["source_range"]:
            return False
        if clip_url(x) != clip_url(y):
            return False
    return True


# ─── FCPXML building ──────────────────────────────────────────────────────────

class FCPXMLBuilder:
    def __init__(self, rate: float, version: str, width: int, height: int):
        self.rate     = rate
        self.version  = version
        self.width    = width
        self.height   = height
        self.assets   = {}          # url -> {id, name, is_image, duration}
        self.next_id  = 2           # r1 is the format
        self.need_title_effect = False

    def asset_id(self, url: str, name: str, frames: float) -> str:
        """Register a media file, growing its recorded duration as needed."""
        if url not in self.assets:
            ext = Path(url.replace("\\", "/")).suffix.lower()
            self.assets[url] = {
                "id":       f"r{self.next_id}",
                "name":     name or Path(url.replace('\\', '/')).name,
                "is_image": ext in IMAGE_EXTS,
                "frames":   frames,
            }
            self.next_id += 1
        else:
            self.assets[url]["frames"] = max(self.assets[url]["frames"], frames)
        return self.assets[url]["id"]

    # ── resources ─────────────────────────────────────────────────────────
    def resources_xml(self) -> str:
        fd = frame_duration(self.rate)
        lines = ["  <resources>"]
        lines.append(
            f'    <format id="r1" name="FFVideoFormat{self.height}p{int(round(self.rate))}" '
            f'frameDuration="{fd}" width="{self.width}" height="{self.height}" '
            f'colorSpace="1-1-1 (Rec. 709)"/>'
        )
        for url, a in self.assets.items():
            src = file_url(url)
            if a["is_image"]:
                # Stills are durationless in FCPXML; "0s" means "as long as needed".
                lines.append(
                    f'    <asset id="{a["id"]}" name={quoteattr(a["name"])} '
                    f'start="0s" duration="0s" hasVideo="1" videoSources="1" '
                    f'format="r1">'
                )
            else:
                dur = tval(a["frames"], self.rate)
                lines.append(
                    f'    <asset id="{a["id"]}" name={quoteattr(a["name"])} '
                    f'start="0s" duration="{dur}" hasVideo="1" videoSources="1" '
                    f'hasAudio="1" audioSources="1" audioChannels="2" '
                    f'audioRate="48000" format="r1">'
                )
            lines.append(f'      <media-rep kind="original-media" src="{src}"/>')
            lines.append("    </asset>")

        if self.need_title_effect:
            lines.append(
                f'    <effect id="rTitle" name="Basic Title" '
                f'uid={quoteattr(TITLE_EFFECT_UID)}/>'
            )
        lines.append("  </resources>")
        return "\n".join(lines)

    # ── connected items ───────────────────────────────────────────────────
    def video_xml(self, item: dict, lane: int, offset_f: float, indent: str) -> str:
        aid = self.asset_id(item["url"], item["name"], item["duration"])
        return (
            f'{indent}<video ref="{aid}" lane="{lane}" '
            f'offset="{tval(offset_f, self.rate)}" '
            f'name={quoteattr(item["name"])} start="0s" '
            f'duration="{tval(item["duration"], self.rate)}"/>'
        )

    def title_xml(self, item: dict, lane: int, offset_f: float,
                  idx: int, indent: str) -> str:
        self.need_title_effect = True
        text = caption_text(item["clip"])
        sid  = f"ts{idx}"
        return (
            f'{indent}<title ref="rTitle" lane="{lane}" '
            f'offset="{tval(offset_f, self.rate)}" '
            f'name={quoteattr(text.replace(chr(10), " ")[:60] or "Text")} '
            f'start="0s" duration="{tval(item["duration"], self.rate)}">\n'
            f'{indent}  <text>\n'
            f'{indent}    <text-style ref="{sid}">{escape(text)}</text-style>\n'
            f'{indent}  </text>\n'
            f'{indent}  <text-style-def id="{sid}">\n'
            f'{indent}    <text-style font="Open Sans" fontSize="64" '
            f'fontFace="Regular" fontColor="1 1 1 1" alignment="center"/>\n'
            f'{indent}  </text-style-def>\n'
            f'{indent}</title>'
        )


# ─── Conversion ───────────────────────────────────────────────────────────────

def convert(otio_path: Path, out_path: Path, version: str,
            no_titles: bool, width: int, height: int) -> bool:
    data = json.loads(otio_path.read_text(encoding="utf-8"))
    tracks = data["tracks"]["children"]

    video_tracks = [t for t in tracks if t.get("kind") == "Video"]
    audio_tracks = [t for t in tracks if t.get("kind") == "Audio"]

    if not video_tracks:
        print(f"  [ERROR] {otio_path.name}: no video tracks", file=sys.stderr)
        return False

    base = video_tracks[0]
    rate = track_rate(base) or 60.0

    builder = FCPXMLBuilder(rate, version, width, height)

    spine_items = flatten(base, rate)
    total = sum(c["source_range"]["duration"]["value"] for c in base["children"])

    # Does the audio simply mirror the edit?  Then asset-clips carry it.
    audio_folded = bool(audio_tracks) and tracks_match(base, audio_tracks[0])
    if audio_tracks and not audio_folded:
        print(f"  [WARN] audio track is not a mirror of the video track - "
              f"writing it as connected clips on lane -1")

    # Overlays: every video track above the first.
    overlays = []
    for i, t in enumerate(video_tracks[1:], start=1):
        items = flatten(t, rate)
        is_caption = any(
            (c["clip"].get("media_references", {})
              .get("DEFAULT_MEDIA", {})
              .get("OTIO_SCHEMA", "")).startswith("GeneratorReference")
            for c in items[:1]
        )
        if is_caption and no_titles:
            print(f"  [skip] {t.get('name')} (captions, --no-titles)")
            continue
        overlays.append({"lane": i, "items": items, "captions": is_caption,
                         "name": t.get("name")})

    # Register spine media up front so ids come out in a stable order.
    for it in spine_items:
        builder.asset_id(it["url"], it["name"], it["src_start"] + it["duration"])

    # Attach each overlay item to the spine clip it starts over.
    attach = {i: [] for i in range(len(spine_items))}
    orphan = 0
    for ov in overlays:
        for n, item in enumerate(ov["items"]):
            host = None
            for i, s in enumerate(spine_items):
                if s["start"] <= item["start"] < s["start"] + s["duration"]:
                    host = i
                    break
            if host is None:
                host = len(spine_items) - 1
                orphan += 1
            attach[host].append((ov, item, n))

    if orphan:
        print(f"  [WARN] {orphan} overlay clip(s) start past the end of the edit; "
              f"attached to the last clip")

    # ── Emit ──────────────────────────────────────────────────────────────
    spine_lines = []
    for i, s in enumerate(spine_items):
        aid = builder.asset_id(s["url"], s["name"], s["src_start"] + s["duration"])
        open_tag = (
            f'          <asset-clip ref="{aid}" '
            f'offset="{tval(s["start"], rate)}" '
            f'name={quoteattr(s["name"])} '
            f'start="{tval(s["src_start"], rate)}" '
            f'duration="{tval(s["duration"], rate)}" '
            f'format="r1" tcFormat="NDF"'
        )
        kids = attach[i]
        if not kids:
            spine_lines.append(open_tag + "/>")
            continue

        spine_lines.append(open_tag + ">")
        for ov, item, n in kids:
            # A connected clip's offset lives in its parent's local time.
            local = s["src_start"] + (item["start"] - s["start"])
            if ov["captions"]:
                spine_lines.append(
                    builder.title_xml(item, ov["lane"], local, n, "            "))
            else:
                spine_lines.append(
                    builder.video_xml(item, ov["lane"], local, "            "))
        spine_lines.append("          </asset-clip>")

    project_name = data.get("name") or otio_path.stem

    body = "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<!DOCTYPE fcpxml>',
        f'<fcpxml version="{version}">',
        builder.resources_xml(),
        '  <library>',
        f'    <event name={quoteattr(project_name)}>',
        f'      <project name={quoteattr(project_name)}>',
        f'        <sequence format="r1" duration="{tval(total, rate)}" '
        f'tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">',
        '          <spine>',
        "\n".join(spine_lines),
        '          </spine>',
        '        </sequence>',
        '      </project>',
        '    </event>',
        '  </library>',
        '</fcpxml>',
        '',
    ])

    out_path.write_text(body, encoding="utf-8")

    n_titles = sum(len(o["items"]) for o in overlays if o["captions"])
    n_videos = sum(len(o["items"]) for o in overlays if not o["captions"])
    print(f"  [OK] {out_path.name}")
    print(f"       {len(spine_items)} spine clips, {n_videos} connected videos, "
          f"{n_titles} titles, {len(builder.assets)} assets")
    print(f"       {out_path.stat().st_size / 1024:,.1f} KB")
    return True


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Convert the final OTIO timelines to Resolve .fcpxml.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python OTIOtoFCPXML.py
  python OTIOtoFCPXML.py --version 1.10
  python OTIOtoFCPXML.py --no-titles
  python OTIOtoFCPXML.py FinalTimelineWithCap.otio -o custom.fcpxml
        """
    )
    ap.add_argument("inputs", nargs="*",
                    help="OTIO files to convert (default: the two 06_Final timelines)")
    ap.add_argument("-o", "--output",
                    help="Output path (only valid with a single input)")
    ap.add_argument("--version", default="1.9",
                    help="FCPXML version to declare (default: 1.9)")
    ap.add_argument("--no-titles", dest="no_titles", action="store_true",
                    help="Leave the caption track out of the FCPXML")
    ap.add_argument("--width",  type=int, default=1920, help="Frame width (default 1920)")
    ap.add_argument("--height", type=int, default=1080, help="Frame height (default 1080)")
    args = ap.parse_args()

    inputs = [Path(p) for p in args.inputs] if args.inputs else list(DEFAULT_INPUTS)

    if args.output and len(inputs) != 1:
        print("[ERROR] -o only works with a single input file", file=sys.stderr)
        sys.exit(1)

    print(f"  FCPXML version : {args.version}")
    print(f"  frame size     : {args.width}x{args.height}")
    print()

    ok = 0
    for src in inputs:
        if not src.exists():
            print(f"  [MISS] {src.name} - not found, skipping")
            continue
        print(f"Converting {src.name} ...")
        out = Path(args.output) if args.output else src.with_suffix(".fcpxml")
        try:
            if convert(src, out, args.version, args.no_titles,
                       args.width, args.height):
                ok += 1
        except Exception as e:
            print(f"  [ERROR] {src.name}: {e}", file=sys.stderr)
        print()

    if ok == 0:
        print("[ERROR] Nothing was converted - run A_CombineFinalTimelines.bat first.",
              file=sys.stderr)
        sys.exit(1)

    print(f"Done - {ok} file(s) written.")
    print("Import into Resolve with:  File > Import > Timeline > Import AAF, EDL, XML...")


if __name__ == "__main__":
    main()
