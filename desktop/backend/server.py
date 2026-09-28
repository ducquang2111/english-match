from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import json
import os
import mimetypes
import sqlite3
import re
import csv
import io
import hashlib
import threading
import uuid
import unicodedata
from functools import wraps
from datetime import datetime, timezone


class AppConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get('ENGLISH_MATCH_DATA_DIR', ROOT))
DB_PATH = DATA_DIR / 'vocabulary.db'
HOST = '127.0.0.1'
PORT = 8000

SEED_VOCAB = [
    ('noon', 'giữa trưa'),
    ('workshop', 'phân xưởng / xưởng làm việc'),
    ('cafeteria', 'quán ăn tự phục vụ'),
    ('rental', 'sự cho thuê'),
    ('conference', 'hội nghị / hội thảo'),
    ("o'clock", 'giờ đúng'),
    ('luggage', 'hành lý'),
    ('enclose', 'bao quanh / vây quanh'),
    ('journey', 'chuyến đi / hành trình'),
    ('repair', 'sửa chữa'),
    ('cashier', 'thu ngân'),
    ('exchange', 'trao đổi'),
    ('schedule', 'lịch trình'),
    ('arrival', 'sự đến nơi'),
    ('departure', 'sự khởi hành'),
    ('passenger', 'hành khách'),
]

DEFAULT_LIST_NAME = 'List 1'


def db_connect():
    con = sqlite3.connect(DB_PATH, timeout=15, factory=AppConnection)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    return con


def normalize_text(value, max_len):
    if not isinstance(value, str):
        return None
    text = re.sub(r'\s+', ' ', value.strip())
    if not text:
        return None
    if len(text) > max_len:
        return False
    return text


def word_details(data, current=None):
    """Optional management fields; omitted fields are preserved on partial edits."""
    result = {}
    for key, label, limit in [('part_of_speech', 'Loại từ', 64), ('phonetic', 'Phiên âm', 256)]:
        value = data.get(key, current[key] if current is not None else '')
        if not isinstance(value, str):
            raise ValueError(f'{label} phải là văn bản; có thể để trống.')
        value = re.sub(r'\s+', ' ', value.strip())
        if len(value) > limit:
            raise ValueError(f'{label} tối đa {limit} ký tự.')
        result[key] = value
    return result


def get_default_list_id(con):
    row = con.execute(
        'SELECT id FROM vocabulary_lists WHERE name = ? COLLATE NOCASE LIMIT 1',
        (DEFAULT_LIST_NAME,),
    ).fetchone()
    if row:
        return row['id']
    cur = con.execute('INSERT INTO vocabulary_lists(name) VALUES (?)', (DEFAULT_LIST_NAME,))
    return cur.lastrowid


def list_exists(con, list_id):
    return con.execute('SELECT 1 FROM vocabulary_lists WHERE id=?', (list_id,)).fetchone() is not None


