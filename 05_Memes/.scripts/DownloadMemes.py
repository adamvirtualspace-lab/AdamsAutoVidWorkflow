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

memes_dir = Path(__file__).resolve().parent.parent / "memes"
memes_dir.mkdir(exist_ok=True)
print(f"Saving to: {memes_dir}\n", flush=True)

def simplify_query(meme_name):
    # Strip the descriptive suffix after " - " to keep the query short and clean
    base = meme_name.split(" - ")[0].strip()
    return base + " meme"

def save_image(image_bytes, out_path):
    """
    Open the image with PIL, convert to a Resolve‑friendly format,
    and save to out_path according to its extension.
    """
    img = Image.open(BytesIO(image_bytes))

    # Determine target format from file extension
    ext = out_path.suffix.lower()
    if ext in ('.jpg', '.jpeg'):
        # Convert to RGB (handles CMYK, paletted, etc.)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        # Save as baseline JPEG (progressive = False) with high quality
        img.save(out_path, 'JPEG', quality=95, optimize=True, progressive=False)
    elif ext == '.png':
        # PNG can keep alpha if present, but convert to RGB if no alpha
        if img.mode not in ('RGBA', 'LA', 'P'):   # P may have transparency
            img = img.convert('RGB')
        # Save as PNG (PIL will handle mode correctly)
        img.save(out_path, 'PNG')
    elif ext == '.webp':
        # WebP is supported, but convert to RGB for safety
        if img.mode != 'RGB':
            img = img.convert('RGB')
        img.save(out_path, 'WEBP', quality=90)
    else:
        # Fallback: save as JPEG
        if img.mode != 'RGB':
            img = img.convert('RGB')
        img.save(out_path, 'JPEG', quality=95, optimize=True, progressive=False)

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
                    # Re‑encode and save with the correct format
                    save_image(resp.content, out_path)
                    print(f"  [ok] {filename} saved", flush=True)
                    downloaded = True
                    break
                except Exception as e:
                    # Log the error but continue trying other images
                    # print(f"  [warn] failed to process image: {e}", flush=True)
                    continue
        except Exception as e:
            print(f"  [error] search failed: {e}", flush=True)

        if not downloaded:
            print(f"  [fail] could not download {filename}", flush=True)

        time.sleep(1.5)  # polite delay to avoid rate limits

print("\nDone!", flush=True)
