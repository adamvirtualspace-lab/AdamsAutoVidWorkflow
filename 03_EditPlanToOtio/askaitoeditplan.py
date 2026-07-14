import ollama
import sys
from pathlib import Path

MODEL = "qwen3.5:4b"   # change to your preferred local model

def generate_editplan(srt_path: Path, raw_path: Path) -> str:
    subtitle_text = srt_path.read_text(encoding="utf-8")
    video_path = raw_path.resolve()

    prompt = f"""You are a video editor. Below is an SRT subtitle file from a gameplay video.

Analyze the subtitles and decide which segments to KEEP (funny, interesting, engaging) and which to CUT (boring, silence, filler).

Output a markdown edit plan with this exact format:

# Edit Plan
Source media reference: {video_path}

| # | Keep/Cut | Start | End | Notes |
|---|----------|-------|-----|-------|
| 1 | KEEP | 00:00:00 | 00:00:05 | example row |

Rules:
- Use timecodes in HH:MM:SS format (no milliseconds).
- Every row must cover a contiguous time segment of the video.
- KEEP = interesting/funny/engaging parts.
- CUT = boring/silent/filler parts.
- All timecodes must be in HH:MM:SS format.

Here is the subtitle content:
{subtitle_text}"""

    try:
        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={
                "num_predict": 65536,
                "temperature": 0.2,
            }
        )
        return response["message"]["content"]
    except Exception as e:
        print(f"Ollama call failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    srt = Path("../02_RawSubtitles/COMPILED_AUDIO_merged.srt")
    raw = Path("../01_RAW/COMPILED_VIDEO.mp4")
    if not srt.exists():
        print(f"SRT file not found: {srt}")
        sys.exit(1)
    if not raw.exists():
        print(f"RAW file not found: {raw}")
        sys.exit(1)
    print("Generating edit plan from subtitles...")
    result = generate_editplan(srt, raw)
    out_path = Path("editplan.md")
    out_path.write_text(result, encoding="utf-8")
    print(f"Edit plan written to {out_path.resolve()}")
