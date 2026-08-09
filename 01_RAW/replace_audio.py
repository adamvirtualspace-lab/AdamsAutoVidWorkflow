import os
import shutil
import sys
import subprocess

# ─────────────────────────────────────────────
# CONFIG — must match combine_audio.py
# ─────────────────────────────────────────────
VIDEO_FILE     = "COMPILED_VIDEO.mp4"
BACKUP_FILE    = "COMPILED_VIDEO.original.mp4"  # untouched copy, made here
COMBINED_FILE  = "COMBINED_AUDIO.mp3"           # made by combine_audio.py

AUDIO_BITRATE = "320k"
# ─────────────────────────────────────────────


def main():
    currentpath = os.path.dirname(os.path.abspath(__file__))
    print("currentpath : " + currentpath)

    video_path  = os.path.join(currentpath, VIDEO_FILE)
    backup_path = os.path.join(currentpath, BACKUP_FILE)
    audio_path  = os.path.join(currentpath, COMBINED_FILE)
    tmp_path    = os.path.join(currentpath, "_replace_audio_tmp.mp4")

    revert  = "--revert" in sys.argv
    dry_run = "--dry-run" in sys.argv

    # ── Revert: restore the untouched original video ────────────────────
    if revert:
        if not os.path.exists(backup_path):
            print(f"[ERROR] no backup found at {backup_path} - nothing to revert to.")
            sys.exit(1)
        print(f"Reverting: {BACKUP_FILE} -> {VIDEO_FILE}")
        if not dry_run:
            if os.path.exists(video_path):
                os.remove(video_path)
            shutil.copy2(backup_path, video_path)
        print("Done.")
        return

    if not os.path.exists(audio_path):
        print(f"[ERROR] {COMBINED_FILE} not found in {currentpath}")
        print(f"        Run B_RunThisToIsolateAndLevelVoice.bat then "
              f"C_RunThisToCombineAudio.bat first.")
        sys.exit(1)

    # ── Backup: made once, the first time this runs. Every run after that
    # replaces audio starting from the SAME untouched video, so re-running
    # this after re-leveling the audio just swaps in the new take -- it
    # never layers a replacement onto an already-replaced file. ───────────
    first_run = not os.path.exists(backup_path)
    if first_run:
        if not os.path.exists(video_path):
            print(f"[ERROR] {VIDEO_FILE} not found in {currentpath}")
            print(f"        Run A_RunThisToCompileMP4.bat first.")
            sys.exit(1)
        print(f"First run - moving the untouched original to {BACKUP_FILE}")
        if not dry_run:
            os.rename(video_path, backup_path)
    else:
        print(f"{BACKUP_FILE} already exists - replacing audio on top of "
              f"that untouched copy, not on top of a previous replacement.")

    # ── ffmpeg: video stream is copied untouched (no re-encode, so this is
    # fast regardless of file size); the mp3 gets transcoded to AAC because
    # mp3-in-mp4 is unevenly supported by editors/players downstream, while
    # AAC-in-mp4 is the safe default (it's what the original audio was). ──
    cmd = [
        "ffmpeg", "-y",
        "-i", backup_path,
        "-i", audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", AUDIO_BITRATE,
        "-shortest",
        tmp_path,
    ]

    print()
    print("Replacing audio...")
    print("  $ " + " ".join(cmd))
    if dry_run:
        print("  (dry run - not actually running)")
        return

    result = subprocess.run(cmd)
    if result.returncode != 0 or not os.path.exists(tmp_path):
        print(f"[ERROR] ffmpeg failed (exit {result.returncode}).")
        if first_run:
            print(f"        Restoring {VIDEO_FILE} from the backup so "
                  f"nothing's left half-done.")
            shutil.copy2(backup_path, video_path)
        sys.exit(1)

    if os.path.exists(video_path):
        os.remove(video_path)
    os.rename(tmp_path, video_path)

    print()
    print(f"[OK] {VIDEO_FILE} now has the leveled audio.")
    print(f"     Original preserved at {BACKUP_FILE}.")
    print(f"     To go back to the raw audio: "
          f"python replace_audio.py --revert")


if __name__ == "__main__":
    main()
