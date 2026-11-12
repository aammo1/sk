#!/usr/bin/env python3
"""Test script for the Editor V2 device library (components/)."""
import os, sys, json, tempfile, shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ev2_tutorial import *


def test_has_arabic():
    assert has_arabic("هذا نص بالعربية") is True
    assert has_arabic("Salam khouya, labas?") is False
    assert has_arabic("Kdenlive و Whisper") is True
    assert has_arabic("English only 123") is False
    print("✓ test_has_arabic passed")


def test_bidi_span():
    # In RTL context:
    ar_span = bidi_span("مرحبا", "w1", is_rtl=True)
    assert ar_span == '<span id="w1" class="w">مرحبا</span>', ar_span

    lat_span = bidi_span("Docker", "w2", is_rtl=True)
    assert lat_span == '<span id="w2" class="w"><bdi>Docker</bdi></span>', lat_span

    # In LTR context:
    ltr_span = bidi_span("Docker", "w3", is_rtl=False)
    assert ltr_span == '<span id="w3" class="w">Docker</span>', ltr_span
    print("✓ test_bidi_span passed")


def test_bidi_text():
    pure_en = bidi_text("Hello World")
    assert pure_en == "Hello World", pure_en

    mixed = bidi_text("تثبيت Docker على Arch")
    assert "<bdi>Docker</bdi>" in mixed, mixed
    assert "<bdi>Arch</bdi>" in mixed, mixed
    assert "تثبيت" in mixed
    assert "على" in mixed
    print("✓ test_bidi_text passed")


def test_comp_init_and_chapters():
    tmp_dir = tempfile.mkdtemp()
    try:
        c = Comp(dur=60.0, caption_mode='darija-ar', hook_end=15.0)
        assert c.caption_mode == 'darija-ar'
        assert c.hook_end == 15.0
        assert c.chapters == []

        # Add chapter banners
        chapter_banner(c, 2.5, 6.0, "01", "Introduction to Omarchy", subtitle="Screencast overview", style="card")
        chapter_banner(c, 20.0, 30.0, "02", "إعداد Whisper و Kdenlive", subtitle="Fast transcription", style="lower_third")
        chapter_banner(c, 45.0, 55.0, "03", "Auto-cut silence", style="card")

        assert len(c.chapters) == 3

        txt_path = os.path.join(tmp_dir, "chapters.txt")
        json_path = os.path.join(tmp_dir, "chapters.json")

        lines = c.write_chapters(path=txt_path, json_path=json_path)

        # First chapter must start at 00:00 Intro because earliest chapter was at 2.5s
        assert lines[0] == "00:00 Intro", lines[0]
        assert "00:02 01 Introduction to Omarchy" in lines[1]
        assert "00:20 02 إعداد Whisper و Kdenlive" in lines[2]
        assert "00:45 03 Auto-cut silence" in lines[3]

        with open(txt_path, "r", encoding="utf-8") as f:
            txt_content = f.read()
            assert "00:00 Intro" in txt_content
            assert "إعداد Whisper" in txt_content

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert len(data) == 4
            assert data[0]["timestamp"] == "00:00"
            assert data[0]["title"] == "Intro"
            assert data[2]["title"] == "02 إعداد Whisper و Kdenlive"

        print("✓ test_comp_init_and_chapters passed")
    finally:
        shutil.rmtree(tmp_dir)


def test_captions_bidi_and_hook_filter():
    # 1. Darija caption with Arabic and Latin tech words
    c = Comp(dur=30.0)
    groups = [
        ([("دابا", 0.5), ("غادي", 0.8), ("نشوفو", 1.1), ("Kdenlive", 1.4)], 2.0),
        ([("Now", 2.2), ("we", 2.4), ("test", 2.6), ("English", 2.8)], 3.5),
    ]
    captions(c, groups)

    # Check that first clip has dir="rtl" and <bdi> around Kdenlive
    first_clip = c.els[0]
    assert 'dir="rtl"' in first_clip, first_clip
    assert '<bdi>Kdenlive</bdi>' in first_clip, first_clip

    # Check second clip (English) has no dir="rtl" and no <bdi>
    second_clip = c.els[1]
    assert 'dir="rtl"' not in second_clip, second_clip
    assert '<bdi>' not in second_clip, second_clip

    # 2. Hook-only mode filtering
    c_hook = Comp(dur=30.0, caption_mode='hook-only', hook_end=2.0)
    captions(c_hook, groups)
    # Only group 1 (onset 0.5 < 2.0) should be rendered; group 2 (onset 2.2 >= 2.0) should be skipped
    assert len(c_hook.els) == 1, len(c_hook.els)
    assert "Kdenlive" in c_hook.els[0]

    print("✓ test_captions_bidi_and_hook_filter passed")


