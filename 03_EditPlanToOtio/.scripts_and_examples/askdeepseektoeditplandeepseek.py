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

prompt = f"""Can you edit a video? by just reading a subtitle file, understand the context, and then make and write edits in .otio format ? if can, then please read this subtitle and understand the context first, and make editplan.md of what should we keep and what should we cut. i prefer to include all the fun and interesting stuffs while just cut away the boring or silence moments. In current directory can look for '01_RAW/COMPILED_VIDEO.mp4' that i have generate the subtitle using voice recognition and the subtitle is '02_RawSubtitles/COMPILED_AUDIO.srt' Keep all the interesting, engaging, humorous, or important moments. Cut boring or silent parts. write the editplan to 03_EditPlanToOtio/editplan.md and please write it according to the example below.

Here is the example format to follow:
{example_text}

Here is the subtitle:
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

out = Path("editplan.md")
out.write_text(result, encoding="utf-8")
print(f"Edit plan written to {out.resolve()}", flush=True)
