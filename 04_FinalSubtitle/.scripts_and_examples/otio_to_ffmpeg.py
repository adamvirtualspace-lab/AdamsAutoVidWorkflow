import os
import json
import subprocess

currentpath = os.path.dirname(os.path.abspath(__file__))
print("currentpath : " + currentpath)

spl = currentpath.split("\\")[-1]
basepathspl = currentpath.split("\\")[-2]
basepath = currentpath.split(basepathspl)[0]
print("basepath : " + basepath)

otiopath = basepath + "03_EditPlanToOtio\\"
otiofile = next(os.path.join(r, f) for r, d, files in os.walk(otiopath) for f in files if f.endswith('.otio'))
print("otiofile : " + otiofile)

destinationconcat = currentpath + "\\03_EditPlanToOtio.concat"
destinationaudio  = currentpath + "\\03_EditPlanToOtio.MP3"
print("destinationconcat : " + destinationconcat)
print("destinationaudio  : " + destinationaudio)
print(" ")

# ── Parse OTIO ───────────────────────────────────────────────────────
with open(otiofile, "r", encoding="utf-8") as f:
    otio_data = json.load(f)

clips = []
for track in otio_data["tracks"]["children"]:
    if track.get("kind") != "Video":
        continue
    for clip in track.get("children", []):
        media_refs = clip.get("media_references", {})
        target_url = media_refs.get("DEFAULT_MEDIA", {}).get("target_url", "")
        source_range = clip.get("source_range", {})
        rate     = source_range["start_time"]["rate"]
        start    = source_range["start_time"]["value"]
        duration = source_range["duration"]["value"]
        inpoint  = start / rate
        outpoint = (start + duration) / rate
        clips.append({
            "file"    : target_url,
            "inpoint" : inpoint,
            "outpoint": outpoint
        })
        print("clip : " + target_url + " | in: " + str(round(inpoint, 4)) + "s | out: " + str(round(outpoint, 4)) + "s")

print(" ")
print("total clips : " + str(len(clips)))
print(" ")

# ── Write concat file ────────────────────────────────────────────────
with open(destinationconcat, "w", encoding="utf-8") as f:
    f.write("ffconcat version 1.0\n")
    for clip in clips:
        # forward slashes required by ffmpeg even on Windows
        filepath = clip["file"].replace("\\", "/")
        f.write("file '" + filepath + "'\n")
        f.write("inpoint "  + str(clip["inpoint"])  + "\n")
        f.write("outpoint " + str(clip["outpoint"]) + "\n")

print("concat file written : " + destinationconcat)
print(" ")

# ── FFmpeg: concat → audio ───────────────────────────────────────────
ffmpeg_audio_command = [
    "ffmpeg", "-y",
    "-f", "concat",       # use concat demuxer
    "-safe", "0",         # allow absolute paths
    "-i", destinationconcat,
    "-vn",
    "-c:a", "libmp3lame",
    "-b:a", "320k",
    destinationaudio
]

print("Running FFmpeg...")
print(" ".join(ffmpeg_audio_command))
print(" ")

result = subprocess.run(
    ffmpeg_audio_command,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

if result.returncode == 0:
    print("Done! Audio output : " + destinationaudio)
else:
    print("FFmpeg failed:")
    print(result.stderr)
