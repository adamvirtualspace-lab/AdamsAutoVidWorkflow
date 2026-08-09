import os
import shutil
import subprocess
import sys
import tempfile

# ─────────────────────────────────────────────
# CONFIG — tweak these as needed
# ─────────────────────────────────────────────
VIDEO_FILE  = "COMPILED_VIDEO.mp4"
BACKUP_FILE = "COMPILED_VIDEO.original.mp4"   # untouched copy, made by replace_audio.py

VOICE_FILE  = "COMPILED_AUDIO.mp3"    # isolated + leveled voice -> what 02_RawSubtitles transcribes
BG_FILE     = "COMPILED_BGAUDIO.mp3"  # everything else: music, ambience, game sfx

DEMUCS_MODEL = "htdemucs"   # Meta's general-purpose 4-stem model, used here in
                            # --two-stems=vocals mode (vocals vs. everything else)

# Same idea as Audacity's Compressor, applied to the ISOLATED VOICE ONLY --
# this is what actually made transcription better: whisper hears a clean,
# evenly-leveled voice with no music/effects fighting for its attention.
#   attacks/decays : how fast the gain reacts (seconds)
#   points         : input_dB/output_dB pairs describing the curve
#   gain           : flat makeup gain after companding, in dB
VOICE_FILTER = (
    "compand=attacks=0.01:decays=0.5:"
    "points=-80/-80|-55/-40|-35/-12|-20/-6|-10/-4|0/-2:gain=8,"
    "loudnorm=I=-14:TP=-1.5:LRA=7"
)

AUDIO_BITRATE = "320k"
# ─────────────────────────────────────────────


def run(cmd):
    print("  $ " + " ".join(cmd))
    return subprocess.run(cmd)


def pick_device():
    """cuda if torch sees a GPU, else cpu. Demucs is MUCH faster on a GPU."""
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            print(f"  GPU found: {name} - using CUDA")
            return "cuda"
    except ImportError:
        pass
    print("  no GPU available to torch - using CPU (this will be slower)")
    return "cpu"


def main():
    currentpath = os.path.dirname(os.path.abspath(__file__))
    print("currentpath : " + currentpath)

    video_path  = os.path.join(currentpath, VIDEO_FILE)
    backup_path = os.path.join(currentpath, BACKUP_FILE)
    voice_path  = os.path.join(currentpath, VOICE_FILE)
    bg_path     = os.path.join(currentpath, BG_FILE)

    dry_run = "--dry-run" in sys.argv

    # Isolate from the untouched backup if D_RunThisToReplaceAudio.bat has
    # already run once (so we're re-isolating, not isolating our own
    # previously-combined mix back out of itself); otherwise from
    # COMPILED_VIDEO.mp4 directly, which is still untouched at that point.
    if os.path.exists(backup_path):
        source_video = backup_path
        print(f"Reading from the untouched backup: {BACKUP_FILE}")
    elif os.path.exists(video_path):
        source_video = video_path
        print(f"Reading from {VIDEO_FILE} (no backup yet - "
              f"D_RunThisToReplaceAudio.bat hasn't run on this project).")
    else:
        print(f"[ERROR] Neither {VIDEO_FILE} nor {BACKUP_FILE} found in "
              f"{currentpath}")
        print(f"        Run A_RunThisToCompileMP4.bat first.")
        sys.exit(1)

    if dry_run:
        print("\n(dry run - showing the plan, not running it)")
        print(f"  1. extract audio from {os.path.basename(source_video)} to a temp wav")
        print(f"  2. demucs --two-stems=vocals -> vocals.wav + no_vocals.wav")
        print(f"  3. filter vocals.wav ({VOICE_FILTER}) -> {VOICE_FILE}")
        print(f"  4. no_vocals.wav as-is -> {BG_FILE}")
        return

    tmp_dir = tempfile.mkdtemp(prefix="adam_isolate_")
    extracted_wav = os.path.join(tmp_dir, "extracted.wav")

    try:
        # ── 1. Extract the full audio track to an uncompressed wav ──────
        # Demucs works from an audio file, and a lossless intermediate here
        # avoids stacking mp3 artifacts before separation even happens.
        print("\nExtracting audio...")
        r = run(["ffmpeg", "-y", "-i", source_video, "-vn",
                 "-ar", "44100", "-ac", "2", extracted_wav])
        if r.returncode != 0 or not os.path.exists(extracted_wav):
            print(f"[ERROR] audio extraction failed (exit {r.returncode}).")
            sys.exit(1)

        # ── 2. Demucs: split into vocals vs. everything else ────────────
        print("\nSeparating voice from background (this is the slow part)...")
        device = pick_device()
        demucs_out = os.path.join(tmp_dir, "separated")
        r = run([
            sys.executable, "-m", "demucs",
            "--two-stems", "vocals",
            "-n", DEMUCS_MODEL,
            "-d", device,
            "-o", demucs_out,
            extracted_wav,
        ])
        if r.returncode != 0:
            print(f"[ERROR] demucs failed (exit {r.returncode}).")
            sys.exit(1)

        stem_dir = os.path.join(demucs_out, DEMUCS_MODEL, "extracted")
        vocals_wav    = os.path.join(stem_dir, "vocals.wav")
        no_vocals_wav = os.path.join(stem_dir, "no_vocals.wav")

        if not os.path.exists(vocals_wav) or not os.path.exists(no_vocals_wav):
            print(f"[ERROR] demucs didn't produce the expected files in "
                  f"{stem_dir}")
            sys.exit(1)

        # ── 3. Level the voice stem, export as VOICE_FILE ────────────────
        print(f"\nLeveling the voice stem -> {VOICE_FILE}")
        r = run(["ffmpeg", "-y", "-i", vocals_wav, "-af", VOICE_FILTER,
                 "-c:a", "libmp3lame", "-b:a", AUDIO_BITRATE, voice_path])
        if r.returncode != 0 or not os.path.exists(voice_path):
            print(f"[ERROR] leveling the voice stem failed (exit {r.returncode}).")
            sys.exit(1)

        # ── 4. Export the background stem as-is ──────────────────────────
        print(f"\nExporting the background stem -> {BG_FILE}")
        r = run(["ffmpeg", "-y", "-i", no_vocals_wav,
                 "-c:a", "libmp3lame", "-b:a", AUDIO_BITRATE, bg_path])
        if r.returncode != 0 or not os.path.exists(bg_path):
            print(f"[ERROR] exporting the background stem failed (exit {r.returncode}).")
            sys.exit(1)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print()
    print(f"[OK] {VOICE_FILE}  - isolated + leveled voice (for transcription)")
    print(f"[OK] {BG_FILE}  - everything else (music, ambience, sfx)")
    print(f"     {VIDEO_FILE} itself is UNTOUCHED - these are standalone audio files.")
    print(f"     Not happy with the level? Tweak VOICE_FILTER above and run this "
          f"again - it always re-isolates from the original, never stacks.")
    print(f"     Next: C_RunThisToCombineAudio.bat")


if __name__ == "__main__":
    main()
