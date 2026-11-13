#!/usr/bin/env python3
"""look.py — show or change the video's look (work/look.json), shared by the hook, the inserts and
the body: accent colour, how the screen is framed, how far zooms go, border trimming.

    ev2 look <dir>                                   print it (resolving "auto")
    ev2 look <dir> --accent "#E11D74" | auto         brand colour (auto = from the recording)
    ev2 look <dir> --frame inset | full              screen as a rounded card on the backdrop, or edge to edge
    ev2 look <dir> --max-zoom 1.6                    1.2-2.0
    ev2 look <dir> --trim auto | off                 cut window borders / wallpaper slivers
    ev2 look <dir> --no-click-sfx | --click-sfx
After a change: `ev2 hook <dir>`, `ev2 inserts <dir>` and `ev2 finish <dir>` pick it up.
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'components'))
import ev2_pro as P  # noqa: E402

ap = argparse.ArgumentParser(description='Show or change work/look.json')
ap.add_argument('video_dir')
ap.add_argument('--accent')
ap.add_argument('--frame', choices=['inset', 'full'])
ap.add_argument('--max-zoom', type=float)
ap.add_argument('--inset', type=float)
ap.add_argument('--trim', choices=['auto', 'off'])
ap.add_argument('--click-sfx', dest='click_sfx', action='store_true', default=None)
ap.add_argument('--no-click-sfx', dest='click_sfx', action='store_false')
a = ap.parse_args()
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
if a.max_zoom:
    look['max_zoom'] = a.max_zoom
if a.inset:
    look['inset'] = a.inset
if a.trim:
    look['trim'] = a.trim
    look.pop('resolved_trim', None)
if a.click_sfx is not None:
    look['click_sfx'] = a.click_sfx
os.makedirs(os.path.dirname(lp), exist_ok=True)
json.dump(look, open(lp, 'w'), indent=2)
look, th = P.ensure_look(vd, force=force)
print(json.dumps(look, indent=2))
print(f'look: accent {th["accent"]} (gradient to {th["accent2"]}), backdrop assets/pro/bg.png')
