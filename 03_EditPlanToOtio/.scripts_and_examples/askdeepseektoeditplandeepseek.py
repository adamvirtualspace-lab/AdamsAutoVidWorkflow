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

prompt = f"""You are a video editor assistant. Your task is to read the subtitle file below, understand the video's content, rank every segment by importance, and produce a structured edit plan in Markdown format.

## Source Files (for reference)
- Video: `01_RAW/COMPILED_VIDEO.mp4`
- Subtitle: `02_RawSubtitles/COMPILED_AUDIO_merged.srt` (content provided below)

## Step 1 — Score Every Segment
Before deciding what to cut, mentally score each segment from 1–10 based on these criteria:

| Score | Meaning |
|-------|---------|
| 9–10  | Must keep — laughter, peak funny moments, major events, emotional highs |
| 7–8   | Strong — engaging story, interesting gameplay, good conversation |
| 5–6   | Average — decent content, some value but not essential |
| 3–4   | Weak — repetitive, slow, or filler content |
| 1–2   | Cut — silence, dead air, nothing happening |

## Step 2 — Apply the 50% Rule
- Rank all segments by their score
- **Automatically cut the bottom 50% lowest-scored segments**
- Always keep scores 7 and above, no matter what
- Scores 5–6 only survive if cutting them would break narrative flow

## Step 3 — Hard Rules (override everything)
- **NEVER cut laughter** — instant score 10, always kept
- **NEVER cut funny moments** — score 9–10, always kept
- If cutting a segment would make the surrounding context confusing, keep it

## Duration Target
- Aim for final video **under 30 minutes**
- If still above 30 minutes after applying the 50% rule, drop all remaining score 5–6 segments

## Output Instructions
- Output **only** the Markdown edit plan — no preamble, no explanation, no code fences
- Include the score for each segment in the edit plan
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
