from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import json
import mimetypes
import sqlite3
import re
import os
import shutil

ROOT = Path(__file__).resolve().parent

# Local: dùng vocabulary.db trong thư mục source như trước.
# Khi deploy (ví dụ Railway), đặt biến môi trường DB_PATH=/data/vocabulary.db
# và gắn Persistent Volume vào /data để dữ liệu không mất sau redeploy/restart.
BUNDLED_DB_PATH = ROOT / 'vocabulary.db'
DB_PATH = Path(os.environ.get('DB_PATH', str(BUNDLED_DB_PATH))).expanduser()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Lần deploy đầu tiên: nếu Volume còn trống nhưng source có DB cũ,
# tự copy DB cũ sang Volume để giữ nguyên các list/từ vựng hiện có.
if DB_PATH.resolve() != BUNDLED_DB_PATH.resolve() and not DB_PATH.exists() and BUNDLED_DB_PATH.exists():
    shutil.copy2(BUNDLED_DB_PATH, DB_PATH)

HOST = os.environ.get('HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT', '8000'))

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
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    con.execute('PRAGMA busy_timeout = 5000')
    return con


def normalize_text(value, max_len):
    text = re.sub(r'\s+', ' ', str(value or '').strip())
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

        default_list_id = get_default_list_id(con)

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

        # Any old/unassigned words are moved into the default list.
        con.execute(
            'UPDATE vocabulary SET list_id=? WHERE list_id IS NULL OR list_id NOT IN (SELECT id FROM vocabulary_lists)',
            (default_list_id,),
        )

        seeded = con.execute("SELECT value FROM app_meta WHERE key='seeded'").fetchone()
        if not seeded:
            con.executemany(
                'INSERT OR IGNORE INTO vocabulary (english, vietnamese, list_id) VALUES (?, ?, ?)',
                [(en, vi, default_list_id) for en, vi in SEED_VOCAB],
            )
            con.execute("INSERT OR REPLACE INTO app_meta(key, value) VALUES('seeded', '1')")

        con.commit()


class AppHandler(BaseHTTPRequestHandler):
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

        if parsed.path == '/health':
            self.send_json({'ok': True})
            return

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

        if parsed.path == '/health':
            self.send_json({'ok': True})
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


def main():
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f'English Matching Game v2 đang chạy tại: http://{HOST}:{PORT}')
    print(f'Database: {DB_PATH}')
    print('Nhấn Ctrl+C để dừng.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nĐã dừng máy chủ.')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
