---
name: image-to-webp
description: Download images from URLs or local files, resize them to standard web dimensions (thumbnails, product cards, hero banners, etc.), and convert to WebP for performance. Handles batch processing, responsive srcset generation, and stores output in public/images. Use this skill whenever the user asks to download stock photos from Pexels, Unsplash, Shutterstock (or any image URL), resize or scale images, convert images to WebP, optimize images for web performance, prepare product images for an ecommerce store, generate multiple image sizes for responsive design, or process local/uploaded image files for use in a web application. Also trigger when the user mentions image optimization, web image formats, srcset, or needs images in their public folder for caching.
---

# Image to WebP

This skill streamlines getting images ready for web and e-commerce use. It handles two workflows:

1. **URL workflow**: Download an image from a URL → resize → convert to WebP → save to `public/images/`
2. **Local file workflow**: Take an existing local image → resize → convert to WebP → save to `public/images/`

The goal is producing optimized, cacheable images in the right sizes for storefronts and web apps.

## Preset Sizes

Use these presets when the user doesn't specify exact dimensions. They cover standard web/e-commerce needs:

| Preset     | Dimensions | Use case                                      |
|------------|-----------|-----------------------------------------------|
| `thumb`    | 150×150   | Thumbnails, product grid tiles, cart previews  |
| `small`    | 300×300   | Product cards, category listings              |
| `medium`   | 600×600   | Product detail page main image                |
| `large`    | 1200×auto | Hero banners, full-width section images       |
| `original` | —         | No resize, just WebP conversion              |

When the user asks for a specific size like "400px wide" or "square at 200", use those exact dimensions instead of a preset.

For `auto` dimensions, maintain the original aspect ratio. For example, `1200×auto` means 1200px wide with height proportional.

## How to Process Images

### Step 1: Determine the task

Ask the user (or infer from context):
- Image source: URL or local file path?
- Desired size: a preset name, specific dimensions, or multiple sizes for responsive srcset?
- Output name: what to call the file? If not specified, derive a slug from the URL or filename.

### Step 2: Install dependencies if needed

The processing script requires Pillow. Check if it's installed:

```bash
python3 -c "import PIL" 2>/dev/null || pip3 install Pillow
```

### Step 3: Run the processing script

Use the bundled script at `scripts/process_image.py`. It handles download, resize, and convert in one step.

**Download from URL and process:**
```bash
python3 <skill-path>/scripts/process_image.py \
  --url "https://images.pexels.com/photos/example.jpeg" \
  --sizes thumb,medium \
  --output-dir public/images \
  --name "product-shot"
```

**Process a local file:**
```bash
python3 <skill-path>/scripts/process_image.py \
  --input path/to/local-image.jpg \
  --sizes large \
  --output-dir public/images \
  --name "hero-banner"
```

**Custom dimensions:**
```bash
python3 <skill-path>/scripts/process_image.py \
  --url "https://images.pexels.com/photos/example.jpeg" \
  --sizes 400x400 \
  --output-dir public/images \
  --name "product-thumb"
```

**Multiple sizes for srcset:**
```bash
python3 <skill-path>/scripts/process_image.py \
  --url "https://images.pexels.com/photos/example.jpeg" \
  --sizes thumb,small,medium,large \
  --output-dir public/images \
  --name "product"
```

This produces `product-thumb.webp`, `product-small.webp`, `product-medium.webp`, and `product-large.webp`.

### Step 4: Report results

After processing, tell the user:
- What files were created and where
- The file sizes (the script outputs these)
- Suggested usage in their app (e.g., the appropriate `<img>` or Next.js `<Image>` tag)

### Step 5: Usage guidance

If the project uses Next.js, suggest using the `<Image>` component:

```jsx
<Image
  src="/images/hero-banner-large.webp"
  alt="Hero banner"
  width={1200}
  height={600}
/>
```

For standard HTML, suggest `<picture>` with srcset for responsive images:

```html
<picture>
  <source
    media="(max-width: 600px)"
    srcset="/images/product-small.webp"
  />
  <source
    media="(max-width: 1200px)"
    srcset="/images/product-medium.webp"
  />
  <img
    src="/images/product-large.webp"
    alt="Product photo"
    loading="lazy"
  />
</picture>
```

## Batch Processing

When the user provides multiple URLs or a list of images, process them in sequence. Provide a summary table at the end showing each file, its size preset, output path, and file size.

## Output Directory Convention

- Default output directory: `public/images/`
- Create the directory if it doesn't exist (the script does this automatically)
- If the project uses a different convention (e.g., `static/img/`, `assets/images/`), adapt accordingly but keep the images together in one directory

## Naming Convention

File names follow the pattern `{name}-{preset}.webp` or `{name}-{width}x{height}.webp` for custom sizes.

For example:
- `product-medium.webp`
- `hero-banner-1200xauto.webp`
- `team-photo-600x600.webp`

The `--name` flag determines the prefix. If not provided, the script derives it from the URL or filename.

## Error Handling

- If a URL returns an error (404, timeout, etc.), report it clearly and suggest the user verify the URL
- If a local file doesn't exist, tell the user the exact path checked and ask them to verify
- If Pillow isn't available and pip install fails, guide the user through manual installation

## Script Reference

For full details on the processing script's options and behavior, read `references/script_reference.md`.