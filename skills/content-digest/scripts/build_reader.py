#!/usr/bin/env python3
"""Render a local ContentDigest reading page from a verified transcript."""
from __future__ import annotations

import argparse
import copy
import html
import json
import math
import os
import re
from pathlib import Path
import unicodedata
from urllib.parse import urlparse

TEMPLATE = Path(__file__).resolve().parents[1] / 'assets/reader.html'


def normalized(text):
    return ''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith('P'))


def require_text(value, label, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f'{label} must be non-empty text')


def build(data_path, output=None):
    data_path = Path(data_path).resolve()
    folder = data_path.parent
    data = copy.deepcopy(json.loads(data_path.read_text()))
    transcript = json.loads((folder / 'transcript.json').read_text())
    index = json.loads((folder / 'reading-index.json').read_text())
    state = json.loads((folder / 'task-state.json').read_text())
    if state.get('status') not in {'transcribed', 'text_imported'}:
        raise ValueError('A full transcription or imported text is required; a sample cannot be summarized as a complete episode.')
    expected = [part['part'] for part in index]
    if not expected or data.get('read_parts') != expected:
        raise ValueError('read_parts must cover all read index parts in order.')
    for field in ('title', 'subtitle', 'thesis'):
        require_text(data.get(field), field)
    for field in ('events', 'insights', 'quotes', 'chapters', 'notes'):
        if not isinstance(data.get(field), list):
            raise ValueError(f'{field} must be an array')
    if not data['insights']:
        raise ValueError('At least one supported insight is required.')
    meta = transcript['metadata']
    duration = state.get('audio_duration')
    url = meta.get('source_url', '')
    if url:
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.username or parsed.password:
            raise ValueError('The source URL must use HTTPS without embedded credentials.')
    segments = transcript['segments']

    def attach_ref(ref):
        if ref is None:
            return
        if not isinstance(ref, dict) or duration is None:
            raise ValueError('Use ref: null when original timestamps are unavailable.')
        start, end = ref.get('start'), ref.get('end')
        if (not all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in (start, end))
                or not 0 <= start < end <= duration):
            raise ValueError(f'Reference is outside the source duration: {ref}')
        nearby = [s for s in segments if isinstance(s.get('start'), (float, int))
                  and s['end'] > start and s['start'] < min(end, start + 40)]
        ref['excerpt'] = ' '.join(s['text'] for s in nearby)
        ref['excerpt_start'] = min((s['start'] for s in nearby), default=start)
        ref['excerpt_end'] = max((s['end'] for s in nearby), default=min(end, start + 40))

    visible = [data['title'], data['subtitle'], data['thesis']]
    for event in data['events']:
        for key in ('title', 'text'):
            require_text(event.get(key), 'event.' + key)
            visible.append(event[key])
        if type(event.get('insight')) is not int or not 1 <= event['insight'] <= len(data['insights']):
            raise ValueError('Each topic must point to an existing insight.')
    for point in data['insights']:
        if point.get('kind') not in {'Speaker view', 'Source statement'}:
            raise ValueError('kind must be Speaker view or Source statement.')
        for key in ('title', 'claim', 'example', 'limit'):
            require_text(point.get(key), 'insight.' + key, key == 'limit')
            visible.append(point[key])
        attach_ref(point.get('ref'))
        if not isinstance(point.get('details'), list):
            raise ValueError('details must be an array.')
        for detail in point['details']:
            for key in ('title', 'text'):
                require_text(detail.get(key), 'detail.' + key)
            attach_ref(detail.get('ref'))
    for quote in data['quotes']:
        require_text(quote.get('text'), 'quote.text')
        attach_ref(quote.get('ref'))
        ref = quote.get('ref')
        candidates = segments if ref is None else [s for s in segments if isinstance(s.get('start'), (int, float))
                        and s['end'] > ref['start'] and s['start'] < ref['end']]
        original = normalized(' '.join(s['text'] for s in candidates))
        if not normalized(quote['text']) or normalized(quote['text']) not in original:
            raise ValueError('Quote does not match the referenced transcript; do not present a rewrite as a quotation.')
        visible.append(quote['text'])
    previous_end = 0
    for chapter in data['chapters']:
        for key in ('title', 'text'):
            require_text(chapter.get(key), 'chapter.' + key)
        attach_ref(chapter.get('ref'))
        if chapter.get('ref') is None or chapter['ref']['start'] < previous_end:
            raise ValueError('Chapters must be chronological and non-overlapping.')
        previous_end = chapter['ref']['end']
    for note in data['notes']:
        require_text(note, 'note')
    count = sum(len(''.join(t.split())) for t in visible)
    visible_text = ' '.join(visible)
    cjk_count = len(re.findall(r'[\u3400-\u9fff]', visible_text))
    word_count = len(re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", visible_text))
    minutes = max(1, math.ceil(cjk_count / 400 + word_count / 220))
    dest = Path(output).resolve() if output else folder / 'ContentDigest.html'
    data.update(source={'title': meta.get('title', data['title']), 'series': meta.get('series') or 'Content review',
                        'url': url, 'duration': duration,
                        'source_type': meta.get('source_type', 'local_asr')},
                reading_characters=count, reading_words=word_count, reading_minutes=minutes,
                transcript_file=Path(os.path.relpath(folder / 'transcript.md', dest.parent)).as_posix()
                if (folder / 'transcript.md').exists() else None)
    encoded = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    for char, escaped in [('<', '\\u003c'), ('>', '\\u003e'), ('&', '\\u0026'), ('\u2028', '\\u2028'), ('\u2029', '\\u2029')]:
        encoded = encoded.replace(char, escaped)
    page = TEMPLATE.read_text().replace('__CD_TITLE__', html.escape(data['title'] + ' · ContentDigest'))
    page = page.replace('__CD_DATA__', encoded)
    dest = Path(output).resolve() if output else folder / 'ContentDigest.html'
    if dest in {data_path, *(folder / name for name in ('transcript.json', 'task-state.json', 'reading-index.json', 'transcript.txt', 'transcript.md', 'transcript.srt'))}:
        raise ValueError('Output must not overwrite source data.')
    dest.write_text(page)
    return {'page': str(dest), 'visible_characters': count, 'reading_minutes': data['reading_minutes'],
            'insights': len(data['insights']), 'chapters': len(data['chapters']), 'quotes': len(data['quotes'])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.data, args.output), ensure_ascii=False))
