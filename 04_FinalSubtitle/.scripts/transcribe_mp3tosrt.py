import os
import subprocess
import re
import argparse

# ── CONFIG ────────────────────────────────────────────────────
WHISPER_BIN   = os.path.expanduser(r"~\whisper.cpp\whisper-cli.exe")
WHISPER_MODEL = os.path.expanduser(r"~\whisper.cpp\models\ggml-large-v3.bin")
VAD_MODEL     = os.path.expanduser(r"~\whisper.cpp\models\ggml-silero-v6.2.0.bin")
REPEAT_THRESHOLD = 5   # how many repeats before we consider it a loop
# ─────────────────────────────────────────────────────────────

# ── PARSE ARGS ───────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("mp3",  nargs="?", help="path to a specific .mp3 to transcribe")
parser.add_argument("dest", nargs="?", help="output .srt path or folder (default: cwd)")
args = parser.parse_args()
# ─────────────────────────────────────────────────────────────

currentpath = os.getcwd()
print("currentpath : " + currentpath)

# ── BUILD FILE LIST ──────────────────────────────────────────
if args.mp3:
    # single-file mode
    rawpath = os.path.dirname(os.path.abspath(args.mp3))
    mp3files = [os.path.basename(args.mp3)]

    if args.dest:
        dest_abs = os.path.abspath(args.dest)
        if dest_abs.lower().endswith(".srt"):
            # full srt path provided → use it directly as srtbase
            srt_dest_file = dest_abs.replace(".srt", "").replace(".SRT", "")
            srt_dest = os.path.dirname(dest_abs)
        else:
            # folder provided → derive srt name from mp3 name
            srt_dest_file = None
            srt_dest = dest_abs
    else:
        srt_dest_file = None
        srt_dest = currentpath

    print("single file mode : " + args.mp3)
    print("srt_dest         : " + srt_dest)

else:
    # auto-discovery mode (original behaviour)
    spl = currentpath.split("\\")[-1]
    destinationpath = currentpath.split(spl)[0]
    rawpath = destinationpath + "01_RAW"
    mp3files = [f for f in os.listdir(rawpath) if f.endswith(".mp3") or f.endswith(".MP3")]
    srt_dest = currentpath
    srt_dest_file = None
    print("destinationpath : " + destinationpath)
    print("rawpath         : " + rawpath)

print("mp3files found : " + str(len(mp3files)))
print("")
for mp3 in mp3files:
    print("  mp3 : " + mp3)
print("")
# ─────────────────────────────────────────────────────────────


def srt_timestamp_to_ms(ts):
    ts = ts.replace(",", ".")
    h, m, s = ts.split(":")
    return int(h) * 3600000 + int(m) * 60000 + int(float(s) * 1000)


def ms_to_srt_timestamp(ms):
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def find_loop_start(srtfile):
    print("checking for hallucination loop in : " + srtfile)

    if not os.path.exists(srtfile):
        print("srt not found : " + srtfile)
        return None

    lines = open(srtfile, encoding="utf-8").readlines()

    entries = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if re.match(r"^\d+$", line):
            if i + 2 < len(lines):
                timecodes = lines[i + 1].strip()
                text = lines[i + 2].strip()
                match = re.match(r"(\d+:\d+:\d+,\d+) --> (\d+:\d+:\d+,\d+)", timecodes)
                if match:
                    start_ms = srt_timestamp_to_ms(match.group(1))
                    entries.append((start_ms, text))
        i += 1

    for i in range(len(entries) - REPEAT_THRESHOLD):
        texts = [entries[i + j][1] for j in range(REPEAT_THRESHOLD)]
        if len(set(texts)) == 1:
            loop_start_ms = entries[i][0]
            print("loop detected at : " + ms_to_srt_timestamp(loop_start_ms) + " → \"" + entries[i][1] + "\"")
            return loop_start_ms, i

    print("no loop detected, transcript looks clean!")
    return None