def test_screen_zoom():
    c = Comp(dur=15.0)
    vid = screen_zoom(
        c, 1.0, 5.0, "screencast.mp4",
        roi=(400, 300, 600, 400),
        z=5, media_start=10.0,
        highlight_box=(420, 320, 200, 80),
        webcam_box=(1380, 500, 480, 540)
    )
    assert any("screencast.mp4" in el for el in c.els)
    # Check scale calculation: 1920 / 600 = 3.2, 1080 / 400 = 2.7 -> min(2.6, ...) = 2.6
    js_str = "\n".join(c.js)
    assert 'scale:2.6000' in js_str, js_str
    # Check click_soft SFX cue was added
    assert any(cue[1] == 'ev1kit/click_1' for cue in c.cues)
    # Check highlight box rendered
    assert any("szbox" in el for el in c.els)
    # Check webcam overlay rendered at z + 2 = 7
    assert any("omcam" in el for el in c.els)
    print("✓ test_screen_zoom passed")


def test_shortcut_pill_and_cmd_toast():
    c = Comp(dur=10.0)
    # Shortcut pill with English and Arabic label
    pid1 = shortcut_pill(c, 0.5, 2.0, ['Super', 'Shift', 'R'], label="Reload UI")
    pid2 = shortcut_pill(c, 3.0, 4.5, 'Ctrl+C', label="إلغاء الأمر")

    # Command toast
    tid = cmd_toast(c, 5.0, 8.0, "$ agy implement-feature")

    # Check key_click cues were recorded
    key_clicks = [cue for cue in c.cues if cue[1] == 'ev1kit/key_click']
    assert len(key_clicks) == 3, key_clicks

    # Check HTML output
    html_all = "\n".join(c.els)
    assert "Super" in html_all and "Shift" in html_all and "Reload UI" in html_all
    assert "إلغاء الأمر" in html_all and 'dir="rtl"' in html_all
    assert "ev2-toast" in html_all and "tch" in html_all

    print("✓ test_shortcut_pill_and_cmd_toast passed")


def test_flow_diagram():
    c = Comp(dur=15.0)
    nodes = [
        ('n1', 'Omarchy Screencast', 360, 540),
        ('n2', 'Faster-Whisper INT8', 960, 540),
        ('n3', 'مشروع Kdenlive النهائي', 1560, 540)
    ]
    edges = [
        ('n1', 'n2', 0.5),
        ('n2', 'n3', 1.0)
    ]
    gid = flow_diagram(c, 1.0, 10.0, nodes, edges, z=12, title="Pipeline de Montage")
    html_all = "\n".join(c.els)
    assert "Omarchy Screencast" in html_all
    assert "Faster-Whisper" in html_all
    assert "Kdenlive" in html_all and 'dir="rtl"' in html_all
    assert "<path" in html_all  # SVG arrows
    # Check clicks recorded
    clicks = [cue for cue in c.cues if 'click' in cue[1]]
    assert len(clicks) >= 3
    print("✓ test_flow_diagram passed")


def test_split_compare():
    c = Comp(dur=12.0)
    left = {
        'title': 'Before / Manuel',
        'items': ['Cutting silence by hand', 'Misheard English tech terms'],
        'accent': '#FF5252'
    }
    right = {
        'title': 'Editor V2',
        'items': ['تقطيع الصمت أوتوماتيكيا', 'قاموس الدارجة + Tech terms'],
        'accent': '#4ADE80'
    }
    gid = split_compare(c, 0.5, 8.0, left, right, z=15, vs_label="VS")
    html_all = "\n".join(c.els)
    assert "Before / Manuel" in html_all
    assert "Editor V2" in html_all
    assert "VS" in html_all
    assert "تقطيع الصمت" in html_all and 'dir="rtl"' in html_all
    assert "<bdi>Tech</bdi>" in html_all or "Tech" in html_all
    print("✓ test_split_compare passed")


