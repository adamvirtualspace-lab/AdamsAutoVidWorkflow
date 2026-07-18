import re
from openai import OpenAI
from pathlib import Path

key_file = Path(__file__).resolve().parent.parent.parent / "deepseekapikey.txt"
API_KEY = key_file.read_text(encoding="utf-8").strip()

client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com/")
MODEL = "deepseek-v4-flash"

currentpath = Path(__file__).resolve()
print("current directory : " + str(currentpath))

srt_path = Path(__file__).resolve().parent.parent.parent / "04_FinalSubtitle" / "04_FinalSubtitle.srt"
print(f"Reading SRT: {srt_path}", flush=True)
srt_text = srt_path.read_text(encoding="utf-8")
print(f"  {len(srt_text)} chars loaded", flush=True)

example_path = Path(__file__).resolve().parent / "memeeditplan_example.md"
print(f"Reading example: {example_path}", flush=True)
example_text = example_path.read_text(encoding="utf-8")
print(f"  {len(example_text)} chars loaded", flush=True)

prompt = f"""You are a meme-savvy video editor. Read the subtitle below, find funny or interesting moments, and assign a fitting well-known internet meme to each one.

Rules:
- Filenames: lowercase, underscores, `.jpg` (e.g. `this_is_fine.jpg`)
- Duration: 4–6s standard, 3s for quick reactions
- Use Indonesian/local memes where appropriate
- Output ONLY the Markdown — no preamble, no code fences
- Follow the example format exactly; set meme folder to `05_Memes\\.memes\\`

## Example:
{example_text}

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

# Strip accidental markdown code fences if model wraps output
m = re.search(r'```markdown\s*\n(.*?)\n```', result, re.DOTALL)
if m:
    result = m.group(1).strip()
    print(f"  Extracted markdown block ({len(result)} chars)", flush=True)

out = Path(__file__).resolve().parent / "memeeditplan.md"
out.write_text(result, encoding="utf-8")
print(f"Meme edit plan written to {out.resolve()}", flush=True)
