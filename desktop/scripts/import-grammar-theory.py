"""Compile reviewed Markdown chapters into safe structured offline reading content.

Usage: python scripts/import-grammar-theory.py /path/to/content
No external runtime dependencies; the generated JSON is packaged with the app.
"""
import json
import re
import sys
from pathlib import Path


def blocks(text):
    output = []
    for chunk in re.split(r'\n\s*\n', text.strip()):
        if not chunk.strip():
            continue
        lines = chunk.splitlines()
        if len(lines) == 1 and re.match(r'^#{1,4} ', lines[0]):
            output.append({'type': 'heading', 'text': re.sub(r'^#+ ', '', lines[0])})
        elif all(line.startswith('|') for line in lines):
            rows = [[x.strip() for x in line.strip().strip('|').split('|')] for line in lines]
            rows = [row for row in rows if not all(re.fullmatch(r':?-+:?', cell) for cell in row)]
            assert all(len(row) == len(rows[0]) for row in rows), 'Uneven grammar table'
            output.append({'type': 'table', 'rows': rows})
        elif all(re.match(r'^(?:[-*] |\d+\. )', line) for line in lines):
            output.append({'type': 'list', 'ordered': bool(re.match(r'^\d+\.', lines[0])), 'items': [re.sub(r'^(?:[-*] |\d+\. )', '', line) for line in lines]})
        else:
            output.append({'type': 'paragraph', 'text': '\n'.join(lines)})
    return output


root = Path(sys.argv[1])
chapters = []
for path in sorted(root.glob('*.md')):
    number = int(path.name[:2])
    if not 1 <= number <= 26:
        continue
    text = path.read_text(encoding='utf-8')
    title = re.match(r'## (\d+) (.+)', text)
    assert title and int(title[1]) == number
    parts = re.split(r'^### (\d+\.\d+) (.+)\n', text, flags=re.M)
    sections = [{'id': parts[i], 'title': parts[i + 1].strip(), 'blocks': blocks(parts[i + 2])} for i in range(1, len(parts), 3)]
    assert sections and all(s['blocks'] for s in sections)
    chapters.append({'id': str(number), 'title': title[2].strip(), 'sections': sections})
assert len(chapters) == 26
assert sum(len(c['sections']) for c in chapters) == 295
intro = (root / '00-mo-dau.md').read_text(encoding='utf-8').split('## Mục lục')[0]
intro = re.sub(r'^Biên soạn ngày .*\n', '', intro, flags=re.M).replace('@NEWPAGE', '')
sources = (root / '99-nguon.md').read_text(encoding='utf-8')
content = {'version': 1, 'title': 'Ngữ pháp tiếng Anh', 'chapters': chapters,
           'introduction': blocks(intro), 'sources': blocks(sources)}
target = Path(__file__).resolve().parents[1] / 'backend' / 'grammar-content.json'
target.write_text(json.dumps(content, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(f'{len(chapters)} chapters; 295 sections; {target.stat().st_size} bytes')
