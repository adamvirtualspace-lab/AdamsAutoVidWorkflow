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

prompt = f"""Read the subtitle below and create an edit plan. You have a strict budget of 30 minutes total — pick only the absolute best moments to fill that budget and cut everything else ruthlessly. Score each segment 1-10 (10 = laughter/peak funny moments, 7-8 = engaging, 5-6 = average, 1-4 = boring/filler), then keep only the highest-scored segments until you hit the 30-minute budget. If you must choose between two similar-scored segments, always prefer the funnier or more exciting one. Never cut laughter or a genuinely funny moment. Output only the markdown edit plan, no preamble.\n\nExample format:\n{example_text}\n\nSubtitle:\n{srt_text}"""

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
