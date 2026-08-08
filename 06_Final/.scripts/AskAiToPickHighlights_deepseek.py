import re
from openai import OpenAI
from pathlib import Path

key_file = Path(__file__).resolve().parent.parent.parent / "deepseekapikey.txt"
API_KEY = key_file.read_text(encoding="utf-8").strip()

client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com/")
MODEL = "deepseek-v4-flash"

currentpath = Path(__file__).resolve()
print("current directory : " + str(currentpath))

# ── Project layout ────────────────────────────────────────────────────────────
# .scripts/ -> 06_Final/ -> <ProjectRoot>/
final_root   = Path(__file__).resolve().parent.parent
project_root = final_root.parent
project_name = project_root.name

srt_path = project_root / "04_FinalSubtitle" / "04_FinalSubtitle.srt"
print(f"Reading SRT: {srt_path}", flush=True)
srt_text = srt_path.read_text(encoding="utf-8")
print(f"  {len(srt_text)} chars loaded", flush=True)


def srt_end_seconds(text: str) -> int:
    """Last '-->' end timestamp in the SRT, as whole seconds (rounded up)."""
    stamps = re.findall(r'-->\s*(\d+):(\d+):(\d+)[,.](\d+)', text)
    if not stamps:
        return 0
    h, m, s, ms = stamps[-1]
    return int(h) * 3600 + int(m) * 60 + int(s) + (1 if int(ms) else 0)


cut_secs = srt_end_seconds(srt_text)
cut_str  = f"{cut_secs // 60}m {cut_secs % 60:02d}s"
print(f"  cut runs to {cut_str}", flush=True)

example_path = Path(__file__).resolve().parent / "highlights_example.md"
print(f"Reading example: {example_path}", flush=True)
example_text = example_path.read_text(encoding="utf-8")
print(f"  {len(example_text)} chars loaded", flush=True)

prompt = f"""You are a video editor cutting a cold open. Read the subtitle below and pick the 3 best moments to play BEFORE the intro, as a teaser for the whole episode.

Rules:
- Pick exactly 3 moments
- Each 5-10 seconds long; the three together should stay under about 30 seconds
- They must land without setup - funny, dramatic, or surprising on their own
- Order them for punch, not chronology: the strongest one goes first
- Every timestamp must come from the subtitle below, which runs to {cut_str}
- Output ONLY the Markdown - no preamble, no code fences

Follow the example's STRUCTURE only - its table columns, its Notes section, its
heading layout. Do NOT copy its header values or its example rows; those belong
to a different project. Use exactly these values in the header:

- H1 heading:      `{project_name} - Highlight Plan`
- **Source SRT:**  `{srt_path.name}`

The Cut Time column is a range in FINAL CUT time, the same clock the subtitle
uses. The range IS the clip, so make start and end exactly the moment you want.

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

out = final_root / "highlights.md"
out.write_text(result, encoding="utf-8")
print(f"Highlight plan written to {out.resolve()}", flush=True)
print("Open it, tweak the timestamps if you want, then run the combine step.",
      flush=True)
