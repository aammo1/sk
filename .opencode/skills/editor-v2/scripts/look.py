#!/usr/bin/env python3
"""look.py — show or change the video's look (work/look.json), shared by the hook, the inserts and
the body: accent colour, how the screen is framed, how far zooms go, border trimming, chapter cards,
and explainer pacing.

    ev2 look <dir>                                   print it (resolving "auto")
    ev2 look <dir> --accent "#E11D74" | auto         brand colour (auto = from the recording)
    ev2 look <dir> --frame inset | full              screen as a rounded card on the backdrop, or edge to edge
    ev2 look <dir> --max-zoom 1.6                    1.2-2.0
    ev2 look <dir> --trim auto | off                 cut window borders / wallpaper slivers
    ev2 look <dir> --no-click-sfx | --click-sfx
    ev2 look <dir> --pip-corner auto|top-left|top-right|bottom-left|bottom-right   where the speaker PiP sits
    ev2 look <dir> --chapter-style full | bar        full-page pause card (default) or lower-third bar
    ev2 look <dir> --chapter-hold 2.8                seconds a full-page chapter card adds (2.0-4.0)
    ev2 look <dir> --insert-every 60                 suggest an explainer every N body seconds (0 or 30-300)
    ev2 look <dir> --insert-hold 4.0                 finished explainer hold before exit (2.0-8.0)
After a change: `ev2 hook <dir>`, `ev2 inserts <dir>` and `ev2 finish <dir>` pick it up.
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'components'))
import ev2_pro as P  # noqa: E402


def _fail(msg):
    print(f'look: {msg}', file=sys.stderr)
    sys.exit(2)


ap = argparse.ArgumentParser(description='Show or change work/look.json')
ap.add_argument('video_dir')
ap.add_argument('--accent')
ap.add_argument('--frame', choices=['inset', 'full'])
ap.add_argument('--max-zoom', type=float)
ap.add_argument('--inset', type=float)
ap.add_argument('--trim', choices=['auto', 'off'])
ap.add_argument('--click-sfx', dest='click_sfx', action='store_true', default=None)
ap.add_argument('--no-click-sfx', dest='click_sfx', action='store_false')
ap.add_argument('--pip-corner', choices=['auto', 'top-left', 'top-right', 'bottom-left', 'bottom-right'])
ap.add_argument('--chapter-style', choices=['full', 'bar'])
ap.add_argument('--chapter-hold', type=float)
ap.add_argument('--insert-every', type=int)
ap.add_argument('--insert-hold', type=float)
a = ap.parse_args()

if a.chapter_hold is not None and not 2.0 <= a.chapter_hold <= 4.0:
    _fail(f'--chapter-hold must be 2.0-4.0 s (got {a.chapter_hold:g})')
if a.insert_every is not None and not (a.insert_every == 0 or 30 <= a.insert_every <= 300):
    _fail(f'--insert-every must be 0 or 30-300 s (got {a.insert_every})')
if a.insert_hold is not None and not 2.0 <= a.insert_hold <= 8.0:
    _fail(f'--insert-hold must be 2.0-8.0 s (got {a.insert_hold:g})')

vd = os.path.abspath(a.video_dir)
lp = os.path.join(vd, 'work', 'look.json')
look = json.load(open(lp)) if os.path.isfile(lp) else {}
force = False
if a.accent:
    look['accent'] = a.accent
    look.pop('resolved_accent', None)
    force = True
if a.frame:
    look['frame'] = a.frame
if a.max_zoom is not None:
    look['max_zoom'] = a.max_zoom
if a.inset is not None:
    look['inset'] = a.inset
if a.trim:
    look['trim'] = a.trim
    look.pop('resolved_trim', None)
if a.click_sfx is not None:
    look['click_sfx'] = a.click_sfx
if a.pip_corner:
    look['pip_corner'] = a.pip_corner
if a.chapter_style is not None:
    look['chapter_style'] = a.chapter_style
if a.chapter_hold is not None:
    look['chapter_hold'] = a.chapter_hold
if a.insert_every is not None:
    look['insert_every'] = a.insert_every
if a.insert_hold is not None:
    look['insert_hold'] = a.insert_hold
os.makedirs(os.path.dirname(lp), exist_ok=True)
json.dump(look, open(lp, 'w'), indent=2)
look, th = P.ensure_look(vd, force=force)
print(json.dumps(look, indent=2))
print(f'look: accent {th["accent"]} (gradient to {th["accent2"]}), backdrop assets/pro/bg.png')
