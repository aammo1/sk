# process_image.py Reference

## Synopsis

```bash
python3 process_image.py (--url URL | --input PATH) [--sizes SIZES] [--output-dir DIR] [--name NAME] [--quality N]
```

## Arguments

| Flag          | Required | Default         | Description                                                               |
|---------------|----------|-----------------|---------------------------------------------------------------------------|
| `--url`       | Yes*     | —               | URL to download image from. Mutually exclusive with `--input`.            |
| `--input`     | Yes*     | —               | Path to local image file. Mutually exclusive with `--url`.                |
| `--sizes`     | No       | `original`      | Comma-separated list of sizes (presets or custom dimensions).            |
| `--output-dir`| No       | `public/images` | Directory to save output files. Created automatically if it doesn't exist.|
| `--name`      | No       | Auto-derived    | Filename prefix for output. Auto-derived from URL/filename if not set.    |
| `--quality`   | No       | `80`            | WebP quality (1-100). 80 is a good balance of quality and file size.      |

*One of `--url` or `--input` is required.

## Size Presets

| Preset     | Dimensions  | Description                              |
|------------|-------------|------------------------------------------|
| `thumb`    | 150×150     | Small thumbnails, grid tiles             |
| `small`    | 300×300     | Product cards, category listings         |
| `medium`   | 600×600     | Product detail main image                |
| `large`    | 1200×auto   | Hero banners, full-width images          |
| `original` | (original)  | No resize, just WebP conversion          |

## Custom Dimensions

Format: `WxH` where either dimension can be `auto` or omitted.

Examples:
- `400x400` — 400px square
- `800xauto` — 800px wide, height proportional
- `x600` — 600px tall, width proportional
- `1200x` — 1200px wide, height proportional (same as 1200xauto)

## Output Naming

Files are named `{name}-{size_label}.webp`.

Examples:
- `product-thumb.webp`
- `hero-banner-large.webp`
- `product-400x400.webp`
- `banner-1200xauto.webp`

## Crop Behavior

When the target aspect ratio differs from the source:
1. The image is center-cropped to match the target ratio
2. Then resized to exact dimensions

This ensures no distortion — images are cropped rather than stretched.

## Dependencies

- **Python 3.6+**
- **Pillow** (`pip3 install Pillow`)

Pillow handles all image processing (open, resize, crop, convert to WebP). The script checks for Pillow at startup and prints installation instructions if it's missing.