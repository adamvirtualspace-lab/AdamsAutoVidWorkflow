import sys
from openai import OpenAI
from pathlib import Path

key_file = Path(__file__).resolve().parent.parent.parent / "deepseekapikey.txt"
API_KEY = key_file.read_text(encoding="utf-8").strip()

client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com/")
MODEL = "deepseek-v4-flash"

srt_path = Path("../02_RawSubtitles/COMPILED_AUDIO_merged.srt")
print(f"Reading SRT: {srt_path}", flush=True)
srt_text = srt_path.read_text(encoding="utf-8")
print(f"  {len(srt_text)} chars loaded", flush=True)

example_path = Path(__file__).resolve().parent / "editplan_example.md"
print(f"Reading example: {example_path}", flush=True)
example_text = example_path.read_text(encoding="utf-8")
print(f"  {len(example_text)} chars loaded", flush=True)

prompt = f"""You are a video editor assistant. Your task is to read the subtitle file below, understand the video's content and context, then produce a structured edit plan in Markdown format.

## Source Files (for reference)
- Video: `01_RAW/COMPILED_VIDEO.mp4`
- Subtitle: `02_RawSubtitles/COMPILED_AUDIO_merged.srt` (content provided below)

## Your Task
Analyze the subtitle and write an edit plan. The output path will be: `03_EditPlanToOtio/editplan.md`

## Editing Rules

**KEEP:**
- Funny, entertaining, or humorous moments
- Laughter — never cut this under any circumstances
- Engaging conversation or storytelling
- Interesting or important content

**CUT:**
- Boring, dull, or repetitive segments
- Silent or dead-air moments
- Filler content with no value

## Duration Target
- Aim for a final video duration **under 30 minutes**
- If the total duration of kept segments exceeds 30 minutes, revise and cut more aggressively until it fits

## Output Instructions
- Output **only** the Markdown edit plan — no preamble, no explanation, no code fences
- Follow the example format exactly

## Example Format:
{example_text}

---

## Subtitle:
{srt_text}"""

print(f"Sending {len(prompt)} chars to DeepSeek...", flush=True)
response = client.chat.completions.create(
    model=MODEL,
    messages=[{"role": "user", "content": prompt}],
    stream=False,
    reasoning_effort="low",
    extra_body={"thinking": {"type": "enabled"}},
)

result = response.choices[0].message.content
print(f"Response received: {len(result)} chars", flush=True)

# Extract markdown content between ```markdown and ``` if present
import re
m = re.search(r'```markdown\s*\n(.*?)\n```', result, re.DOTALL)
if m:
    result = m.group(1).strip()
    print(f"  Extracted markdown block ({len(result)} chars)", flush=True)

out = Path("editplan.md")
out.write_text(result, encoding="utf-8")
print(f"Edit plan written to {out.resolve()}", flush=True)
