"""inserts.py: the explainer inserts of this video.

An insert is a short animated scene (1.5-30 s) shown in the middle of the tutorial while your voice
keeps playing. Declare each one in work/timeline.json:

    "inserts": [{"name": "order-flow", "src_t": 135.2, "dur": 8, "mode": "full", "cam": true}]

  src_t  where it starts, in SOURCE seconds (like chapters)
  dur    its length in final seconds
  mode   "full" (opaque full-screen scene) or "over" (transparent animation over the dimmed screencast)
  cam    true keeps the webcam on top

Then write one @scene per insert below. Times inside a scene are LOCAL (0 = insert start).
words(ins) gives what is said during the insert; asset(key) reads work/assets.json;
hype_slide('slides.md', 3) gives a PNG of a Hype slide.

  ev2 inserts <dir>            build + render work/inserts/*
  ev2 finish <dir>             composite them into the body
  ev2 inserts <dir> --final    before publishing (refuses placeholders and example())

For mode "over" use devices without their own black backdrop (keyword, typewriter, ...): devices that
draw an ev1-black layer (flow_diagram, terminal, ...) make the insert opaque; use mode "full" for them.

Devices catalogue: reference/devices.md
"""
import json, os, sys

KIT = json.load(open('kit.json'))['skill']
sys.path.insert(0, os.path.join(KIT, 'components'))
from ev2_tutorial import *          # noqa: every device (reference/devices.md)
from ev2_inserts import scene, run, words, asset, ph, example, hype_slide


@scene('order-flow')
def order_flow(c, ins):
    """Example (replace): a three-step flow drawn while you explain it."""
    d = ins['dur']
    flow_diagram(c, 0.2, d - 0.2,
                 nodes=[('a', 'Boutique', 360, 540), ('b', 'Commande', 960, 540), ('c', 'Livraison', 1560, 540)],
                 edges=[('a', 'b', 0.9), ('b', 'c', 1.8)], title='كيفاش كتمشي الطلبية')
    example('order-flow diagram nodes/title')


# A Hype slide as the picture of an insert (needs `hype`):
# @scene('pricing-slide')
# def pricing_slide(c, ins):
#     png = hype_slide('slides.md', 3)
#     if png:
#         still(c, 0, ins['dur'], png, 1)
#     else:
#         ph(c, 0, ins['dur'], 'pricing slide (hype render failed)')

run()