def init_db():
    """Create tables and safely migrate the old database without losing vocabulary."""
    with db_connect() as con:
        con.execute('''
            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        con.execute('''
            CREATE TABLE IF NOT EXISTS vocabulary_lists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        con.execute("INSERT OR IGNORE INTO app_meta(key,value) VALUES('database_id',?)", (uuid.uuid4().hex,))

        con.execute('''
            CREATE TABLE IF NOT EXISTS vocabulary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                english TEXT NOT NULL COLLATE NOCASE,
                vietnamese TEXT NOT NULL,
                list_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(english, vietnamese)
            )
        ''')

        # Migration from v1: add list_id to the existing vocabulary table.
        columns = {row['name'] for row in con.execute('PRAGMA table_info(vocabulary)').fetchall()}
        if 'list_id' not in columns:
            con.execute('ALTER TABLE vocabulary ADD COLUMN list_id INTEGER')
        for column in ('part_of_speech', 'phonetic'):
            if column not in columns:
                con.execute(f"ALTER TABLE vocabulary ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")

        seeded = con.execute("SELECT value FROM app_meta WHERE key='seeded'").fetchone()
        unassigned = con.execute('SELECT COUNT(*) FROM vocabulary WHERE list_id IS NULL OR list_id NOT IN (SELECT id FROM vocabulary_lists)').fetchone()[0]
        if unassigned or not seeded:
            default_list_id = get_default_list_id(con)
            con.execute('UPDATE vocabulary SET list_id=? WHERE list_id IS NULL OR list_id NOT IN (SELECT id FROM vocabulary_lists)', (default_list_id,))
        if not seeded:
            con.executemany(
                'INSERT OR IGNORE INTO vocabulary (english, vietnamese, list_id) VALUES (?, ?, ?)',
                [(en, vi, default_list_id) for en, vi in SEED_VOCAB],
            )
            con.execute("INSERT OR REPLACE INTO app_meta(key, value) VALUES('seeded', '1')")

        init_learning(con)
        con.commit()


class LegacyHandler(BaseHTTPRequestHandler):
    server_version = 'EnglishMatch/2.0'

    def log_message(self, fmt, *args):
        print(f'[{self.log_date_time_string()}] {fmt % args}')

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            raw = self.rfile.read(length) if length else b'{}'
            return json.loads(raw.decode('utf-8'))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return None

    def vocabulary_select_sql(self):
        return (
            'SELECT v.id, v.english, v.vietnamese, v.part_of_speech, v.phonetic, v.list_id, v.created_at, '
            'COALESCE(l.name, ?) AS list_name '
            'FROM vocabulary v '
            'LEFT JOIN vocabulary_lists l ON l.id = v.list_id '
        )

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/api/lists':
            with db_connect() as con:
                rows = con.execute('''
                    SELECT l.id, l.name, l.created_at, COUNT(v.id) AS word_count
                    FROM vocabulary_lists l
                    LEFT JOIN vocabulary v ON v.list_id = l.id
                    GROUP BY l.id, l.name, l.created_at
                    ORDER BY l.id ASC
                ''').fetchall()
            self.send_json({'items': [dict(r) for r in rows], 'total': len(rows)})
            return

        if parsed.path == '/api/vocabulary':
            query = parse_qs(parsed.query)
            search = (query.get('search', [''])[0] or '').strip()
            raw_list_id = (query.get('list_id', [''])[0] or '').strip()

            where = []
            params = ['Không có list']

            if search:
                like = f'%{search}%'
                where.append('(v.english LIKE ? OR v.vietnamese LIKE ? OR v.part_of_speech LIKE ? OR v.phonetic LIKE ? OR l.name LIKE ?)')
                params.extend([like] * 5)

            if raw_list_id and raw_list_id.lower() != 'all':
                try:
                    list_id = int(raw_list_id)
                except ValueError:
                    self.send_json({'error': 'list_id không hợp lệ.'}, 400)
                    return
                where.append('v.list_id = ?')
                params.append(list_id)

            sql = self.vocabulary_select_sql()
            if where:
                sql += ' WHERE ' + ' AND '.join(where)
            sql += ' ORDER BY l.id ASC, v.id ASC'

            with db_connect() as con:
                rows = con.execute(sql, params).fetchall()
            self.send_json({'items': [dict(r) for r in rows], 'total': len(rows)})
            return

        if parsed.path == '/api/stats':
            with db_connect() as con:
                total_vocab = con.execute('SELECT COUNT(*) AS c FROM vocabulary').fetchone()['c']
                total_lists = con.execute('SELECT COUNT(*) AS c FROM vocabulary_lists').fetchone()['c']
            self.send_json({'total_vocabulary': total_vocab, 'total_lists': total_lists})
            return

        self.serve_static(parsed.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        data = self.read_json()
        if data is None:
            self.send_json({'error': 'Dữ liệu JSON không hợp lệ.'}, 400)
            return

        if parsed.path == '/api/lists':
            name = normalize_text(data.get('name'), 80)
            if name is None:
                self.send_json({'error': 'Vui lòng nhập tên list.'}, 400)
                return
            if name is False:
                self.send_json({'error': 'Tên list tối đa 80 ký tự.'}, 400)
                return
            try:
                with db_connect() as con:
                    cur = con.execute('INSERT INTO vocabulary_lists(name) VALUES (?)', (name,))
                    con.commit()
                    row = con.execute(
                        'SELECT id, name, created_at FROM vocabulary_lists WHERE id=?',
                        (cur.lastrowid,),
                    ).fetchone()
                item = dict(row)
                item['word_count'] = 0
                self.send_json({'item': item}, 201)
            except sqlite3.IntegrityError:
                self.send_json({'error': 'Tên list này đã tồn tại.'}, 409)
            return

        if parsed.path == '/api/vocabulary':
            english = normalize_text(data.get('english'), 120)
            vietnamese = normalize_text(data.get('vietnamese'), 220)
            try:
                details = word_details(data)
            except ValueError as exc:
                self.send_json({'error': str(exc)}, 400)
                return
            if english is None or vietnamese is None:
                self.send_json({'error': 'Vui lòng nhập đủ từ tiếng Anh và nghĩa tiếng Việt.'}, 400)
                return
            if english is False or vietnamese is False:
                self.send_json({'error': 'Từ hoặc nghĩa quá dài.'}, 400)
                return

            raw_list_id = data.get('list_id')
            try:
                list_id = int(raw_list_id) if raw_list_id not in (None, '') else None
            except (TypeError, ValueError):
                self.send_json({'error': 'List không hợp lệ.'}, 400)
                return

            try:
                with db_connect() as con:
                    if list_id is None:
                        list_id = get_default_list_id(con)
                    if not list_exists(con, list_id):
                        self.send_json({'error': 'List không tồn tại.'}, 404)
                        return
                    if con.execute('SELECT COUNT(*) FROM vocabulary').fetchone()[0] >= 10000:
                        self.send_json({'error': 'Kho từ tối đa 10.000 cặp.'}, 400)
                        return
                    cur = con.execute(
                        'INSERT INTO vocabulary (english, vietnamese, list_id, part_of_speech, phonetic) VALUES (?, ?, ?, ?, ?)',
                        (english, vietnamese, list_id, details['part_of_speech'], details['phonetic']),
                    )
                    con.commit()
                    row = con.execute(
                        self.vocabulary_select_sql() + ' WHERE v.id=?',
                        ('Không có list', cur.lastrowid),
                    ).fetchone()
                self.send_json({'item': dict(row)}, 201)
            except sqlite3.IntegrityError:
                self.send_json({'error': 'Cặp từ này đã có trong kho từ vựng.'}, 409)
            return

        self.send_json({'error': 'Không tìm thấy API.'}, 404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        match = re.fullmatch(r'/api/vocabulary/(\d+)', parsed.path)
        if not match:
            self.send_json({'error': 'Không tìm thấy API.'}, 404)
            return

        data = self.read_json()
        if data is None:
            self.send_json({'error': 'Dữ liệu JSON không hợp lệ.'}, 400)
            return

        item_id = int(match.group(1))
        with db_connect() as con:
            current = con.execute(
                'SELECT id, english, vietnamese, list_id, part_of_speech, phonetic FROM vocabulary WHERE id=?',
                (item_id,),
            ).fetchone()
            if not current:
                self.send_json({'error': 'Không tìm thấy từ vựng.'}, 404)
                return

            english = current['english']
            vietnamese = current['vietnamese']
            list_id = current['list_id']
            try:
                details = word_details(data, current)
            except ValueError as exc:
                self.send_json({'error': str(exc)}, 400)
                return

            if 'english' in data:
                value = normalize_text(data.get('english'), 120)
                if value is None:
                    self.send_json({'error': 'Từ tiếng Anh không được để trống.'}, 400)
                    return
                if value is False:
                    self.send_json({'error': 'Từ tiếng Anh quá dài.'}, 400)
                    return
                english = value

            if 'vietnamese' in data:
                value = normalize_text(data.get('vietnamese'), 220)
                if value is None:
                    self.send_json({'error': 'Nghĩa tiếng Việt không được để trống.'}, 400)
                    return
                if value is False:
                    self.send_json({'error': 'Nghĩa tiếng Việt quá dài.'}, 400)
                    return
                vietnamese = value

            if 'list_id' in data:
                try:
                    list_id = int(data.get('list_id'))
                except (TypeError, ValueError):
                    self.send_json({'error': 'List không hợp lệ.'}, 400)
                    return
                if not list_exists(con, list_id):
                    self.send_json({'error': 'List không tồn tại.'}, 404)
                    return

            try:
                con.execute(
                    'UPDATE vocabulary SET english=?, vietnamese=?, list_id=?, part_of_speech=?, phonetic=? WHERE id=?',
                    (english, vietnamese, list_id, details['part_of_speech'], details['phonetic'], item_id),
                )
                con.commit()
                row = con.execute(
                    self.vocabulary_select_sql() + ' WHERE v.id=?',
                    ('Không có list', item_id),
                ).fetchone()
                self.send_json({'item': dict(row)})
            except sqlite3.IntegrityError:
                self.send_json({'error': 'Cặp từ này đã có trong kho từ vựng.'}, 409)

    def do_DELETE(self):
        parsed = urlparse(self.path)

        vocab_match = re.fullmatch(r'/api/vocabulary/(\d+)', parsed.path)
        if vocab_match:
            item_id = int(vocab_match.group(1))
            with db_connect() as con:
                cur = con.execute('DELETE FROM vocabulary WHERE id=?', (item_id,))
                con.commit()
            if cur.rowcount == 0:
                self.send_json({'error': 'Không tìm thấy từ vựng.'}, 404)
            else:
                self.send_json({'ok': True})
            return

        list_match = re.fullmatch(r'/api/lists/(\d+)', parsed.path)
        if list_match:
            list_id = int(list_match.group(1))
            with db_connect() as con:
                row = con.execute(
                    'SELECT id, name FROM vocabulary_lists WHERE id=?',
                    (list_id,),
                ).fetchone()
                if not row:
                    self.send_json({'error': 'Không tìm thấy list.'}, 404)
                    return
                count = con.execute(
                    'SELECT COUNT(*) AS c FROM vocabulary WHERE list_id=?',
                    (list_id,),
                ).fetchone()['c']
                if count:
                    self.send_json({
                        'error': f'List "{row["name"]}" còn {count} từ. Hãy chuyển hoặc xóa các từ trước khi xóa list.'
                    }, 409)
                    return
                con.execute('DELETE FROM vocabulary_lists WHERE id=?', (list_id,))
                con.commit()
            self.send_json({'ok': True})
            return

        self.send_json({'error': 'Không tìm thấy API.'}, 404)

    def serve_static(self, path):
        if path in ('', '/'):
            file_path = ROOT / 'index.html'
        else:
            safe = Path(path.lstrip('/'))
            if '..' in safe.parts:
                self.send_error(403)
                return
            file_path = ROOT / safe

        if not file_path.exists() or not file_path.is_file():
            file_path = ROOT / 'index.html'

        data = file_path.read_bytes()
        content_type, _ = mimetypes.guess_type(str(file_path))
        content_type = content_type or 'application/octet-stream'
        if content_type.startswith('text/') or content_type in ('application/javascript', 'application/json'):
            content_type += '; charset=utf-8'

        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(data)


# Phase 1: persistent rounds, bulk import, backup and restore.
WRITE_LOCK = threading.RLock()
MAX_BODY = 64 * 1024 * 1024


def serialized(fn):
    @wraps(fn)
    def wrapped(self, *args, **kwargs):
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + self.headers.get('Host', ''):
            self.send_json({'error': 'Yêu cầu khác nguồn không được phép.'}, 403)
            return
        with WRITE_LOCK:
            return fn(self, *args, **kwargs)
    return wrapped


def get_progress(con):
    row = con.execute("SELECT value FROM app_meta WHERE key='progress'").fetchone()
    return json.loads(row[0]) if row else None


def database_id(con):
    return con.execute("SELECT value FROM app_meta WHERE key='database_id'").fetchone()[0]


def positive_id(value):
    return type(value) is int and 0 < value < 2 ** 53


def validate_progress(s):
    if s is None:
        return
    def check(ok):
        if not ok:
            raise ValueError('Cấu trúc tiến độ không hợp lệ.')
    check(isinstance(s, dict) and s.get('version') == 1)
    check(isinstance(s.get('scope'), str) and (s['scope'] == 'all' or s['scope'].isdigit()))
    check(type(s.get('updatedAt')) is int and s['updatedAt'] >= 0)
    words, pages, states = s.get('words'), s.get('pages'), s.get('pageStates')
    check(isinstance(words, list) and 0 < len(words) <= 10000)
    check(isinstance(pages, list) and isinstance(states, list) and len(pages) == len(states) > 0)
    ids = set()
    for w in words:
        check(isinstance(w, dict) and positive_id(w.get('id')) and w['id'] not in ids)
        check(bool(normalize_text(w.get('english'), 120)) and bool(normalize_text(w.get('vietnamese'), 220)))
        check(positive_id(w.get('list_id')))
        ids.add(w['id'])
    flat = []
    for page, state in zip(pages, states):
        check(isinstance(page, list) and 0 < len(page) <= 8 and all(positive_id(x) for x in page))
        check(isinstance(state, dict))
        flat.extend(page)
        for key in ('matched', 'wrongIds'):
            values = state.get(key)
            check(isinstance(values, list) and all(positive_id(x) for x in values))
            check(len(values) == len(set(values)) and set(values) <= set(page))
        check(type(state.get('wrong')) is int and 0 <= state['wrong'] <= 1000000)
        order = state.get('order')
        check(isinstance(order, list) and all(isinstance(x, str) for x in order))
        check(len(order) == len(page) * 2 and set(order) == {f'{x}-{side}' for x in page for side in ('en', 'vi')})
    check(len(flat) == len(ids) and set(flat) == ids)
    check(type(s.get('pageIndex')) is int and 0 <= s['pageIndex'] < len(pages))


def ascii_lower(s):
    return s.translate(str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))


def export_backup(con):
    return {'format': 'english-match-backup', 'version': 3,
            'exported_at': datetime.now(timezone.utc).isoformat(),
            'lists': [dict(r) for r in con.execute('SELECT * FROM vocabulary_lists ORDER BY id')],
            'vocabulary': [dict(r) for r in con.execute('SELECT * FROM vocabulary ORDER BY id')],
            'progress': get_progress(con), 'learning': learning_export(con)}


def validate_backup(raw):
    if not isinstance(raw, dict) or raw.get('format') != 'english-match-backup' or raw.get('version') not in (1, 2, 3):
        raise ValueError('Hãy chọn file JSON sao lưu được xuất từ English Match (định dạng 1, 2 hoặc 3).')
    lists, words = raw.get('lists'), raw.get('vocabulary')
    if not isinstance(lists, list) or not isinstance(words, list) or len(lists) > 10000 or len(words) > 10000:
        raise ValueError('Cấu trúc hoặc số lượng dữ liệu không hợp lệ (tối đa 10.000 từ).')
    list_ids, names, ids, pairs = set(), set(), set(), set()
    clean_lists, clean_words = [], []
    for r in lists:
        if not isinstance(r, dict) or not positive_id(r.get('id')):
            raise ValueError('Mã list không hợp lệ.')
        name = normalize_text(r.get('name'), 80)
        if not name or r['id'] in list_ids or ascii_lower(name) in names:
            raise ValueError('Tên/mã list trống, trùng hoặc quá dài.')
        list_ids.add(r['id']); names.add(ascii_lower(name))
        clean_lists.append({'id': r['id'], 'name': name, 'created_at': str(r.get('created_at', ''))[:100]})
    for r in words:
        if not isinstance(r, dict) or not positive_id(r.get('id')) or not positive_id(r.get('list_id')):
            raise ValueError('Mã từ hoặc mã list không hợp lệ.')
        en, vi = normalize_text(r.get('english'), 120), normalize_text(r.get('vietnamese'), 220)
        if not en or not vi or r['id'] in ids or r['list_id'] not in list_ids:
            raise ValueError('Từ trống, quá dài, trùng mã hoặc thuộc list không tồn tại.')
        pair = (ascii_lower(en), vi)
        if pair in pairs:
            raise ValueError('Bản sao lưu có cặp từ trùng nhau.')
        pairs.add(pair); ids.add(r['id'])
        clean_words.append({'id': r['id'], 'english': en, 'vietnamese': vi, 'list_id': r['list_id'], 'created_at': str(r.get('created_at', ''))[:100], **word_details(r)})
    progress = raw.get('progress')
    validate_progress(progress)
    match_learning(progress)
    if raw['version'] >= 2 and not isinstance(raw.get('learning'),dict):
        raise ValueError('Bản sao lưu thiếu dữ liệu học tập.')
    return {'lists': clean_lists, 'vocabulary': clean_words, 'progress': progress, 'learning': validate_learning_backup(raw.get('learning'))}


def backup_token(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def snapshot_database():
    folder = DB_PATH.parent / 'backups'
    folder.mkdir(exist_ok=True)
    dest = folder / ('before-restore-' + datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8] + '.db')
    with db_connect() as con:
        with sqlite3.connect(dest, factory=AppConnection) as out:
            con.backup(out)
    return dest.name


def prepare_import(con, data):
    text = data.get('text')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Hãy dán nội dung hoặc chọn CSV UTF-8.')
    try:
        list_id = int(data.get('list_id'))
    except (TypeError, ValueError):
        raise ValueError('Hãy chọn list để nhập từ.')
    if not list_exists(con, list_id):
        raise ValueError('List không tồn tại.')
    text = text.lstrip('\ufeff')
    delim = data.get('delimiter', 'auto')
    if delim == 'auto':
        first = next((x for x in text.splitlines() if x.strip()), '')
        if '\t' in first:
            delim = '\t'
        elif '|' in first:
            delim = '|'
        else:
            try:
                delim = csv.Sniffer().sniff(text[:4096], delimiters=',;').delimiter
            except csv.Error:
                delim = ','
    if delim not in ('\t', '|', ',', ';'):
        raise ValueError('Dấu phân cách không hợp lệ.')
    existing = {(ascii_lower(r[0]), r[1]) for r in con.execute('SELECT english,vietnamese FROM vocabulary')}
    rows, seen, first = [], set(), True
    try:
        reader = csv.reader(io.StringIO(text), delimiter=delim, strict=True)
        for cells in reader:
            if not cells or not any(x.strip() for x in cells):
                continue
            if first and len(cells) == 2 and cells[0].strip().lower() in ('english', 'tiếng anh') and cells[1].strip().lower() in ('vietnamese', 'tiếng việt', 'nghĩa'):
                first = False
                continue
            first = False
            if len(rows) >= 5000:
                raise ValueError('Mỗi lần nhập tối đa 5.000 dòng.')
            en = normalize_text(cells[0], 120) if cells else None
            vi = normalize_text(cells[1], 220) if len(cells) > 1 else None
            r = {'line': reader.line_num, 'english': en or '', 'vietnamese': vi or ''}
            if len(cells) != 2 or not en or not vi:
                r.update(status='error', message='Cần 2 cột, không trống; tiếng Anh ≤120, nghĩa ≤220 ký tự.')
            elif (ascii_lower(en), vi) in existing | seen:
                r.update(status='duplicate', message='Cặp đã có, sẽ bỏ qua.')
            else:
                r.update(status='new', message='Sẽ thêm')
                seen.add((ascii_lower(en), vi))
            rows.append(r)
    except csv.Error as exc:
        raise ValueError('CSV không hợp lệ. Kiểm tra dấu ngoặc kép và dấu phân cách.') from exc
    if not rows:
        raise ValueError('Không có dòng từ vựng nào.')
    if len(existing) + len(seen) > 10000:
        raise ValueError('Kho từ tối đa 10.000 cặp.')
    return {'rows': rows, 'list_id': list_id, 'new': sum(r['status']=='new' for r in rows),
            'errors': sum(r['status']=='error' for r in rows), 'duplicates': sum(r['status']=='duplicate' for r in rows)}


# Phase 2 learning records. Snapshots retain history when vocabulary is edited/deleted.
def init_learning(con):
    con.execute('''CREATE TABLE IF NOT EXISTS learning_sessions (
        id TEXT PRIMARY KEY, mode TEXT NOT NULL, scope_name TEXT NOT NULL,
        started_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, status TEXT NOT NULL,
        total INTEGER NOT NULL, correct INTEGER NOT NULL, wrong INTEGER NOT NULL)''')
    con.execute('''CREATE TABLE IF NOT EXISTS learning_events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
        session_id TEXT NOT NULL, mode TEXT NOT NULL, word_id INTEGER NOT NULL,
        english TEXT NOT NULL, vietnamese TEXT NOT NULL, correct INTEGER NOT NULL,
        answer TEXT NOT NULL, occurred_at INTEGER NOT NULL)''')
    con.execute('CREATE INDEX IF NOT EXISTS learning_word_idx ON learning_events(word_id,seq)')
    con.execute('CREATE INDEX IF NOT EXISTS learning_session_idx ON learning_events(session_id,seq)')


def clean_answer(value):
    text = unicodedata.normalize('NFKC', value).translate(str.maketrans({'’': "'", '‘': "'", 'ʼ': "'"}))
    return re.sub(r'\s+', ' ', text.strip()).lower()


def require_learning(ok, message='Dữ liệu học tập không hợp lệ.'):
    if not ok:
        raise ValueError(message)


def valid_key(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{8,80}', value) is not None


def timestamp(value):
    return type(value) is int and 0 <= value < 2**53


def review_progress(con):
    row = con.execute("SELECT value FROM app_meta WHERE key='review_progress'").fetchone()
    return json.loads(row[0]) if row else None


def validate_review(s):
    if s is None:
        return
    require_learning(isinstance(s, dict) and s.get('version') == 1 and valid_key(s.get('id')))
    require_learning(s.get('mode') in ('flashcard','typing'))
    require_learning(isinstance(s.get('scope'),str) and (s['scope']=='all' or s['scope'].isdigit()))
    require_learning(isinstance(s.get('scopeName'),str) and len(s['scopeName']) <= 200)
    require_learning(timestamp(s.get('startedAt')) and timestamp(s.get('updatedAt')))
    require_learning(type(s.get('wrongOnly')) is bool and type(s.get('flipped')) is bool)
    words, results = s.get('words'), s.get('results')
    require_learning(isinstance(words,list) and 0 < len(words) <= 10000 and isinstance(results,list) and len(results)<=len(words))
    require_learning(type(s.get('index')) is int and 0 <= s['index'] <= len(words))
    require_learning(len(results) in (s['index'],s['index']+1))
    ids=set()
    for w in words:
        require_learning(isinstance(w,dict) and positive_id(w.get('id')) and w['id'] not in ids and positive_id(w.get('list_id')))
        require_learning(bool(normalize_text(w.get('english'),120)) and bool(normalize_text(w.get('vietnamese'),220)))
        ids.add(w['id'])
    for i,r in enumerate(results):
        require_learning(isinstance(r,dict) and type(r.get('correct')) is bool and timestamp(r.get('at')))
        require_learning(isinstance(r.get('answer'),str) and len(r['answer'])<=1000)
        if s['mode']=='typing':
            require_learning(r['correct']==(clean_answer(r['answer'])==clean_answer(words[i]['english'])), 'Kết quả bài gõ không khớp đáp án.')


def match_learning(s):
    if s is None or 'learning' not in s:
        return None, []
    l=s['learning']
    require_learning(isinstance(l,dict) and valid_key(l.get('id')) and timestamp(l.get('startedAt')))
    require_learning(isinstance(l.get('scopeName'),str) and len(l['scopeName'])<=200)
    events=l.get('events')
    require_learning(isinstance(events,list) and len(events)<=100000)
    words={w['id']:w for w in s['words']}; records=[]
    for i,e in enumerate(events):
        require_learning(isinstance(e,dict) and type(e.get('correct')) is bool and timestamp(e.get('at')))
        ids=e.get('wordIds')
        require_learning(isinstance(ids,list) and 1<=len(ids)<=2 and all(positive_id(x) and x in words for x in ids) and len(set(ids))==len(ids))
        for wid in ids:
            w=words[wid]
            records.append({'event_id':f'{l["id"]}:{i}:{wid}', 'session_id':l['id'], 'mode':'match', 'word_id':wid,
                            'english':w['english'],'vietnamese':w['vietnamese'],'correct':int(e['correct']),'answer':'','occurred_at':e['at']})
    correct=sum(e['correct'] for e in events); wrong=len(events)-correct
    complete=sum(len(p['matched']) for p in s['pageStates'])==len(words)
    meta={'id':l['id'],'mode':'match','scope_name':l['scopeName'],'started_at':l['startedAt'],'updated_at':s['updatedAt'],
          'status':'completed' if complete else 'active','total':len(words),'correct':correct,'wrong':wrong}
    return meta,records


def review_learning(s):
    if s is None:
        return None,[]
    correct=sum(r['correct'] for r in s['results']); records=[]
    for i,r in enumerate(s['results']):
        w=s['words'][i]
        records.append({'event_id':f'{s["id"]}:{i}', 'session_id':s['id'], 'mode':s['mode'], 'word_id':w['id'],
                        'english':w['english'],'vietnamese':w['vietnamese'],'correct':int(r['correct']),'answer':r['answer'],'occurred_at':r['at']})
    meta={'id':s['id'],'mode':s['mode'],'scope_name':s['scopeName']+(' · Từ cần ôn' if s['wrongOnly'] else ''),
          'started_at':s['startedAt'],'updated_at':s['updatedAt'],'status':'completed' if len(s['results'])==len(s['words']) else 'active',
          'total':len(s['words']),'correct':correct,'wrong':len(s['results'])-correct}
    return meta,records


def sync_learning(con, meta, records, old_id=None):
    if old_id and (meta is None or old_id!=meta['id']):
        con.execute("UPDATE learning_sessions SET status='stopped' WHERE id=? AND status='active'",(old_id,))
    if meta is None:
        return
    existing=con.execute('SELECT * FROM learning_sessions WHERE id=?',(meta['id'],)).fetchone()
    if existing:
        require_learning(existing['mode']==meta['mode'] and existing['started_at']==meta['started_at'], 'Mã buổi học đã được sử dụng.')
        require_learning(meta['correct']>=existing['correct'] and meta['wrong']>=existing['wrong'], 'Không thể ghi đè kết quả mới bằng tiến độ cũ. Hãy tải lại trang.')
        require_learning(meta['updated_at']>=existing['updated_at'], 'Tiến độ này cũ hơn dữ liệu đã lưu. Hãy tải lại trang.')
    prior_ids={r[0] for r in con.execute('SELECT event_id FROM learning_events WHERE session_id=?',(meta['id'],))}
    require_learning(prior_ids.issubset({r['event_id'] for r in records}), 'Tiến độ thiếu câu trả lời đã lưu. Hãy tải lại trang.')
    con.execute('''INSERT INTO learning_sessions(id,mode,scope_name,started_at,updated_at,status,total,correct,wrong)
        VALUES(:id,:mode,:scope_name,:started_at,:updated_at,:status,:total,:correct,:wrong)
        ON CONFLICT(id) DO UPDATE SET scope_name=excluded.scope_name,updated_at=excluded.updated_at,
        status=excluded.status,total=excluded.total,correct=excluded.correct,wrong=excluded.wrong''',meta)
    for r in records:
        old=con.execute('SELECT * FROM learning_events WHERE event_id=?',(r['event_id'],)).fetchone()
        if old:
            require_learning(all(old[k]==v for k,v in r.items()), 'Một câu trả lời đã lưu không được thay đổi.')
            continue
        con.execute('''INSERT INTO learning_events(event_id,session_id,mode,word_id,english,vietnamese,correct,answer,occurred_at)
            VALUES(:event_id,:session_id,:mode,:word_id,:english,:vietnamese,:correct,:answer,:occurred_at)''',r)


def word_learning(con):
    rows=con.execute('''SELECT v.id,v.english,v.vietnamese,v.list_id,l.name AS list_name,
        COUNT(e.seq) AS reviews,
        SUM(CASE WHEN e.mode!='flashcard' AND e.correct=1 THEN 1 ELSE 0 END) AS correct_count,
        SUM(CASE WHEN e.mode!='flashcard' AND e.correct=0 THEN 1 ELSE 0 END) AS wrong_count,
        SUM(CASE WHEN e.mode='flashcard' AND e.correct=1 THEN 1 ELSE 0 END) AS remembered,
        SUM(CASE WHEN e.mode='flashcard' AND e.correct=0 THEN 1 ELSE 0 END) AS forgotten,
        MAX(e.occurred_at) AS last_reviewed,
        CASE WHEN COALESCE(MAX(CASE WHEN e.correct=0 THEN e.seq END),0) >
             COALESCE(MAX(CASE WHEN e.correct=1 AND e.mode IN ('typing','flashcard') THEN e.seq END),0)
             THEN 1 ELSE 0 END AS needs_review
        FROM vocabulary v JOIN vocabulary_lists l ON l.id=v.list_id
        LEFT JOIN learning_events e ON e.word_id=v.id AND e.english=v.english COLLATE BINARY AND e.vietnamese=v.vietnamese
        GROUP BY v.id ORDER BY needs_review DESC, wrong_count+forgotten DESC,v.id''').fetchall()
    return [dict(r) for r in rows]


def learning_export(con):
    return {'review_progress':review_progress(con),
            'sessions':[dict(r) for r in con.execute('SELECT * FROM learning_sessions ORDER BY started_at,id')],
            'events':[dict(r) for r in con.execute('SELECT * FROM learning_events ORDER BY seq')]}


def validate_learning_backup(raw):
    if raw is None:
        return {'review_progress':None,'sessions':[],'events':[]}
    require_learning(isinstance(raw,dict) and isinstance(raw.get('sessions'),list) and isinstance(raw.get('events'),list))
    validate_review(raw.get('review_progress'))
    sessions=[];events=[];ids=set();keys=set();seqs=set()
    for s in raw['sessions']:
        require_learning(isinstance(s,dict) and valid_key(s.get('id')) and s['id'] not in ids)
        require_learning(s.get('mode') in ('match','typing','flashcard') and s.get('status') in ('active','stopped','completed'))
        require_learning(isinstance(s.get('scope_name'),str) and len(s['scope_name'])<=250)
        require_learning(timestamp(s.get('started_at')) and timestamp(s.get('updated_at')))
        require_learning(all(type(s.get(k)) is int and 0<=s[k]<=1000000 for k in ('total','correct','wrong')))
        require_learning(s['total']<=10000 and s['correct']<=s['total'])
        ids.add(s['id']); sessions.append({k:s[k] for k in ('id','mode','scope_name','started_at','updated_at','status','total','correct','wrong')})
    session_modes={s['id']:s['mode'] for s in sessions}
    for e in raw['events']:
        require_learning(isinstance(e,dict) and positive_id(e.get('seq')) and e['seq'] not in seqs)
        require_learning(isinstance(e.get('event_id'),str) and len(e['event_id'])<=150 and e['event_id'] not in keys and e.get('session_id') in ids)
        require_learning(e.get('mode') in ('match','typing','flashcard') and positive_id(e.get('word_id')) and type(e.get('correct')) is int and e['correct'] in (0,1))
        require_learning(e['mode']==session_modes[e['session_id']], 'Chế độ của kết quả không khớp buổi học.')
        require_learning(bool(normalize_text(e.get('english'),120)) and bool(normalize_text(e.get('vietnamese'),220)))
        require_learning(isinstance(e.get('answer'),str) and len(e['answer'])<=1000 and timestamp(e.get('occurred_at')))
        seqs.add(e['seq']);keys.add(e['event_id'])
        events.append({k:e[k] for k in ('seq','event_id','session_id','mode','word_id','english','vietnamese','correct','answer','occurred_at')})
    return {'review_progress':raw.get('review_progress'),'sessions':sessions,'events':sorted(events,key=lambda e:e['seq'])}


def restore_learning(con,data):
    con.execute('DELETE FROM learning_events');con.execute('DELETE FROM learning_sessions')
    con.executemany('''INSERT INTO learning_sessions(id,mode,scope_name,started_at,updated_at,status,total,correct,wrong)
        VALUES(:id,:mode,:scope_name,:started_at,:updated_at,:status,:total,:correct,:wrong)''',data['sessions'])
    con.executemany('''INSERT INTO learning_events(seq,event_id,session_id,mode,word_id,english,vietnamese,correct,answer,occurred_at)
        VALUES(:seq,:event_id,:session_id,:mode,:word_id,:english,:vietnamese,:correct,:answer,:occurred_at)''',data['events'])
    con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('review_progress',?)",(json.dumps(data['review_progress'],ensure_ascii=False),))


def learning_get(handler,path,query):
    if path=='/api/review/progress':
        with db_connect() as con:
            handler.send_json({'database_id':database_id(con),'item':review_progress(con)})
        return True
    if path=='/api/learning/stats':
        with db_connect() as con:
            words=word_learning(con)
            totals=dict(con.execute('''SELECT COUNT(*) AS sessions,
                COALESCE(SUM(status='completed'),0) AS completed,
                COALESCE(SUM(CASE WHEN mode!='flashcard' THEN correct ELSE 0 END),0) AS correct,
                COALESCE(SUM(CASE WHEN mode!='flashcard' THEN wrong ELSE 0 END),0) AS wrong,
                COALESCE(SUM(CASE WHEN mode='flashcard' THEN correct ELSE 0 END),0) AS remembered,
                COALESCE(SUM(CASE WHEN mode='flashcard' THEN wrong ELSE 0 END),0) AS forgotten
                FROM learning_sessions''').fetchone())
            totals['words_practiced']=sum(w['reviews']>0 for w in words);totals['needs_review']=sum(w['needs_review'] for w in words)
            recent=[dict(r) for r in con.execute('SELECT started_at,mode,correct,wrong FROM learning_sessions WHERE started_at>=? ORDER BY started_at', (int(datetime.now(timezone.utc).timestamp()*1000)-8*86400000,))]
        handler.send_json({'totals':totals,'words':words,'recent':recent})
        return True
    if path=='/api/learning/history':
        try:
            offset=max(0,int(query.get('offset',['0'])[0]));limit=min(100,max(1,int(query.get('limit',['20'])[0])))
        except ValueError:
            handler.send_json({'error':'Phân trang không hợp lệ.'},400);return True
        mode=query.get('mode',['all'])[0]
        if mode not in ('all','match','typing','flashcard'):
            handler.send_json({'error':'Chế độ không hợp lệ.'},400);return True
        where='' if mode=='all' else ' WHERE mode=?';params=[] if mode=='all' else [mode]
        with db_connect() as con:
            total=con.execute('SELECT COUNT(*) FROM learning_sessions'+where,params).fetchone()[0]
            rows=con.execute('SELECT * FROM learning_sessions'+where+' ORDER BY started_at DESC,id DESC LIMIT ? OFFSET ?',params+[limit,offset]).fetchall()
        handler.send_json({'items':[dict(r) for r in rows],'total':total,'offset':offset,'limit':limit});return True
    match=re.fullmatch(r'/api/learning/session/([A-Za-z0-9_-]{8,80})',path)
    if match:
        with db_connect() as con:
            s=con.execute('SELECT * FROM learning_sessions WHERE id=?',(match.group(1),)).fetchone()
            rows=con.execute('SELECT * FROM learning_events WHERE session_id=? ORDER BY seq',(match.group(1),)).fetchall()
        handler.send_json({'item':dict(s),'events':[dict(r) for r in rows]} if s else {'error':'Không tìm thấy buổi học.'},200 if s else 404);return True
    return False


class AppHandler(LegacyHandler):
    server_version = 'EnglishMatch/2.2'

    def read_json(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= MAX_BODY:
                return None
            data = json.loads(self.rfile.read(length).decode('utf-8')) if length else {}
            return data if isinstance(data, dict) else None
        except (ValueError, UnicodeDecodeError):
            return None

    def do_GET(self):
        path = urlparse(self.path).path
        if learning_get(self, path, parse_qs(urlparse(self.path).query)):
            return
        if path == '/api/progress':
            with db_connect() as con:
                self.send_json({'database_id': database_id(con), 'item': get_progress(con)})
        elif path == '/api/backup':
            with db_connect() as con:
                con.execute('BEGIN')
                data = export_backup(con)
            self.send_json(data)
        else:
            super().do_GET()

    @serialized
    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ('/api/import/preview', '/api/import', '/api/restore/preview', '/api/restore'):
            return super().do_POST()
        data = self.read_json()
        try:
            if data is None:
                raise ValueError('JSON không hợp lệ hoặc quá lớn.')
            if path.startswith('/api/import'):
                with db_connect() as con:
                    con.execute('BEGIN IMMEDIATE')
                    report = prepare_import(con, data)
                    if path == '/api/import':
                        if report['errors']:
                            self.send_json({'error': 'Hãy sửa hết dòng lỗi trước khi nhập.', **report}, 400)
                            return
                        con.executemany('INSERT INTO vocabulary(english,vietnamese,list_id) VALUES(?,?,?)',
                                        [(r['english'], r['vietnamese'], report['list_id']) for r in report['rows'] if r['status']=='new'])
                        con.commit()
                self.send_json(report)
                return
            clean = validate_backup(data.get('backup'))
            token = backup_token(clean)
            if path.endswith('/preview'):
                self.send_json({'token': token, 'lists': len(clean['lists']), 'words': len(clean['vocabulary']), 'has_progress': clean['progress'] is not None, 'history_count': len(clean['learning']['sessions'])})
                return
            if data.get('token') != token:
                raise ValueError('Nội dung đã thay đổi. Hãy kiểm tra bản sao lưu lại.')
            snapshot = snapshot_database()
            with db_connect() as con:
                con.execute('BEGIN IMMEDIATE')
                restore_learning(con, clean['learning'])
                con.execute('DELETE FROM vocabulary')
                con.execute('DELETE FROM vocabulary_lists')
                con.executemany('INSERT INTO vocabulary_lists(id,name,created_at) VALUES(:id,:name,:created_at)', clean['lists'])
                con.executemany('INSERT INTO vocabulary(id,english,vietnamese,list_id,created_at,part_of_speech,phonetic) VALUES(:id,:english,:vietnamese,:list_id,:created_at,:part_of_speech,:phonetic)', clean['vocabulary'])
                con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('progress',?)", (json.dumps(clean['progress'], ensure_ascii=False),))
                con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('seeded','1')")
                con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('database_id',?)", (uuid.uuid4().hex,))
                con.commit()
            self.send_json({'ok': True, 'safety_backup': snapshot})
        except (ValueError, sqlite3.IntegrityError) as exc:
            self.send_json({'error': str(exc)}, 400)

    @serialized
    def do_PUT(self):
        path = urlparse(self.path).path
        match = re.fullmatch(r'/api/lists/(\d+)', path)
        if path not in ('/api/progress','/api/review/progress') and not match:
            return super().do_PUT()
        data = self.read_json()
        try:
            if data is None:
                raise ValueError('JSON không hợp lệ.')
            with db_connect() as con:
                if path in ('/api/progress','/api/review/progress'):
                    item=data.get('item')
                    if path=='/api/progress':
                        validate_progress(item)
                        meta,records=match_learning(item)
                        old=get_progress(con)
                        old_id=(old or {}).get('learning',{}).get('id')
                        key='progress'
                    else:
                        validate_review(item)
                        meta,records=review_learning(item)
                        old=review_progress(con)
                        old_id=(old or {}).get('id')
                        key='review_progress'
                    if data.get('database_id') != database_id(con):
                        self.send_json({'error': 'Dữ liệu vừa được khôi phục. Hãy tải lại trang.'},409)
                        return
                    sync_learning(con,meta,records,old_id)
                    con.execute('INSERT OR REPLACE INTO app_meta(key,value) VALUES(?,?)',(key,json.dumps(item,ensure_ascii=False)))
                else:
                    name = normalize_text(data.get('name'), 80)
                    if not name:
                        raise ValueError('Tên list cần 1–80 ký tự.')
                    cur = con.execute('UPDATE vocabulary_lists SET name=? WHERE id=?', (name, int(match.group(1))))
                    if not cur.rowcount:
                        self.send_json({'error': 'List không tồn tại.'}, 404)
                        return
                con.commit()
            self.send_json({'ok': True})
        except sqlite3.IntegrityError:
            self.send_json({'error': 'Tên list đã tồn tại.'}, 409)
        except ValueError as exc:
            self.send_json({'error': str(exc)}, 400)

    @serialized
    def do_DELETE(self):
        return super().do_DELETE()

    def serve_static(self, path):
        allowed = {'/': 'index.html', '/index.html': 'index.html', '/app.js': 'app.js', '/review.js': 'review.js'}
        if path not in allowed or not (ROOT / allowed[path]).is_file():
            self.send_json({'error': 'Không tìm thấy tài nguyên.'}, 404)
            return
        p = ROOT / allowed[path]
        body = p.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8' if p.suffix == '.html' else 'application/javascript; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)


def main():
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f'English Match 2.2 đang chạy tại: http://{HOST}:{PORT}')
    print('Nhấn Ctrl+C để dừng.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nĐã dừng máy chủ.')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
