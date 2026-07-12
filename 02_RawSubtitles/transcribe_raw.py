import os
import subprocess
import re

# ── CONFIG ────────────────────────────────────────────────────
WHISPER_BIN   = os.path.expanduser(r"~\whisper.cpp\whisper-cli.exe")
WHISPER_MODEL = os.path.expanduser(r"~\whisper.cpp\models\ggml-large-v3.bin")
VAD_MODEL     = os.path.expanduser(r"~\whisper.cpp\models\ggml-silero-v6.2.0.bin")
REPEAT_THRESHOLD = 5   # how many repeats before we consider it a loop
# ─────────────────────────────────────────────────────────────

currentpath = os.getcwd()
print("currentpath : " + currentpath)

spl = currentpath.split("\\")[-1]
destinationpath = currentpath.split(spl)[0]
print("destinationpath : " + destinationpath)

rawpath = destinationpath + "01_RAW"
print("rawpath : " + rawpath)

mp3files = [f for f in os.listdir(rawpath) if f.endswith(".mp3")]
print("mp3files found : " + str(len(mp3files)))


def srt_timestamp_to_ms(ts):
    # converts "00:12:24,310" to milliseconds
    ts = ts.replace(",", ".")
    h, m, s = ts.split(":")
    return int(h) * 3600000 + int(m) * 60000 + int(float(s) * 1000)


def ms_to_srt_timestamp(ms):
    # converts milliseconds to "00:12:24,310"
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def find_loop_start(srtfile):
    # reads srt and finds the timestamp where a line repeats REPEAT_THRESHOLD times
    print("checking for hallucination loop in : " + srtfile)

    if not os.path.exists(srtfile):
        print("srt not found : " + srtfile)
        return None

    lines = open(srtfile, encoding="utf-8").readlines()

    # collect all (start_ms, text) from the srt
    entries = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if re.match(r"^\d+$", line):  # subtitle index
            if i + 2 < len(lines):
                timecodes = lines[i + 1].strip()
                text = lines[i + 2].strip()
                match = re.match(r"(\d+:\d+:\d+,\d+) --> (\d+:\d+:\d+,\d+)", timecodes)
                if match:
                    start_ms = srt_timestamp_to_ms(match.group(1))
                    entries.append((start_ms, text))
            i += 1
        else:
            i += 1

    # scan for REPEAT_THRESHOLD consecutive same lines
    for i in range(len(entries) - REPEAT_THRESHOLD):
        texts = [entries[i + j][1] for j in range(REPEAT_THRESHOLD)]
        if len(set(texts)) == 1:  # all the same
            loop_start_ms = entries[i][0]
            print("loop detected at : " + ms_to_srt_timestamp(loop_start_ms) + " → \"" + entries[i][1] + "\"")
            return loop_start_ms, i  # return timestamp and line index

    print("no loop detected, transcript looks clean!")
    return None


def run_whisper(mp3path, srtbase, offset_ms=0):
    offset_flag = []
    if offset_ms > 0:
        print("restarting whisper from offset : " + ms_to_srt_timestamp(offset_ms))
        offset_flag = ["--offset-t", str(offset_ms)]

    cmd = [
        WHISPER_BIN,
        "-m", WHISPER_MODEL,
        "-f", mp3path,
        "-of", srtbase,
        "-osrt",
        "-l", "auto",
        "-t", "12",
        "--entropy-thold", "2.4",
        "--logprob-thold", "-1.0",
        "--vad",
        "--vad-model", VAD_MODEL,
    ] + offset_flag

    result = subprocess.run(cmd)
    return result.returncode


def merge_srts(srt_first, first_line_cutoff, srt_second, srt_final):
    # takes clean lines from first srt (up to loop start)
    # then appends all lines from second srt (re-numbered)
    print("merging srts...")

    lines_first = open(srt_first, encoding="utf-8").read().strip().split("\n\n")
    lines_second = open(srt_second, encoding="utf-8").read().strip().split("\n\n")

    # keep only blocks before the loop
    clean_blocks = lines_first[:first_line_cutoff]
    second_blocks = lines_second

    # renumber all blocks sequentially
    all_blocks = clean_blocks + second_blocks
    final_lines = []
    for idx, block in enumerate(all_blocks):
        block_lines = block.strip().split("\n")
        if len(block_lines) >= 2:
            block_lines[0] = str(idx + 1)  # renumber
            final_lines.append("\n".join(block_lines))

    open(srt_final, "w", encoding="utf-8").write("\n\n".join(final_lines) + "\n")
    print("merged srt written : " + srt_final)


for mp3 in mp3files:
    mp3path = rawpath + "\\" + mp3
    print("\n--- processing : " + mp3path)

    srtpath  = currentpath + "\\" + mp3
    srtbase  = srtpath.replace(".mp3", "")
    srtfile  = srtbase + ".srt"

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

    # ── PASS 2: re-run from loop start timestamp ─────────────
    srtbase_part2 = srtbase + "_part2"
    srtfile_part2 = srtbase_part2 + ".srt"

    print("pass 2 : re-running whisper from loop point...")
    code2 = run_whisper(mp3path, srtbase_part2, offset_ms=loop_start_ms)

    if code2 != 0:
        print("failed on pass 2 : " + mp3)
        continue

    print("pass 2 done : " + srtfile_part2)

    # ── MERGE: stitch both srts together ─────────────────────
    srtfile_final = srtbase + "_merged.srt"
    merge_srts(srtfile, loop_line_idx, srtfile_part2, srtfile_final)

    # clean up part2 temp file
    os.remove(srtfile_part2)
    print("cleaned up temp file : " + srtfile_part2)

    print("final srt : " + srtfile_final)
