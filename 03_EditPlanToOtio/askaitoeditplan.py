import ollama
import subprocess
import sys
from pathlib import Path

MODEL = "qwen3.5:4b"   # change to your preferred local model

def generate_editplan(srt_path: Path, raw_path: Path) -> str:
    subtitle_text = srt_path.read_text(encoding="utf-8")

    prompt = f"""Can you edit a video? by just reading a subtitle file, understand the context, and then make and write edits in .otio format ? if can, then please read this subtitle and understand the context first, and make editplan.md of what should we keep and what should we cut. i prefer to include all the fun and interesting stuffs while just cut away the boring or silence moments. In current directory can look for "\01_RAW\COMPILED_VIDEO.mp4 that i have generate the subtitle using voice recognition and the subtitle is \02_RawSubtitles\COMPILED_AUDIO.srt
Keep all the interesting, engaging, humorous, or important moments. Cut boring or silent parts. write the editplan to 03_EditPlanToOtio\editplan.md and please write it according to editplan_example.md"""
    
    try:
        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={
                "num_predict": 65.536,   # maximum tokens to generate
                "temperature": 0.2     # lower = more deterministic
            }
        )
        return response["message"]["content"]
    except Exception as e:
        print(f"❌ Ollama call failed: {e}")
        sys.exit(1)
