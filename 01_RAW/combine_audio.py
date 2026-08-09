import os
import sys
import subprocess

# ─────────────────────────────────────────────
# CONFIG — must match isolate_voice.py
# ─────────────────────────────────────────────
VOICE_FILE    = "COMPILED_AUDIO.mp3"     # isolated + leveled voice
BG_FILE       = "COMPILED_BGAUDIO.mp3"   # everything else
COMBINED_FILE = "COMBINED_AUDIO.mp3"     # the two mixed back together

AUDIO_BITRATE = "320k"
# ─────────────────────────────────────────────


def main():
    currentpath = os.path.dirname(os.path.abspath(__file__))
    print("currentpath : " + currentpath)

    voice_path    = os.path.join(currentpath, VOICE_FILE)
    bg_path       = os.path.join(currentpath, BG_FILE)
    combined_path = os.path.join(currentpath, COMBINED_FILE)

    dry_run = "--dry-run" in sys.argv

    missing = [f for f, p in [(VOICE_FILE, voice_path), (BG_FILE, bg_path)]
               if not os.path.exists(p)]
    if missing:
        print(f"[ERROR] missing: {', '.join(missing)}")
        print(f"        Run B_RunThisToIsolateAndLevelVoice.bat first.")
        sys.exit(1)

    # amix's default normalize=1 blindly halves amplitude for a 2-input mix
    # NO MATTER how loud each input actually is -- so a quiet background
    # track still drags the already-leveled voice down with it (measured:
    # voice alone -15.3 LUFS -> naive amix -21.4 LUFS, undoing the leveling
    # step). normalize=0 skips that, then loudnorm re-levels the finished
    # mix properly (true-peak aware, so it won't clip), landing the combined
    # track at the same target the voice alone was leveled to.
    cmd = [
        "ffmpeg", "-y",
        "-i", voice_path,
        "-i", bg_path,
        "-filter_complex",
        "[0:a][1:a]amix=inputs=2:duration=longest:normalize=0,"
        "loudnorm=I=-14:TP=-1.5:LRA=7",
        "-c:a", "libmp3lame", "-b:a", AUDIO_BITRATE,
        combined_path,
    ]

    print("\nCombining voice + background...")
    print("  $ " + " ".join(cmd))
    if dry_run:
        print("  (dry run - not actually running)")
        return

    result = subprocess.run(cmd)
    if result.returncode != 0 or not os.path.exists(combined_path):
        print(f"[ERROR] ffmpeg failed (exit {result.returncode}).")
        sys.exit(1)

    print()
    print(f"[OK] {COMBINED_FILE} written.")
    print(f"     Next: D_RunThisToReplaceAudio.bat")


if __name__ == "__main__":
    main()
