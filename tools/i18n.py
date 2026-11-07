#!/usr/bin/env python3
"""Track reviewed RU/EN pairs. Standard library only; no translation service or network."""
import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'i18n/manifest.json'
SKIP = {'.git', 'node_modules', '.venv', 'venv', 'dist', 'build', '.astro', '__pycache__', 'output', 'tmp'}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def safe(path):
    file = (ROOT / path).resolve()
    if not file.is_relative_to(ROOT) or file == ROOT:
        raise ValueError('Path must be a file inside the repository: ' + path)
    return file

def inspect(data):
    rows, covered, seen = [], set(), set()
    for entry in data.get('entries', []):
        source, target = entry['source'], entry['target']
        if target in seen:
            raise ValueError('Duplicate translation target: ' + target)
        seen.add(target)
        covered.add(source)
        a, b = safe(source), safe(target)
        state = 'missing-source' if not a.is_file() else 'missing-translation' if not b.is_file() else 'stale' if digest(a) != entry['sourceSha256'] else 'unreviewed' if digest(b) != entry['targetSha256'] else 'current'
        rows.append((state, source, target))
    for entry in data.get('shared', []):
        source = entry['path']
        covered.add(source)
        safe(source)
    patterns = data.get('excludeGlobs', [])
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for name in files:
            file = Path(folder) / name
            path = file.relative_to(ROOT).as_posix()
            if file.suffix.lower() not in {'.md', '.txt', '.html'} or '.en.' in name or path in covered or any(fnmatch.fnmatch(path, p) for p in patterns):
                continue
            content = file.read_text(encoding='utf-8', errors='replace')
            # Pure numeric tables, English vendor files, and code are shared.
            if re.search('[А-Яа-яЁё]', content):
                rows.append(('pending', path, ''))
    return sorted(rows)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['status', 'check', 'record'], nargs='?', default='status')
    parser.add_argument('paths', nargs='*', help='record: explicit SOURCE TARGET pairs, after translation review')
    parser.add_argument('--strict', action='store_true', help='also fail for pending or stale translations')
    args = parser.parse_args()
    data = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if args.command == 'record':
        if not args.paths or len(args.paths) % 2:
            parser.error('record requires explicit SOURCE TARGET pairs; bulk automatic refresh is intentionally unavailable')
        for source, target in zip(args.paths[::2], args.paths[1::2]):
            a, b = safe(source), safe(target)
            if a == b:
                raise ValueError('Source and translation must be separate files')
            entry = dict(source=source, target=target, sourceSha256=digest(a), targetSha256=digest(b), status='reviewed')
            data['entries'] = [e for e in data.get('entries', []) if e['target'] != target] + [entry]
        data['entries'].sort(key=lambda e: (e['source'], e['target']))
        MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    rows = inspect(data)
    for state, source, target in rows:
        if state != 'current':
            print(f'{state}: {source}' + (f' -> {target}' if target else ''))
    counts = {state: sum(r[0] == state for r in rows) for state in sorted({r[0] for r in rows})}
    print(json.dumps(counts, ensure_ascii=False))
    # RU-first publishing remains possible when EN is pending or stale.
    invalid = {'missing-source', 'missing-translation', 'unreviewed'}
    return int(args.command == 'check' and any(r[0] in invalid or (args.strict and r[0] != 'current') for r in rows))

if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
