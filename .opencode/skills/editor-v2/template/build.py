"""build.py — the hook, designed automatically (components/ev2_hook.py).

You do not write code here. Edit work/hook.json instead (`ev2 hook <dir> --init` creates it with
the best moments of the recording already picked):

    {"recipe": "showcase", "promise": "one strong line, *word* = accent", "brand": "...",
     "title": "...", "shots": [{"src_t": 150.0, "label": "...", "icon": "..."}], "agenda": true}

then `ev2 hook <dir>` (or `ev2 build <dir>`), and `ev2 hook <dir> --final` before `ev2 finish`.
Colours, framing and zoom live in work/look.json (shared with the body and the inserts).
Full manual control (the old device-by-device hook): `ev2 style <dir> custom`.
"""
import json, os, sys

KIT = json.load(open('kit.json'))['skill']
sys.path.insert(0, os.path.join(KIT, 'components'))
import ev2_hook  # noqa: E402

sys.exit(ev2_hook.main(['.'] + (['--final'] if os.environ.get('FINAL') == '1' else [])))