def trim_audio(mp3path, start_ms, trimmed_path):
    start_sec = start_ms / 1000.0
    print("trimming audio from : " + str(start_sec) + "s → " + trimmed_path)

    cmd = [
        "ffmpeg", "-y",
        "-i", mp3path,
        "-ss", str(start_sec),
        "-c", "copy",
        trimmed_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("ffmpeg trim failed : " + result.stderr)
        return False

    print("trim done : " + trimmed_path)
    return True


def shift_srt_timestamps(srtfile, offset_ms):
    print("shifting part2 timestamps by : " + str(offset_ms) + "ms")

    content = open(srtfile, encoding="utf-8").read()

    def shift_match(match):
        start = srt_timestamp_to_ms(match.group(1)) + offset_ms
        end   = srt_timestamp_to_ms(match.group(2)) + offset_ms
        return ms_to_srt_timestamp(start) + " --> " + ms_to_srt_timestamp(end)

    shifted = re.sub(
        r"(\d+:\d+:\d+,\d+) --> (\d+:\d+:\d+,\d+)",
        shift_match,
        content
    )

    open(srtfile, "w", encoding="utf-8").write(shifted)
    print("timestamps shifted!")


def run_whisper(audiopath, srtbase):
    cmd = [
        WHISPER_BIN,
        "-m", WHISPER_MODEL,
        "-f", audiopath,
        "-of", srtbase,
        "-osrt",
        "-l", "auto",
        "-t", "12",
        "--entropy-thold", "2.4",
        "--logprob-thold", "-1.0",
        "--vad",
        "--vad-model", VAD_MODEL,
    ]

    result = subprocess.run(cmd)
    return result.returncode


def merge_srts(srt_first, first_line_cutoff, srt_second, srt_final):
    print("merging srts...")

    blocks_first  = open(srt_first,  encoding="utf-8").read().strip().split("\n\n")
    blocks_second = open(srt_second, encoding="utf-8").read().strip().split("\n\n")

    clean_blocks = blocks_first[:first_line_cutoff]
    all_blocks   = clean_blocks + blocks_second

    final_lines = []
    for idx, block in enumerate(all_blocks):
        block_lines = block.strip().split("\n")
        if len(block_lines) >= 2:
            block_lines[0] = str(idx + 1)
            final_lines.append("\n".join(block_lines))

    open(srt_final, "w", encoding="utf-8").write("\n\n".join(final_lines) + "\n")
    print("merged srt written : " + srt_final)


# ── MAIN LOOP ─────────────────────────────────────────────────
for mp3 in mp3files:
    mp3path = rawpath + "\\" + mp3
    print("\n--- processing : " + mp3path)

    # build srtbase — respects explicit dest path or derives from mp3 name
    if srt_dest_file:
        srtbase = srt_dest_file
    else:
        mp3_noext = mp3.replace(".mp3", "").replace(".MP3", "")
        srtbase = srt_dest + "\\" + mp3_noext

    srtfile = srtbase + ".srt"
    print("srtbase : " + srtbase)

    # ── PASS 1: normal transcription ────────────────────────
    print("pass 1 : running whisper...")
    code = run_whisper(mp3path, srtbase)

    if code != 0:
        print("failed on pass 1 : " + mp3)
        continue

    print("pass 1 done : " + srtfile)

    # ── CHECK: did it loop? ──────────────────────────────────
    result = find_loop_start(srtfile)

    if result is None:
        print("all good, no retry needed!")
        continue

    loop_start_ms, loop_line_idx = result

    # ── TRIM: cut audio from loop point using ffmpeg ─────────
    trimmed_mp3 = mp3path.replace(".mp3", "_trimmed.mp3").replace(".MP3", "_trimmed.MP3")
    trim_ok = trim_audio(mp3path, loop_start_ms, trimmed_mp3)

    if not trim_ok:
        print("trim failed, skipping pass 2")
        continue

    # ── PASS 2: whisper on trimmed audio ─────────────────────
    srtbase_part2 = srtbase + "_part2"
    srtfile_part2 = srtbase_part2 + ".srt"

    print("pass 2 : running whisper on trimmed audio...")
    code2 = run_whisper(trimmed_mp3, srtbase_part2)

    if code2 != 0:
        print("failed on pass 2 : " + mp3)
        os.remove(trimmed_mp3)
        continue

    print("pass 2 done : " + srtfile_part2)

