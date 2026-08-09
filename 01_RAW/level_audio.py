import os
import sys
import subprocess

# ─────────────────────────────────────────────
# CONFIG — tweak these as needed
# ─────────────────────────────────────────────
VIDEO_FILE         = "COMPILED_VIDEO.mp4"             # output of A_RunThisToCompileMP4.bat
BACKUP_FILE        = "COMPILED_VIDEO.original.mp4"    # untouched copy, made by replace_audio.py
LEVELED_AUDIO_FILE = "COMPILED_VIDEO.leveled_audio.m4a"

# Same idea as Audacity's Compressor, translated to ffmpeg's compand filter:
# quiet talkers get pulled up, loud spikes get pulled down, so everyone sits
# at roughly the same level before loudnorm does the final overall pass.
#   attacks/decays : how fast the gain reacts (seconds)
#   points         : input_dB/output_dB pairs describing the curve
#   gain           : flat makeup gain after companding, in dB
AUDIO_FILTER = (
    "compand=attacks=0.01:decays=0.5:"
    "points=-80/-80|-55/-40|-35/-12|-20/-6|-10/-4|0/-2:gain=8,"
    "loudnorm=I=-14:TP=-1.5:LRA=7"
)

AUDIO_CODEC   = "aac"
AUDIO_BITRATE = "320k"
# ─────────────────────────────────────────────


def main():
    currentpath = os.path.dirname(os.path.abspath(__file__))
    print("currentpath : " + currentpath)

    video_path  = os.path.join(currentpath, VIDEO_FILE)
    backup_path = os.path.join(currentpath, BACKUP_FILE)
    out_path    = os.path.join(currentpath, LEVELED_AUDIO_FILE)

    dry_run = "--dry-run" in sys.argv

    # Read from the untouched backup if C_RunThisToReplaceAudio.bat has
    # already run once and made one; otherwise read straight from
    # COMPILED_VIDEO.mp4, which is still untouched at that point.  Either
    # way this only ever reads ORIGINAL audio, never audio this same script
    # already leveled -- so running this again and again, in any order
    # relative to the replace step, never compounds the effect.
    if os.path.exists(backup_path):
        source_path = backup_path
        print(f"Reading from the untouched backup: {BACKUP_FILE}")
    elif os.path.exists(video_path):
        source_path = video_path
        print(f"Reading from {VIDEO_FILE} (no backup yet - "
              f"C_RunThisToReplaceAudio.bat hasn't run on this project).")
    else:
        print(f"[ERROR] Neither {VIDEO_FILE} nor {BACKUP_FILE} found in "
              f"{currentpath}")
        print(f"        Run A_RunThisToCompileMP4.bat first.")
        sys.exit(1)

    cmd = [
        "ffmpeg", "-y",
        "-i", source_path,
        "-vn",
        "-af", AUDIO_FILTER,
        "-c:a", AUDIO_CODEC,
        "-b:a", AUDIO_BITRATE,
        out_path,
    ]

    print()
    print("Leveling audio (compand + loudnorm)...")
    print("  $ " + " ".join(cmd))
    if dry_run:
        print("  (dry run - not actually running)")
        return

    result = subprocess.run(cmd)
    if result.returncode != 0 or not os.path.exists(out_path):
        print(f"[ERROR] ffmpeg failed (exit {result.returncode}).")
        sys.exit(1)

    print()
    print(f"[OK] Leveled audio written to {LEVELED_AUDIO_FILE}")
    print(f"     {VIDEO_FILE} itself is UNTOUCHED - this only made a "
          f"standalone audio file.")
    print(f"     Not happy with it? Tweak AUDIO_FILTER above and run this "
          f"again - it always re-levels from the original, never stacks.")
    print(f"     To put it into the video: "
          f"C_RunThisToReplaceAudio.bat")


if __name__ == "__main__":
    main()
