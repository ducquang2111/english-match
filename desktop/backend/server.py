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
            'SELECT v.id, v.english, v.vietnamese, v.list_id, v.created_at, '
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
                where.append('(v.english LIKE ? OR v.vietnamese LIKE ? OR l.name LIKE ?)')
                params.extend([like, like, like])

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
                        'INSERT INTO vocabulary (english, vietnamese, list_id) VALUES (?, ?, ?)',
                        (english, vietnamese, list_id),
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
                'SELECT id, english, vietnamese, list_id FROM vocabulary WHERE id=?',
                (item_id,),
            ).fetchone()
            if not current:
                self.send_json({'error': 'Không tìm thấy từ vựng.'}, 404)
                return

            english = current['english']
            vietnamese = current['vietnamese']
            list_id = current['list_id']

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
                    'UPDATE vocabulary SET english=?, vietnamese=?, list_id=? WHERE id=?',
                    (english, vietnamese, list_id, item_id),
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
MAX_BODY = 32 * 1024 * 1024


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
    return {'format': 'english-match-backup', 'version': 1,
            'exported_at': datetime.now(timezone.utc).isoformat(),
            'lists': [dict(r) for r in con.execute('SELECT * FROM vocabulary_lists ORDER BY id')],
            'vocabulary': [dict(r) for r in con.execute('SELECT * FROM vocabulary ORDER BY id')],
            'progress': get_progress(con)}


def validate_backup(raw):
    if not isinstance(raw, dict) or raw.get('format') != 'english-match-backup' or raw.get('version') != 1:
        raise ValueError('Hãy chọn file JSON được xuất từ English Match đợt 1.')
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
        clean_words.append({'id': r['id'], 'english': en, 'vietnamese': vi, 'list_id': r['list_id'], 'created_at': str(r.get('created_at', ''))[:100]})
    progress = raw.get('progress')
    validate_progress(progress)
    return {'lists': clean_lists, 'vocabulary': clean_words, 'progress': progress}


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


class AppHandler(LegacyHandler):
    server_version = 'EnglishMatch/2.1'

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
                self.send_json({'token': token, 'lists': len(clean['lists']), 'words': len(clean['vocabulary']), 'has_progress': clean['progress'] is not None})
                return
            if data.get('token') != token:
                raise ValueError('Nội dung đã thay đổi. Hãy kiểm tra bản sao lưu lại.')
            snapshot = snapshot_database()
            with db_connect() as con:
                con.execute('BEGIN IMMEDIATE')
                con.execute('DELETE FROM vocabulary')
                con.execute('DELETE FROM vocabulary_lists')
                con.executemany('INSERT INTO vocabulary_lists(id,name,created_at) VALUES(:id,:name,:created_at)', clean['lists'])
                con.executemany('INSERT INTO vocabulary(id,english,vietnamese,list_id,created_at) VALUES(:id,:english,:vietnamese,:list_id,:created_at)', clean['vocabulary'])
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
        if path != '/api/progress' and not match:
            return super().do_PUT()
        data = self.read_json()
        try:
            if data is None:
                raise ValueError('JSON không hợp lệ.')
            with db_connect() as con:
                if path == '/api/progress':
                    validate_progress(data.get('item'))
                    if data.get('database_id') != database_id(con):
                        self.send_json({'error': 'Dữ liệu vừa được khôi phục. Hãy tải lại trang.'}, 409)
                        return
                    con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('progress',?)", (json.dumps(data.get('item'), ensure_ascii=False),))
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
        allowed = {'/': 'index.html', '/index.html': 'index.html', '/app.js': 'app.js'}
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
    print(f'English Matching Game v2 đang chạy tại: http://{HOST}:{PORT}')
    print('Nhấn Ctrl+C để dừng.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nĐã dừng máy chủ.')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
