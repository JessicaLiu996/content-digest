#!/usr/bin/env python3
"""Import an existing TXT or SRT transcript without inventing timestamps."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlparse


def seconds(value):
    hours, minutes, rest = value.replace(',', '.').split(':')
    if int(minutes) >= 60 or float(rest) >= 60:
        raise ValueError('Invalid SRT timestamp.')
    return int(hours) * 3600 + int(minutes) * 60 + float(rest)


def import_text(source, output, title, source_url=''):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source.suffix.lower() not in {'.txt', '.srt'}:
        raise ValueError('Provide a TXT or SRT transcript.')
    if source_url:
        url = urlparse(source_url)
        if url.scheme != 'https' or not url.hostname or url.username or url.password:
            raise ValueError('Source URL must be HTTPS without embedded credentials.')
    text = source.read_text(encoding='utf-8-sig').strip()
    if not text or not title.strip():
        raise ValueError('Transcript and title must be non-empty.')
    segments = []
    if source.suffix.lower() == '.srt':
        for block in re.split(r'\n\s*\n', text):
            rows = block.strip().splitlines()
            if rows and rows[0].strip().isdigit():
                rows.pop(0)
            if not rows:
                continue
            match = re.fullmatch(r'(\d{2,}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2,}:\d{2}:\d{2}[,.]\d{3})', rows[0].strip())
            if not match or len(rows) < 2:
                raise ValueError('Invalid SRT block; expected timestamps and text.')
            start, end = map(seconds, match.groups())
            content = ' '.join(rows[1:]).strip()
            if start >= end or (segments and start < segments[-1]['start']) or not content:
                raise ValueError('SRT intervals must be positive and ordered, with non-empty text.')
            segments.append({'start': start, 'end': end, 'text': content})
    else:
        segments = [{'start': None, 'end': None, 'text': block.strip()}
                    for block in re.split(r'\n\s*\n', text) if block.strip()]
    if not segments:
        raise ValueError('No transcript segments found.')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Choose an empty output directory; existing results are preserved.')
    output.mkdir(parents=True, exist_ok=True)

    def save(name, data):
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def stamp(t):
        t = int(t)
        return f'{t // 3600:02}:{t % 3600 // 60:02}:{t % 60:02}'

    lines = [(f'[{stamp(s["start"])}–{stamp(s["end"])}] ' if s['start'] is not None else '')
             + ' '.join(s['text'].splitlines()) for s in segments]
    (output / 'transcript.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (output / 'transcript.md').write_text(f'# {title}\n\nImported transcript; timestamps, if present, come from the supplied SRT.\n\n'
                                          + '\n\n'.join(lines) + '\n', encoding='utf-8')
    if source.suffix.lower() == '.srt':
        (output / 'transcript.srt').write_text(text + '\n', encoding='utf-8')
    index, first, size = [], 1, 0
    for number, line in enumerate(lines, 1):
        if size and size + len(line) > 9000:
            index.append({'part': len(index) + 1, 'file': 'transcript.txt', 'start_line': first, 'end_line': number - 1, 'characters': size})
            first, size = number, 0
        size += len(line) + 1
    index.append({'part': len(index) + 1, 'file': 'transcript.txt', 'start_line': first, 'end_line': len(lines), 'characters': size})
    duration = max(s['end'] for s in segments) if segments[0]['start'] is not None else None
    save('transcript.json', {'metadata': {'title': title, 'source_url': source_url, 'source_type': 'imported_text'}, 'segments': segments})
    save('reading-index.json', index)
    save('task-state.json', {'status': 'text_imported', 'audio_duration': duration,
                             'summary_status': 'pending', 'audio_cleanup': 'not_applicable'})
    return {'status': 'text_imported', 'segments': len(segments), 'result_dir': str(output)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--title', required=True)
    parser.add_argument('--source-url', default='')
    args = parser.parse_args()
    print(json.dumps(import_text(args.source, args.output, args.title, args.source_url), ensure_ascii=False))
