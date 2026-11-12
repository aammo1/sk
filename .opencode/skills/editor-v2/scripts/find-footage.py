#!/usr/bin/env python3
"""find-footage.py — search free/real footage sources for one idea, and show it as a sheet.

    python find-footage.py "<query>" <outdir> [--src archive,nasa,commons,mixkit,yt] [--n 8] [--kie-prompt "<prompt>"]

Writes <outdir>/<slug>.json (candidates: source, id, title, duration, licence, page, media
url or yt id) and <outdir>/<slug>.jpg (a thumbnail contact sheet, numbered) so a clip is
chosen by LOOKING at it, never by its title.

Sources (no keys, no logins):
  archive  archive.org moving images (Prelinger etc. — mostly public domain; check each item's
           licenseurl). The vintage-film look the references lean on.
  nasa     images-api.nasa.gov videos (public domain).
  commons  Wikimedia Commons video files (licence per file).
  mixkit   mixkit.co tag pages /free-stock-video/<tag>/ (Mixkit licence, free commercial use).
  yt       yt-dlp "ytsearch" metadata only. Rights depend on the channel: NASA = public domain;
           a company's own launch film used in commentary = flag it in PLAN.md; movie clips =
           flag, and only when the film is the subject or the metaphor is the point.
  kie      KIE AI fallback image generation via --kie-prompt.
"""
import argparse, json, os, re, subprocess, sys, urllib.parse, urllib.request
from io import BytesIO

# Re-exec under editor-v2 private venv if PIL is not installed in ambient python
try:
    import PIL
except ImportError:
    venv_py = os.path.expanduser('~/.cache/editor-v2/venv/bin/python')
    if os.path.exists(venv_py) and sys.executable != venv_py:
        os.execv(venv_py, [venv_py] + sys.argv)

UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'}
UA_API = {'User-Agent': os.environ.get('EV2_CONTACT_UA', os.environ.get('EV1_CONTACT_UA', 'EditorV2Kit/1.0 (personal video editing)'))}


def get(url, hdr=UA, timeout=25):
    if not url:
        raise ValueError('empty url')
    if os.path.exists(url):
        with open(url, 'rb') as f:
            return f.read()
    return urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=timeout).read()


def archive(q, n):
    qq = f'({q}) AND mediatype:movies'
    u = ('https://archive.org/advancedsearch.php?q=' + urllib.parse.quote(qq) +
         '&fl[]=identifier&fl[]=title&fl[]=licenseurl&fl[]=downloads&sort[]=downloads+desc&rows=%d&output=json' % n)
    out = []
    for d in json.loads(get(u, UA_API))['response']['docs']:
        ident = d['identifier']
        out.append(dict(src='archive', id=ident, title=d.get('title', ''), licence=d.get('licenseurl', 'see item'),
                        page=f'https://archive.org/details/{ident}', thumb=f'https://archive.org/services/img/{ident}'))
    return out


def archive_media(ident):
    """best mp4 for an archive item."""
    md = json.loads(get(f'https://archive.org/metadata/{ident}', UA_API))
    fs = [f for f in md.get('files', []) if f['name'].lower().endswith('.mp4')]
    fs.sort(key=lambda f: (('h.264' in f.get('format', '').lower()) or ('512kb' in f['name'].lower())) * -1 + 0)
    big = sorted(fs, key=lambda f: -int(f.get('size', 0) or 0))
    pick = big[0] if big else None
    return f'https://archive.org/download/{ident}/{urllib.parse.quote(pick["name"])}' if pick else None


def nasa(q, n):
    u = 'https://images-api.nasa.gov/search?media_type=video&q=' + urllib.parse.quote(q)
    out = []
    for it in json.loads(get(u, UA_API))['collection']['items'][:n]:
        m = it['data'][0]; thumb = next((l['href'] for l in it.get('links', []) if l.get('render') == 'image'), None)
        out.append(dict(src='nasa', id=m['nasa_id'], title=m.get('title', ''), licence='public domain (NASA)',
                        page=f'https://images.nasa.gov/details/{urllib.parse.quote(m["nasa_id"])}', thumb=thumb, collection=it['href']))
    return out


def commons(q, n):
    u = ('https://commons.wikimedia.org/w/api.php?action=query&format=json&generator=search&gsrnamespace=6&gsrlimit=%d'
         '&gsrsearch=%s&prop=imageinfo&iiprop=url|extmetadata|mime&iiurlwidth=480' % (n * 2, urllib.parse.quote(q + ' filetype:video')))
    out = []
    for p in (json.loads(get(u, UA_API)).get('query', {}).get('pages', {}) or {}).values():
        ii = p['imageinfo'][0]
        if not ii.get('mime', '').startswith('video'): continue
        lic = ii.get('extmetadata', {}).get('LicenseShortName', {}).get('value', '?')
        out.append(dict(src='commons', id=p['title'], title=p['title'][5:], licence=lic, page=ii.get('descriptionurl'),
                        media=ii['url'], thumb=ii.get('thumburl')))
    return out[:n]


