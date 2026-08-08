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
# .scripts/ -> 05_Memes/ -> <ProjectRoot>/
memes_root   = Path(__file__).resolve().parent.parent      # ...\05_Memes
project_root = memes_root.parent                           # ...\SnowRunnerPart02
project_name = project_root.name

# Folder DownloadMemes.py actually writes to — keep these two in sync.
MEMES_DIR = memes_root / "memes"

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


# Only used to fill the **Video:** header line. The OTIO video track isn't the
# point of this workflow — the Memes track is — so the exact name is cosmetic,
# but the (Xm Ys) duration beside it is NOT: it sets the OTIO timeline length.
video_file = f"{project_name}.mp4"

video_dur_secs = srt_end_seconds(srt_text)
video_dur_str  = f"{video_dur_secs // 60}m {video_dur_secs % 60:02d}s"
print(f"  SRT ends at {video_dur_str}", flush=True)

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

Follow the example's STRUCTURE only — its table columns, its Notes section, its
heading layout. Do NOT copy its header values or its example rows; those belong
to a different project. Use exactly these values in the header and Notes:

- H1 heading:      `{project_name} - Meme Edit Plan`
- **Source SRT:**  `{srt_path.name}`
- **Video:**       `{video_file}` ({video_dur_str})
- Meme folder line, verbatim:
  - All meme images located in `{MEMES_DIR}\\`
- SRT offset line, verbatim:
  - SRT timestamps use the original {video_dur_str} recording start time (00:00:00)

Every SRT timestamp you cite must come from the subtitle below — the last one is
at {video_dur_str}, so spread the memes across that whole range.

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

out = Path(__file__).resolve().parent.parent / "memeeditplan.md"
out.write_text(result, encoding="utf-8")
print(f"Meme edit plan written to {out.resolve()}", flush=True)
