#!/usr/bin/env python3
"""kdenlive-gen.py — MLT XML .kdenlive project for an Editor V2 video (optional editor).

V1 holds out/final.mp4 (polished picture + finished sound) split at every cut: the hook,
then one entry per kept body segment, so the cut points are visible and adjustable.
Guides: chapters from work/chapters.json (written by finish.py, final-video times).

Usage:
  kdenlive-gen.py <video-dir> [--out out/project.kdenlive]
"""
import argparse, json, os, sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ev2_timeline as TL  # noqa: E402

PROFILE = {'width': '1920', 'height': '1080', 'frame_rate_num': str(TL.FPS), 'frame_rate_den': '1',
           'sample_aspect_num': '1', 'sample_aspect_den': '1', 'display_aspect_num': '16',
           'display_aspect_den': '9', 'progressive': '1', 'colorspace': '709'}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('video_dir')
    ap.add_argument('--out', default='out/project.kdenlive')
    a = ap.parse_args()

    vd = os.path.abspath(a.video_dir)
    tl = TL.load(vd)
    segs = TL.body_segments(tl)
    NH = TL.frames(tl['hook_split'])
    final = os.path.join(vd, 'out', 'final.mp4')
    if not os.path.isfile(final):
        sys.exit('kdenlive-gen: out/final.mp4 missing (run `ev2 finish` first)')

    root = ET.Element('mlt', {'LC_NUMERIC': 'C', 'version': '7.24.0', 'title': 'editor-v2', 'producer': 'main_bin'})
    ET.SubElement(root, 'profile', PROFILE)
    prod = ET.SubElement(root, 'producer', {'id': 'final'})
    for k, v in (('resource', final), ('mlt_service', 'avformat'), ('kdenlive:clipname', 'final.mp4')):
        ET.SubElement(prod, 'property', {'name': k}).text = v
    bin_ = ET.SubElement(root, 'playlist', {'id': 'main_bin'})
    ET.SubElement(bin_, 'property', {'name': 'kdenlive:folderid'}).text = '1'
    ET.SubElement(bin_, 'entry', {'producer': 'final'})

    v1 = ET.SubElement(root, 'playlist', {'id': 'playlist_v1'})
    ET.SubElement(v1, 'property', {'name': 'kdenlive:track_name'}).text = 'V1 Final (split at cuts)'
    if NH:
        ET.SubElement(v1, 'entry', {'producer': 'final', 'in': '0', 'out': str(NH - 1)})
    pos = NH
    for s in segs:
        n = s['f_end'] - s['f_start']
        ET.SubElement(v1, 'entry', {'producer': 'final', 'in': str(pos), 'out': str(pos + n - 1)})
        pos += n

    tractor = ET.SubElement(root, 'tractor', {'id': 'maintractor', 'title': 'Timeline'})
    ET.SubElement(ET.SubElement(tractor, 'multitrack'), 'track', {'producer': 'playlist_v1'})
    guides = []
    ch = os.path.join(vd, 'work', 'chapters.json')
    if os.path.isfile(ch):
        guides = [{'pos': TL.frames(c['time']), 'comment': c.get('title', ''), 'type': 0}
                  for c in json.load(open(ch, encoding='utf-8'))]
    ET.SubElement(tractor, 'property', {'name': 'kdenlive:docproperties.guides'}).text = json.dumps(guides, ensure_ascii=False)

    out = a.out if os.path.isabs(a.out) else os.path.join(vd, a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    ET.indent(root, space='  ')
    ET.ElementTree(root).write(out, encoding='utf-8', xml_declaration=True)
    ET.parse(out)
    print(f'kdenlive-gen: {out}')
    print(f'  V1 {1 if NH else 0} hook + {len(segs)} body entries = {pos} frames ({pos / TL.FPS:.2f}s); {len(guides)} guides')


if __name__ == '__main__':
    main()
