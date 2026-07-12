import os
import subprocess

# ── CONFIG ────────────────────────────────────────────────────
WHISPER_BIN   = os.path.expanduser(r"~\whisper.cpp\whisper-cli.exe")
WHISPER_MODEL = os.path.expanduser(r"~\whisper.cpp\models\ggml-large-v3.bin")
VAD_MODEL = os.path.expanduser(r"~\whisper.cpp\models\ggml-silero-v6.2.0.bin")
# ─────────────────────────────────────────────────────────────

currentpath = os.getcwd()
print("currentpath : " + currentpath)

spl = currentpath.split("\\")[-1]
destinationpath = currentpath.split(spl)[0]
print("destinationpath : " + destinationpath)

rawpath = destinationpath + "01_RAW"
print("rawpath : " + rawpath)

# find all mp3 files in 01_RAW
mp3files = [f for f in os.listdir(rawpath) if f.endswith(".mp3")]
print("mp3files found : " + str(len(mp3files)))

for mp3 in mp3files:
    mp3path = rawpath + "\\" + mp3
    print("transcribing : " + mp3path)
    
    srtpath = currentpath + "\\" + mp3
    srtbase = srtpath.replace(".mp3", "")
    print("writing to : " + srtbase + ".srt")

    cmd = [
        WHISPER_BIN,
        "-m", WHISPER_MODEL,
        "-f", mp3path,
        "-of", srtbase,
        "-osrt",
        "-l", "auto",
        "-t", "12",
        "--entropy-thold", "2.4",   # default is 2.4, try lowering to 2.0
        "--logprob-thold", "-1.0",  # drops low-confidence segments
        "--vad",
        "--vad-model", VAD_MODEL,
    ]

    result = subprocess.run(cmd)

    if result.returncode == 0:
        print("done : " + srtbase + ".srt")
    else:
        print("failed : " + mp3 + " (exit code " + str(result.returncode) + ")")
