"""Offline grammar reading progress, stored in the existing user database."""
import json
import re
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).resolve().parent / 'grammar-content.json').read_text(encoding='utf-8'))


def empty_progress():
    return {'version': 1, 'completed': [], 'bookmarks': [], 'last_section': None, 'updatedAt': 0}


def validate(value):
    if value is None:
        return empty_progress()
    def check(ok):
        if not ok:
            raise ValueError('Tiến độ ngữ pháp không hợp lệ.')
    check(isinstance(value, dict) and value.get('version') == 1)
    is_id = lambda v: isinstance(v, str) and re.fullmatch(r'[1-9]\d{0,2}\.[1-9]\d{0,2}', v) is not None
    check(value.get('last_section') is None or is_id(value['last_section']))
    check(type(value.get('updatedAt')) is int and 0 <= value['updatedAt'] < 2**53)
    for key in ('completed', 'bookmarks'):
        items = value.get(key)
        check(isinstance(items, list) and len(items) <= 10000 and all(is_id(x) for x in items))
        check(len(items) == len(set(items)))
    return {key: value[key] for key in ('version', 'completed', 'bookmarks', 'last_section', 'updatedAt')}


def get(con):
    row = con.execute("SELECT value FROM app_meta WHERE key='grammar_progress'").fetchone()
    return validate(json.loads(row[0])) if row else empty_progress()


def put(con, value):
    clean = validate(value)
    con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('grammar_progress',?)", (json.dumps(clean, ensure_ascii=False),))
