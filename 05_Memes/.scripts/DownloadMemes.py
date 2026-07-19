import re
import time
import requests
from io import BytesIO
from PIL import Image
from pathlib import Path
from ddgs import DDGS

plan_path = Path(__file__).resolve().parent.parent / "memeeditplan.md"
print(f"Reading plan: {plan_path}", flush=True)
plan_text = plan_path.read_text(encoding="utf-8")

# Parse table rows: grab filename + meme name columns
meme_entries = re.findall(
    r'\|\s*\d+\s*\|[^|]+\|[^|]+\|\s*(\S+\.(?:jpg|png|jpeg|webp))\s*\|\s*([^|]+?)\s*\|',
    plan_text
)
print(f"Found {len(meme_entries)} memes in plan", flush=True)

memes_dir = Path(__file__).resolve().parent.parent / ".memes"
memes_dir.mkdir(exist_ok=True)
print(f"Saving to: {memes_dir}\n", flush=True)

def simplify_query(meme_name):
    # Strip the descriptive suffix after " - " to keep the query short and clean
    # e.g. 'Pikachu Surprised - "Oh we recording?"' -> 'Pikachu Surprised meme'
    base = meme_name.split(" - ")[0].strip()
    return base + " meme"

with DDGS() as ddgs:
    for filename, meme_name in meme_entries:
        meme_name = meme_name.strip()
        out_path = memes_dir / filename

        if out_path.exists():
            print(f"[skip] {filename} already exists", flush=True)
            continue

        query = simplify_query(meme_name)
        print(f"[search] {query}...", flush=True)
        downloaded = False
        try:
            results = list(ddgs.images(query, max_results=8))
            for r in results:
                url = r.get("image", "")
                if not url:
                    continue
                try:
                    resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
                    resp.raise_for_status()
                    img = Image.open(BytesIO(resp.content))
                    img.verify()
                    out_path.write_bytes(resp.content)
                    print(f"  [ok] {filename} ({img.format})", flush=True)
                    downloaded = True
                    break
                except Exception:
                    continue
        except Exception as e:
            print(f"  [error] search failed: {e}", flush=True)

        if not downloaded:
            print(f"  [fail] could not download {filename}", flush=True)

        time.sleep(2)  # be polite to DDG, avoid rate limit

print("\nDone!", flush=True)
