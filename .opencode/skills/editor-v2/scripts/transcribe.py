#!/usr/bin/env python3
"""transcribe.py — word timings for the take, checked for dropped speech.

Supports faster-whisper primary engine (on CPU with int8 quantization) and
HyperFrames windowed loop fallback. Default initial prompt is tailored for
Moroccan Darija + English tech code-switching.

Usage:
    transcribe.py <video-dir> [--src vo.wav] [--language ar|en|fr|auto] [--model large-v3-turbo|small|base] [--engine fw|hf]

Writes work/tx/words_raw.json (fresh every run), work/tx/words.json (working copy),
work/tx/transcript.txt and work/tx/engine.json. Personal term fixes: ~/.config/editor-v2/darija-terms.json
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ev2_timeline as TL  # noqa: E402

# Auto-locate environment Python if launched from bare interpreter lacking faster_whisper / dependencies
try:
    import faster_whisper
    import numpy as np
except ImportError:
    for candidate in [
        os.environ.get('EV2_PY'),
        os.environ.get('EV1_PY'),
        os.path.expanduser('~/.cache/editor-v2/venv/bin/python'),
    ]:
        if candidate and os.path.isfile(candidate) and os.path.realpath(candidate) != os.path.realpath(sys.executable):
            os.execv(candidate, [candidate] + sys.argv)
    # If still missing, we might only have standard libraries; faster_whisper won't be available
    try:
        import numpy as np
    except ImportError:
        np = None

WIN, OVL = 20.0, 2.0

DARIJA_TECH_PROMPT = (
    "هاد الفيديو غانشوفو كيفاش نخدمو بـ Claude Code و Antigravity agy و OpenCode و DeepSeek dsh "
    "على Linux Omarchy و Hyprland. غانديرو setup لـ Docker, MCP, Git, GitHub, API, Python, "
    "Next.js, TypeScript, FFmpeg, Kdenlive, terminal, skill."
)

TECH_MAP_PHRASES = [
    # Multi-token phrases (checked in descending token length order)
    (['اف', 'اف', 'ام', 'بيج'], 'FFmpeg'),
    (['إف', 'إف', 'إم', 'بيج'], 'FFmpeg'),
    (['اف', 'اف', 'امبيج'], 'FFmpeg'),
    (['أومارشي', 'لينكس'], 'Omarchy Linux'),
    (['اومارشي', 'لينكس'], 'Omarchy Linux'),
    (['جيت', 'هاب'], 'GitHub'),
    (['أوبن', 'كود'], 'OpenCode'),
    (['اوبن', 'كود'], 'OpenCode'),
    (['ديب', 'سيك'], 'DeepSeek'),
    (['تايب', 'سكريبت'], 'TypeScript'),
]

TECH_MAP_WORDS = {
    'كلود': 'Claude',
    'دوكر': 'Docker',
    'لينكس': 'Linux',
    'جيت هاب': 'GitHub',
    # NOT 'جيت' -> Git: جيت is everyday Darija for "I came". Say "Git" in a phrase the map knows,
    # or add your own entries to ~/.config/editor-v2/darija-terms.json.
    'بايثون': 'Python',
    'تيرمينال': 'Terminal',
    'أومارشي لينكس': 'Omarchy Linux',
    'اومارشي لينكس': 'Omarchy Linux',
    'أومارشي': 'Omarchy',
    'اومارشي': 'Omarchy',
    'هايبرلاند': 'Hyprland',
    'أنتيغرافيتي': 'Antigravity',
    'انتيغرافيتي': 'Antigravity',
    'أوبن كود': 'OpenCode',
    'اوبن كود': 'OpenCode',
    'أوبنكود': 'OpenCode',
    'ديب سيك': 'DeepSeek',
    'ديبسيك': 'DeepSeek',
    'نيكست جي اس': 'Next.js',
    'تايب سكريبت': 'TypeScript',
    'تايبسكريبت': 'TypeScript',
    'اف اف ام بيج': 'FFmpeg',
    'إف إف إم بيج': 'FFmpeg',
    'اف اف امبيج': 'FFmpeg',
    'كدينلايف': 'Kdenlive',
    'واتساب': 'WhatsApp',
    'داشبورد': 'Dashboard',
    # French UI / e-commerce terms (Darija code-switches into French too)
    'كوماند': 'commande', 'كماند': 'commande', 'كوموند': 'commande',
    'كوماندات': 'commandes', 'كماندات': 'commandes',
    'ليفريزون': 'livraison', 'ليفغيزون': 'livraison',
    'بوتيك': 'boutique',
    'ستوك': 'stock',
    'ريتور': 'retour', 'ريتورات': 'retours',
    'اكسبيديسيون': 'expédition', 'إكسبيديسيون': 'expédition', 'اكسبيديسيو': 'expédition',
    'فاكتور': 'facture', 'فاكتورة': 'facture',
    'تابلو دو بور': 'Tableau de bord', 'تابلو دبور': 'Tableau de bord',
}

# Spelled-out Latin terms the decoder is nudged towards in EVERY 30 s window (faster-whisper
# `hotwords`). The initial prompt only reaches the first window when condition_on_previous_text
# is off. Extend with EV2_HOTWORDS="Vercel, Supabase" or ~/.config/editor-v2/darija-terms.json.
HOTWORDS = ['Claude Code', 'OpenCode', 'Omarchy', 'Hyprland', 'Linux', 'Docker', 'GitHub', 'Git', 'Python',
            'TypeScript', 'Next.js', 'FFmpeg', 'terminal', 'API', 'MCP', 'AI', 'WhatsApp',
            'commande', 'livraison', 'boutique', 'stock', 'expédition', 'retour', 'facture']

# Attached prefixes: Darija/Arabic clitics glued to a borrowed word (بالكوماند -> بالـ commande).
PREFIXES = ['وال', 'بال', 'فال', 'كال', 'لل', 'ال', 'بـ', 'لـ', 'فـ', 'وـ', 'ب', 'ل', 'و', 'ف']


def sync_phrases():
    """Multi-word keys can only match across tokens: keep them in TECH_MAP_PHRASES too."""
    have = {tuple(p) for p, _ in TECH_MAP_PHRASES}
    for k, v in TECH_MAP_WORDS.items():
        toks = tuple(k.split())
        if len(toks) > 1 and toks not in have:
            TECH_MAP_PHRASES.append((list(toks), v))
            have.add(toks)
    TECH_MAP_PHRASES.sort(key=lambda x: -len(x[0]))


sync_phrases()


USER_TERMS = os.path.expanduser(os.environ.get('EV2_TERMS', '~/.config/editor-v2/darija-terms.json'))


def load_user_terms():
    """Merge the creator's own transliteration fixes: {"ديفوبس": "DevOps", "فيرسل": "Vercel"}.
    Keys with spaces become multi-word phrases. Grows into a personal Darija tech lexicon."""
    if not os.path.isfile(USER_TERMS):
        return 0
    try:
        extra = json.load(open(USER_TERMS, encoding='utf-8'))
    except Exception as e:
        print(f'transcribe: WARNING could not read {USER_TERMS}: {e}', file=sys.stderr)
        return 0
    for k, v in extra.items():
        TECH_MAP_WORDS[k] = v
        if re.search(r'[A-Za-z]', v) and v not in HOTWORDS:
            HOTWORDS.append(v)
    sync_phrases()
    return len(extra)


def hotwords_text():
    extra = [w.strip() for w in os.environ.get('EV2_HOTWORDS', '').split(',') if w.strip()]
    return ', '.join(dict.fromkeys(HOTWORDS + extra))


def normalize_ar_token(t):
    """Normalize Arabic word for dictionary comparison."""
    if not t:
        return ""
    # Strip non-alphanumeric punctuation
    t = re.sub(r'^[^\w\u0600-\u06FF]+|[^\w\u0600-\u06FF]+$', '', t)
    # Strip diacritics and tatweel
    t = re.sub(r'[\u064B-\u065F\u0670ـ]', '', t)
    # Normalize alef variants
    t = re.sub(r'[إأآ]', 'ا', t)
    t = re.sub(r'ة', 'ه', t)
    t = re.sub(r'ى', 'ي', t)
    return t.strip()


def fix_tech_terms(word):
    """Map common Arabic script transliterations of tech keywords back to clean Latin tech terms."""
    if not word:
        return word

    # Extract leading / trailing punctuation
    m = re.match(r'^([^\w\u0600-\u06FF]*)([\w\u0600-\u06FF\s.-]+?)([^\w\u0600-\u06FF]*)$', word)
    if not m:
        pfx, core, sfx = '', word, ''
    else:
        pfx, core, sfx = m.group(1), m.group(2).strip(), m.group(3)

    norm_core = normalize_ar_token(core)

    # 1. Exact or normalized core match
    for k, v in TECH_MAP_WORDS.items():
        if core == k or norm_core == normalize_ar_token(k):
            return f"{pfx}{v}{sfx}"

    # 2. Attached clitics: ال / بال / لل ... and بـ لـ فـ وـ / ب ل و ف (longest first)
    for ap in PREFIXES:
        if core.startswith(ap) and len(core) > len(ap) + 1:
            rem = core[len(ap):]
            norm_rem = normalize_ar_token(rem)
            for k, v in TECH_MAP_WORDS.items():
                if ' ' not in k and (rem == k or norm_rem == normalize_ar_token(k)):
                    glue = ap if ap.endswith('ـ') else ap + 'ـ'
                    return f"{pfx}{glue} {v}{sfx}"

    return word


def post_process_words(raw_words):
    """
    Given a list of (word_str, start, end) tuples, merges multi-word tech terms
    and applies fix_tech_terms to single words.
    Returns list of dicts: [{"w": word, "s": round(s, 3), "e": round(e, 3)}].
    """
    if not raw_words:
        return []

    processed = []
    i = 0
    n = len(raw_words)

    while i < n:
        matched = False
        # Check multi-word phrase patterns
        for phrase_tokens, replacement in TECH_MAP_PHRASES:
            plen = len(phrase_tokens)
            if i + plen <= n:
                window_tokens = [normalize_ar_token(raw_words[i + j][0]) for j in range(plen)]
                target_tokens = [normalize_ar_token(tok) for tok in phrase_tokens]
                if window_tokens == target_tokens:
                    s_time = raw_words[i][1]
                    e_time = raw_words[i + plen - 1][2]
                    processed.append({'w': replacement, 's': round(s_time, 3), 'e': round(e_time, 3)})
                    i += plen
                    matched = True
                    break

        if matched:
            continue

        # Single word processing
        w_raw, s_time, e_time = raw_words[i]
        w_fixed = fix_tech_terms(w_raw)
        processed.append({'w': w_fixed, 's': round(s_time, 3), 'e': round(e_time, 3)})
        i += 1

    return processed


def run_cmd(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def duration(p):
    res = run_cmd(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', p])
    return float(res.stdout.strip())


def rms_100ms(src):
    """Calculate 100ms RMS energy across the audio track to detect dropped speech."""
    if np is None:
        return []
    try:
        raw = subprocess.run(
            ['ffmpeg', '-nostdin', '-v', 'error', '-i', src, '-ac', '1', '-ar', '16000', '-f', 's16le', '-'],
            capture_output=True, check=True
        ).stdout
        x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
        n = len(x) // 1600
        if n == 0:
            return np.array([])
        return 20 * np.log10(np.sqrt((x[:n * 1600].reshape(n, 1600) ** 2).mean(1)) + 1e-9)
    except Exception as e:
        print(f"Warning: rms_100ms computation failed: {e}", file=sys.stderr)
        return np.array([])


def fw_transcribe(model, audio, **kw):
    """model.transcribe with hotwords, dropping them on faster-whisper versions without support."""
    try:
        return model.transcribe(audio, **kw)
    except TypeError as e:
        if 'hotwords' not in str(e) or 'hotwords' not in kw:
            raise
        kw.pop('hotwords')
        print('  (this faster-whisper has no hotwords support: upgrade with `ev2 doctor --install-speech`)',
              file=sys.stderr)
        return model.transcribe(audio, **kw)


def transcribe_fw(model, src, D, lang_arg, initial_prompt, windowed=False, hotwords=None):
    """Transcribe using faster-whisper, either directly or in 20s overlapping windows."""
    lang = None if (not lang_arg or lang_arg == 'auto') else lang_arg
    words = []

    if windowed:
        tmp = tempfile.mkdtemp(prefix='ev2tx-fw-')
        try:
            starts = [0.0] if D <= WIN + 1 else list(np.arange(0, D - OVL, WIN - OVL))
            for k, ss in enumerate(starts):
                t = min(WIN, D - ss)
                chunk_wav = os.path.join(tmp, f'chunk_{k:04d}.wav')
                subprocess.run([
                    'ffmpeg', '-nostdin', '-v', 'error', '-y',
                    '-ss', f'{ss:.3f}', '-t', f'{t:.3f}',
                    '-i', src, '-ac', '1', '-ar', '16000', chunk_wav
                ], check=True)
                segments, info = fw_transcribe(
                    model, chunk_wav,
                    word_timestamps=True,
                    vad_filter=True,
                    initial_prompt=initial_prompt,
                    hotwords=hotwords,
                    language=lang,
                )
                if lang is None:
                    # detect ONCE and lock it: per-window detection drifts (Darija came out as Czech/Romanian)
                    lang = info.language
                    print(f'  language auto-detected on the first window: {lang} (locked for all windows)', file=sys.stderr)
                got = []
                for seg in segments:
                    if seg.words:
                        for w in seg.words:
                            txt = w.word.strip()
                            if txt:
                                got.append((txt, w.start + ss, w.end + ss))
                lo = 0.0 if k == 0 else ss + OVL / 2
                hi = D + 1.0 if k == len(starts) - 1 else ss + WIN - OVL / 2
                words += [w for w in got if lo <= w[1] < hi]
                print(f'  window {k + 1}/{len(starts)}  {ss:6.1f}-{ss + t:6.1f}s  {len(got)} words', file=sys.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    else:
        # Whole file in one pass: Whisper keeps context across sentences and there are no window
        # seams. condition_on_previous_text=False stops repetition loops ("I have a lot of work..." x N).
        segments, info = fw_transcribe(
            model, src,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={'min_silence_duration_ms': 500},
            initial_prompt=initial_prompt,
            hotwords=hotwords,
            language=lang,
            beam_size=5,
            condition_on_previous_text=False,
            hallucination_silence_threshold=2.0,
        )
        print(f'  language: {info.language} ({"forced" if lang else "detected"})', file=sys.stderr)
        last = -1
        for seg in segments:
            if int(seg.end) // 30 > last:
                last = int(seg.end) // 30
                print(f'  {seg.end:7.1f}s / {D:.1f}s', file=sys.stderr, flush=True)
            if seg.words:
                for w in seg.words:
                    txt = w.word.strip()
                    if txt:
                        words.append((txt, w.start, w.end))

    return words


def transcribe_hf(src, D, lang_arg):
    """Fallback engine using npx hyperframes transcribe windowed loop."""
    tmp = tempfile.mkdtemp(prefix='ev2tx-hf-')
    words = []
    lang = None if (not lang_arg or lang_arg == 'auto') else lang_arg
    hf_version = os.environ.get('HF_VERSION', '0.8.181')

    try:
        starts = [0.0] if D <= WIN + 1 else list(np.arange(0, D - OVL, WIN - OVL))
        for k, ss in enumerate(starts):
            t = min(WIN, D - ss)
            d = tempfile.mkdtemp(dir=tmp)
            clip = os.path.join(d, 'clip.mp4')
            subprocess.run([
                'ffmpeg', '-nostdin', '-v', 'error', '-y',
                '-f', 'lavfi', '-i', 'color=c=black:s=320x180:r=10',
                '-ss', f'{ss:.3f}', '-t', f'{t:.3f}', '-i', src,
                '-map', '0:v', '-map', '1:a:0', '-shortest',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '40',
                '-c:a', 'aac', '-b:a', '128k', '-ac', '1', '-ar', '16000', clip
            ], check=True)

            cmd = ['npx', '-y', f'hyperframes@{hf_version}', 'transcribe', clip, '-d', d, '--json']
            if lang:
                cmd += ['--language', lang]
            res_raw = run_cmd(cmd).stdout.strip().splitlines()[-1]
            res = json.loads(res_raw)
            transcript_path = res.get('transcriptPath') or os.path.join(d, 'transcript.json')
            raw_w = json.load(open(transcript_path))
            got = [(w['text'].strip(), w['start'] + ss, w['end'] + ss) for w in raw_w if w.get('text', '').strip()]

            lo = 0.0 if k == 0 else ss + OVL / 2
            hi = D + 1.0 if k == len(starts) - 1 else ss + WIN - OVL / 2
            words += [w for w in got if lo <= w[1] < hi]
            print(f'  [HF] window {k + 1}/{len(starts)}  {ss:6.1f}-{ss + t:6.1f}s  {len(got)} words', file=sys.stderr)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return words


def main():
    ap = argparse.ArgumentParser(description="transcribe.py — transcribe audio/video with faster-whisper or HyperFrames fallback.")
    ap.add_argument('video_dir', help="Video project directory containing assets/media/vo.wav")
    ap.add_argument('--src', default=None, help="Source audio/video file (default: <video-dir>/assets/media/vo.wav)")
    ap.add_argument('--language', default=os.environ.get('EV2_LANGUAGE', 'ar'), choices=['ar', 'en', 'fr', 'auto'],
                    help="Spoken language (default: ar, right for Darija; English terms are transliterated, then "
                         "normalized back to Latin). 'auto' detects once and locks it.")
    ap.add_argument('--model', default=os.environ.get('EV2_WHISPER_MODEL', 'large-v3-turbo'),
                    help="Whisper model: tiny|base|small|medium|large-v3|large-v3-turbo, a Hugging Face "
                         "CTranslate2 repo id (e.g. a Darija fine-tune) or a local model dir. Default "
                         "large-v3-turbo or $EV2_WHISPER_MODEL. base/small are fast drafts, weak on Darija.")
    ap.add_argument('--engine', default='fw', choices=['fw', 'hf'], help="Engine: fw (faster-whisper) or hf (hyperframes)")
    ap.add_argument('--windowed', action='store_true', help="Force 20s overlapping window transcription")
    ap.add_argument('--force', action='store_true',
                    help="Overwrite a hand-corrected work/tx/words.json (a timestamped backup is kept)")
    a = ap.parse_args()

    vd = os.path.abspath(a.video_dir)

    # Never silently throw away transcript corrections made at the PLAN gate.
    edited = TL.words_edited(vd)
    words_file = TL.words_paths(vd)[0]
    if edited and not a.force:
        why = ('was edited since the last transcription' if edited is True
               else 'exists and may contain hand corrections (no record of the last automatic write)')
        sys.exit(f'transcribe: {words_file} {why}.\n'
                 f'  Re-running would replace it. To do that anyway: ev2 transcribe {a.video_dir} --force\n'
                 f'  (the current file is kept as words.json.bak-<time>).')
    if edited and a.force:
        bak = f'{words_file}.bak-{time.strftime("%Y%m%d-%H%M%S")}'
        shutil.copyfile(words_file, bak)
        print(f'transcribe: kept your edited transcript as {bak}')
    if a.src:
        if os.path.isabs(a.src) or os.path.isfile(a.src):
            src = a.src
        else:
            src = os.path.join(vd, a.src)
    else:
        src = os.path.join(vd, 'assets', 'media', 'vo.wav')

    if not os.path.isfile(src):
        # Check alternative common locations
        alt_paths = [
            os.path.join(vd, 'work', 'vo.wav'),
            os.path.join(vd, 'vo.wav'),
            os.path.join(vd, 'assets', 'media', 'src.mp4'),
        ]
        found = False
        for alt in alt_paths:
            if os.path.isfile(alt):
                src = alt
                found = True
                break
        if not found:
            sys.exit(f'transcribe: no such audio/media file: {src}')

    D = duration(src)
    print(f'transcribing: {src} ({D:.1f}s)')

    use_fw = False
    if a.engine == 'fw':
        try:
            import faster_whisper
            use_fw = True
        except ImportError:
            print("faster_whisper not available; falling back to HyperFrames engine.", file=sys.stderr)
            use_fw = False

    raw_words = []
    engine_name = 'unknown'

    # Personal terms first: their Latin spellings also become hotwords for the decoder
    n_user = load_user_terms()
    if n_user:
        print(f'transcribe: {n_user} personal terms from {USER_TERMS}')
    hot = hotwords_text() if a.language != 'en' else None

    if use_fw:
        engine_name = f'faster-whisper ({a.model}, int8-cpu)'
        print(f'Loading WhisperModel({a.model}, device="cpu", compute_type="int8")...')
        model = faster_whisper.WhisperModel(a.model, device="cpu", compute_type="int8",
                                            cpu_threads=os.cpu_count() or 4)
        raw_words = transcribe_fw(
            model, src, D,
            lang_arg=a.language,
            initial_prompt=DARIJA_TECH_PROMPT,
            windowed=a.windowed,
            hotwords=hot,
        )
    else:
        engine_name = 'hyperframes'
        raw_words = transcribe_hf(src, D, a.language)

    raw_words.sort(key=lambda w: w[1])

    # Post-process tech terms and phonetic normalization
    words = post_process_words(raw_words)
    words.sort(key=lambda w: w['s'])

    # Write output files
    out_dir = os.path.join(vd, 'work', 'tx')
    os.makedirs(out_dir, exist_ok=True)
    transcript_file = os.path.join(out_dir, 'transcript.txt')

    # words_raw.json = this transcription before onset snapping (always rewritten, never stale);
    # words.json = the working copy that snap-onsets.py and your manual corrections edit in place.
    for path in (os.path.join(out_dir, 'words_raw.json'), words_file):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(words, f, indent=2, ensure_ascii=False)
    TL.stamp_words(vd)
    with open(os.path.join(out_dir, 'engine.json'), 'w') as f:
        json.dump({'engine': engine_name, 'model': a.model if use_fw else None, 'language': a.language,
                   'hotwords': hot if use_fw else None, 'windowed': bool(a.windowed),
                   'source': os.path.relpath(src, vd), 'words': len(words)}, f, indent=2, ensure_ascii=False)

    full_text = ' '.join(w['w'] for w in words)
    # Break into sentences on punctuation
    sentences = re.sub(r'([.?!،؟])\s+', r'\1\n', full_text)
    with open(transcript_file, 'w', encoding='utf-8') as f:
        f.write(sentences.strip() + '\n')

    print(f'transcribe: {len(words)} words, engine: {engine_name}, {D:.1f}s -> {words_file}')

    # Dropped-speech verification: check if speech-level audio has no word for > 1.5s
    if np is not None and D > 0:
        r = rms_100ms(src)
        if len(r) > 0:
            speech = r > np.percentile(r, 95) - 20
            covered = np.zeros(len(r), bool)
            for w in words:
                s_idx = max(0, int(w['s'] * 10))
                e_idx = min(len(covered) - 1, int(w['e'] * 10))
                covered[s_idx:e_idx + 1] = True
            gaps, run_len = [], 0
            for i, (sp, cv) in enumerate(zip(speech, covered)):
                run_len = run_len + 1 if (sp and not cv) else 0
                if run_len == 15:
                    gaps.append(i / 10.0 - 1.4)
            for g in gaps:
                print(f'  CHECK {g:6.1f}s: speech-level audio with no words for 1.5s+ (a dropped span?)')
            if not gaps:
                print('  no dropped spans found')


if __name__ == '__main__':
    main()