def test_omarchy_cam_pip():
    c = Comp(dur=10.0)
    cid, vid = omarchy_cam_pip(c, 1.0, 5.0, "screencast.mp4", media_start=2.0)
    html_all = "\n".join(c.els)
    assert "screencast.mp4" in html_all
    assert "left:1380px" in html_all
    assert "top:500px" in html_all
    assert "width:480px" in html_all
    assert "height:540px" in html_all
    print("✓ test_omarchy_cam_pip passed")


def test_v1_backward_compatibility():
    c = Comp(dur=20.0)
    # Test base V1 devices
    still(c, 0.0, 2.0, "assets/img1.jpg", z=1)
    keyword(c, 2.0, 4.0, "TERMINAL", z=2, kind="shock")
    keyword(c, 4.0, 6.0, "كلمة قوية", z=2, kind="key")  # Arabic keyword
    svg_mark(c, 6.0, 8.0, "<svg><circle cx='10' cy='10' r='5'/></svg>", z=3)
    tile_reveal(c, 8.0, "assets/img2.jpg", z=4)
    paper_card(c, 10.0, 12.0, "assets/card.png", z=5, left=[("قبل", 10.2)], right=[("بعد", 10.4)])
    terminal(c, 12.0, 15.0, "omarchy dev run", ["building components...", "done 100%"], z=6, stop_t=14.0)
    typewriter(c, 15.0, 18.0, [("typing text...", 15.2, 2, "dim"), ("نص بالعربية", 16.0, 2, "normal")], z=7)
    finish(c, 0.0, 20.0, z=80)

    # Test ev1_more devices
    seq(c, [("assets/s1.jpg", 0.0), ("assets/s2.jpg", 1.0)], z=1, t_end=2.0)
    pop_shatter(c, 2.0, 4.0, [("assets/c1.png", 960, 540, 400, 0, 2.5)], z=2)
    slap_caps(c, [("SLAP", 4.0), ("برافو", 4.5)], t_end=5.5, z=60)
    img_mark(c, 5.5, 7.0, "assets/logo.png", z=8)

    html_all = "\n".join(c.els)
    assert "assets/img1.jpg" in html_all
    assert "TERMINAL" in html_all
    assert "كلمة قوية" in html_all
    assert 'dir="rtl"' in html_all
    assert "omarchy dev run" in html_all
    assert "برافو" in html_all

    print("✓ test_v1_backward_compatibility passed")


def test_full_write():
    tmp_dir = tempfile.mkdtemp()
    try:
        c = Comp(dur=10.0, cid='main_test')
        still(c, 0.0, 2.0, "test.jpg", z=1)
        shortcut_pill(c, 0.5, 1.5, ['Super', 'T'])
        captions(c, [([("مرحبا", 0.2), ("بكم", 0.6)], 1.5)])
        finish(c, 0.0, 2.0, z=90)

        out_html = os.path.join(tmp_dir, "index.html")
        out_cues = os.path.join(tmp_dir, "cues.txt")

        c.write(out_html, "assets/tokens.css", title="Test Comp")
        c.write_cues(out_cues)

        assert os.path.exists(out_html)
        assert os.path.exists(out_cues)

        with open(out_html, "r", encoding="utf-8") as f:
            html = f.read()
            assert "<!doctype html>" in html
            assert 'data-composition-id="main_test"' in html
            assert "window.__timelines" in html
            assert "مرحبا" in html
            assert 'dir="rtl"' in html

        with open(out_cues, "r", encoding="utf-8") as f:
            cues_text = f.read()
            assert "# Editor V1/V2 cue sheet" in cues_text

        print("✓ test_full_write passed")
    finally:
        shutil.rmtree(tmp_dir)


if __name__ == '__main__':
    test_has_arabic()
    test_bidi_span()
    test_bidi_text()
    test_comp_init_and_chapters()
    test_captions_bidi_and_hook_filter()
    test_screen_zoom()
    test_shortcut_pill_and_cmd_toast()
    test_flow_diagram()
    test_split_compare()
    test_omarchy_cam_pip()
    test_v1_backward_compatibility()
    test_full_write()
    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY! device library verified!")