def _mixkit_scrape(tag, out, n):
    if not tag:
        return
    try:
        h = get(f'https://mixkit.co/free-stock-video/{tag}/').decode('utf8', 'ignore')
    except Exception:
        return
    for slug, vid in re.findall(r'href="/free-stock-video/([a-z0-9\-]+)-(\d+)/"', h):
        if any(o['id'] == vid for o in out): continue
        out.append(dict(src='mixkit', id=vid, title=slug.replace('-', ' '), licence='Mixkit Stock Video Free License',
                        page=f'https://mixkit.co/free-stock-video/{slug}-{vid}/', media=f'https://assets.mixkit.co/videos/{vid}/{vid}-1080.mp4',
                        thumb=f'https://assets.mixkit.co/videos/{vid}/{vid}-thumb-360-0.jpg'))
        if len(out) >= n: break


def mixkit(q, n):
    tag = re.sub(r'[^a-z0-9]+', '-', q.lower()).strip('-')
    out = []
    if tag:
        _mixkit_scrape(tag, out, n)
    if not out and '-' in tag:
        # multi-word slug returned 0 results: try individual words (longest words first)
        words = sorted(list(dict.fromkeys(w for w in tag.split('-') if w)), key=len, reverse=True)
        for w in words:
            _mixkit_scrape(w, out, n)
            if len(out) >= n:
                break
    return out


def yt(q, n):
    r = subprocess.run(['yt-dlp', '--flat-playlist', '-J', f'ytsearch{n}:{q}'], capture_output=True, text=True)
    try:
        es = json.loads(r.stdout).get('entries', [])
    except Exception:
        return []
    return [dict(src='yt', id=e['id'], title=e.get('title', ''), channel=e.get('channel') or e.get('uploader'),
                 duration=e.get('duration'), licence='check channel', page=f'https://www.youtube.com/watch?v={e["id"]}',
                 thumb=f'https://i.ytimg.com/vi/{e["id"]}/hqdefault.jpg') for e in es]


def sheet(cands, path):
    from PIL import Image, ImageDraw
    if not cands:
        return
    tw, th = 384, 216; cols = 4; rows = max(1, (len(cands) + cols - 1) // cols)
    S = Image.new('RGB', (cols * tw, rows * (th + 34)), (25, 25, 25)); d = ImageDraw.Draw(S)
    for i, c in enumerate(cands):
        x, y = (i % cols) * tw, (i // cols) * (th + 34)
        try:
            im = Image.open(BytesIO(get(c.get('thumb'), UA, 15))).convert('RGB'); im.thumbnail((tw, th)); S.paste(im, (x, y + 34))
        except Exception:
            d.text((x + 8, y + 120), 'no thumb', fill=(200, 80, 80))
        d.text((x + 4, y + 2), f"{i} [{c['src']}] {c['title'][:44]}", fill=(255, 220, 0))
        d.text((x + 4, y + 17), f"{(c.get('channel') or c.get('licence') or '')[:40]} {c.get('duration') or ''}", fill=(170, 170, 170))
    S.save(path, quality=82)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Find real/free footage and generate thumbnails')
    ap.add_argument('query', help='Search query')
    ap.add_argument('out', help='Output directory')
    ap.add_argument('--src', default='archive,nasa,commons,mixkit,yt', help='Comma-separated sources')
    ap.add_argument('--n', type=int, default=6, help='Number of items per source')
    ap.add_argument('--kie-prompt', default=None, help='Optional prompt for KIE image generation fallback')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    slug = re.sub(r'[^a-z0-9]+', '-', a.query.lower()).strip('-')[:50]
    allc = []
    for s in a.src.split(','):
        s = s.strip()
        if not s: continue
        if s in globals():
            try:
                allc += globals()[s](a.query, a.n)
            except Exception as e:
                print(f'{s}: {e}', file=sys.stderr)

    kie_tool = os.path.expanduser(os.environ.get('EV2_KIE_TOOL', '~/.dsh/tools/kie_generate.py'))
    if a.kie_prompt and os.path.exists(kie_tool):
        kie_out = os.path.join(a.out, f'kie_{slug}.png')
        cmd = [
            'uv', 'run', '--script', kie_tool,
            '--prompt', a.kie_prompt,
            '--aspect', '16:9',
            '--out', kie_out
        ]
        try:
            subprocess.run(cmd, check=False)
        except Exception as e:
            print(f'kie: {e}', file=sys.stderr)
        allc.append(dict(
            src='kie',
            id=f'kie_{slug}',
            title=a.kie_prompt,
            licence='KIE Generated',
            page=kie_out,
            media=kie_out,
            thumb=kie_out
        ))

    json.dump(allc, open(os.path.join(a.out, slug + '.json'), 'w'), indent=1)
    sheet(allc, os.path.join(a.out, slug + '.jpg'))
    for i, c in enumerate(allc):
        print(i, c['src'], c['id'], '|', c['title'][:70], '|', c.get('channel') or c.get('licence'), c.get('duration') or '')
