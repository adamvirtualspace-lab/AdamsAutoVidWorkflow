import os
import subprocess

# ─────────────────────────────────────────────
# CONFIG — tweak these as needed
# ─────────────────────────────────────────────
OUTPUT_FPS         = 60          # target framerate (fixes variable framerate from gameplay capture)
OUTPUT_VIDEO_FILE  = "COMPILED_VIDEO.mp4"
OUTPUT_AUDIO_FILE  = "COMPILED_AUDIO.wav"
# ─────────────────────────────────────────────


# ── 1. WHERE ARE WE? ─────────────────────────

# Use the folder where this .py script lives, not wherever you call it from
currentpath = os.path.dirname(os.path.abspath(__file__))
print("currentpath : " + currentpath)


# ── 2. FIND ALL .MP4 FILES ───────────────────

all_files = os.listdir(currentpath)
mp4_files = [f for f in all_files if f.lower().endswith(".mp4")]
mp4_files.sort()  # alphabetical order

print("\nFound " + str(len(mp4_files)) + " .mp4 file(s):")
for f in mp4_files:
    print("  " + f)

if len(mp4_files) == 0:
    print("\nNo .mp4 files found. Exiting.")
    exit()


# ── 3. BUILD FFMPEG CONCAT LIST ──────────────

# ffmpeg concat demuxer needs a text file listing all input clips
concat_list_path = os.path.join(currentpath, "_concat_list.txt")

with open(concat_list_path, "w", encoding="utf-8") as concat_file:
    for mp4 in mp4_files:
        full_mp4_path = os.path.join(currentpath, mp4)
        # ffmpeg wants forward slashes and the path wrapped in single quotes
        safe_path = full_mp4_path.replace("\\", "/")
        concat_file.write("file '" + safe_path + "'\n")

print("\nWrote concat list to : " + concat_list_path)


# ── 4. COMPILE + TRANSCODE VIDEO ─────────────

output_video_path = os.path.join(currentpath, OUTPUT_VIDEO_FILE)

# What we're doing here and why:
#   -f concat -safe 0        → use the concat demuxer with our list file
#   -vf fps=OUTPUT_FPS       → force constant framerate (fixes VFR gameplay recordings)
#   -c:v libx264             → H.264 — widely supported editing format
#   -preset slow             → better compression, still compatible everywhere
#   -crf 18                  → near-lossless quality (0 = lossless, 23 = default, 18 = very good)
#   -pix_fmt yuv420p         → makes it compatible with more editors (Resolve, Premiere, etc)
#   -c:a aac -b:a 320k       → AAC audio at high bitrate, safe for most editors
#   -movflags +faststart     → puts metadata at start of file (good for streaming/preview)

ffmpeg_video_command = [
    "ffmpeg",
    "-y",                           # overwrite output if it already exists
    "-f", "concat",
    "-safe", "0",
    "-i", concat_list_path,
    "-vf", "fps=" + str(OUTPUT_FPS),
    "-c:v", "libx264",
    "-preset", "slow",
    "-crf", "18",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-b:a", "320k",
    "-movflags", "+faststart",
    output_video_path
]

print("\nRunning ffmpeg — compile + transcode video...")
print("Output : " + output_video_path)
print("(This may take a while depending on total clip length)\n")

subprocess.run(ffmpeg_video_command, check=True)

print("\nVideo compile done!")


# ── 5. EXTRACT AUDIO FROM THE COMPILED VIDEO ─

output_audio_path = os.path.join(currentpath, OUTPUT_AUDIO_FILE)

# Extract as uncompressed WAV — best for further audio editing/processing
ffmpeg_audio_command = [
    "ffmpeg",
    "-y",
    "-i", output_video_path,
    "-vn",              # no video
    "-c:a", "pcm_s16le",  # uncompressed 16-bit PCM WAV
    output_audio_path
]

print("\nRunning ffmpeg — extracting audio...")
print("Output : " + output_audio_path)

subprocess.run(ffmpeg_audio_command, check=True)

print("\nAudio extract done!")


# ── 6. CLEANUP ────────────────────────────────

os.remove(concat_list_path)
print("\nCleaned up temp file : " + concat_list_path)


# ── 7. SUMMARY ───────────────────────────────

print("\n─────────────────────────────────────────")
print("ALL DONE")
print("  Clips compiled : " + str(len(mp4_files)))
print("  Video output   : " + output_video_path)
print("  Audio output   : " + output_audio_path)
print("─────────────────────────────────────────")
