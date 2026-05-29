#!/usr/bin/env python3
"""Download, resize, and convert images to WebP for web/ecommerce use."""

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    from PIL import Image
except ImportError:
    print("Pillow is required. Install it with: pip3 install Pillow")
    sys.exit(1)

try:
    import urllib.request
    from urllib.error import URLError, HTTPError
except ImportError:
    print("urllib is required but not available.")
    sys.exit(1)

PRESETS = {
    "thumb": (150, 150),
    "small": (300, 300),
    "medium": (600, 600),
    "large": (1200, None),  # width=1200, height=auto
    "original": (None, None),
}

VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif"}


def slugify(name):
    name = name.lower().strip()
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s_]+", "-", name)
    name = re.sub(r"-+", "-", name)
    return name.strip("-")


def download_image(url, dest_path):
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; ImageProcessor/1.0)"
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            with open(dest_path, "wb") as f:
                f.write(resp.read())
        return True
    except HTTPError as e:
        print(f"HTTP error downloading {url}: {e.code} {e.reason}")
        return False
    except URLError as e:
        print(f"URL error downloading {url}: {e.reason}")
        return False
    except Exception as e:
        print(f"Error downloading {url}: {e}")
        return False


def parse_size(size_str):
    if size_str in PRESETS:
        return PRESETS[size_str]
    match = re.match(r"^(\d+)?x(\d+)?$", size_str)
    if match:
        w = int(match.group(1)) if match.group(1) else None
        h = int(match.group(2)) if match.group(2) else None
        if w or h:
            return (w, h)
    raise ValueError(
        f"Invalid size '{size_str}'. Use a preset ({', '.join(PRESETS.keys())}) "
        f"or a dimension like 400x400, 800xauto, or 1200x."
    )


def size_label(size_str, dims):
    if size_str in PRESETS:
        return size_str
    w, h = dims
    w_str = str(w) if w else "auto"
    h_str = str(h) if h else "auto"
    return f"{w_str}x{h_str}"


def process_image(input_path, output_dir, name, sizes, quality=80):
    try:
        img = Image.open(input_path)
    except Exception as e:
        print(f"Error opening image: {e}")
        return []

    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")

    results = []
    for size_str in sizes:
        dims = parse_size(size_str)
        w, h = dims

        label = size_label(size_str, dims)
        if len(sizes) == 1 and size_str not in PRESETS and "x" in size_str:
            filename = f"{name}-{label}.webp"
        elif len(sizes) == 1 and size_str in PRESETS:
            filename = f"{name}-{label}.webp"
        else:
            filename = f"{name}-{label}.webp"

        out_path = os.path.join(output_dir, filename)

        if w is None and h is None:
            resized = img.copy()
        else:
            orig_w, orig_h = img.size
            if w and h:
                target_ratio = w / h
                orig_ratio = orig_w / orig_h
                if abs(target_ratio - orig_ratio) > 0.01:
                    crop_ratio = orig_w / orig_h if target_ratio > orig_ratio else orig_h / orig_w
                    if target_ratio > orig_ratio:
                        new_h = int(orig_w / target_ratio)
                        top = (orig_h - new_h) // 2
                        cropped = img.crop((0, top, orig_w, top + new_h))
                    else:
                        new_w = int(orig_h * target_ratio)
                        left = (orig_w - new_w) // 2
                        cropped = img.crop((left, 0, left + new_w, orig_h))
                    resized = cropped.resize((w, h), Image.LANCZOS)
                else:
                    resized = img.resize((w, h), Image.LANCZOS)
            elif w and not h:
                ratio = w / orig_w
                new_h = int(orig_h * ratio)
                resized = img.resize((w, new_h), Image.LANCZOS)
            elif h and not w:
                ratio = h / orig_h
                new_w = int(orig_w * ratio)
                resized = img.resize((new_w, h), Image.LANCZOS)
            else:
                resized = img.copy()

        save_kwargs = {"format": "WEBP", "quality": quality}
        if resized.mode == "RGBA":
            save_kwargs["background"] = (255, 255, 255)
            save_kwargs["format"] = "WEBP"

        resized.save(out_path, **save_kwargs)

        file_size = os.path.getsize(out_path)
        results.append({
            "path": out_path,
            "size": label,
            "dimensions": resized.size,
            "file_size": file_size,
        })
        print(f"  Created: {out_path} ({resized.size[0]}x{resized.size[1]}, {file_size:,} bytes)")

    return results


def derive_name_from_url(url):
    parsed = urlparse(url)
    path = parsed.path
    filename = os.path.splitext(os.path.basename(path))[0]
    name = slugify(filename) if filename else "image"
    if not name or name == "image":
        name = slugify(parsed.netloc.replace(".", "-"))
    return name


def derive_name_from_path(filepath):
    filename = os.path.splitext(os.path.basename(filepath))[0]
    return slugify(filename) if filename else "image"


def main():
    parser = argparse.ArgumentParser(
        description="Download, resize, and convert images to WebP."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", help="URL to download the image from")
    group.add_argument("--input", help="Path to a local image file")
    parser.add_argument(
        "--sizes",
        default="original",
        help="Comma-separated list of sizes. Presets: thumb, small, medium, large, original. "
        "Custom: 400x400, 800xauto, 1200x. Default: original",
    )
    parser.add_argument(
        "--output-dir",
        default="public/images",
        help="Output directory (default: public/images)",
    )
    parser.add_argument("--name", help="Output filename prefix (without extension)")
    parser.add_argument(
        "--quality", type=int, default=80, help="WebP quality 1-100 (default: 80)"
    )

    args = parser.parse_args()

    sizes = [s.strip() for s in args.sizes.split(",")]

    if args.url:
        name = args.name or derive_name_from_url(args.url)
        tmp_ext = os.path.splitext(urlparse(args.url).path)[1] or ".jpg"
        tmp_path = os.path.join("/tmp", f"image-to-webp-download{tmp_ext}")
        print(f"Downloading {args.url}...")
        if not download_image(args.url, tmp_path):
            sys.exit(1)
        input_path = tmp_path
    else:
        name = args.name or derive_name_from_path(args.input)
        input_path = args.input
        if not os.path.exists(input_path):
            print(f"Error: Input file not found: {input_path}")
            sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    print(f"Processing '{name}' at sizes: {', '.join(sizes)}")
    results = process_image(input_path, args.output_dir, name, sizes, args.quality)

    if not results:
        print("No images were produced.")
        sys.exit(1)

    print(f"\nDone! Created {len(results)} file(s):")
    for r in results:
        print(f"  {r['path']} — {r['dimensions'][0]}x{r['dimensions'][1]} — {r['file_size']:,} bytes")

    if args.url:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()