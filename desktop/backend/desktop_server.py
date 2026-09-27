"""Private loopback server owned by the desktop application, never an online server."""
import argparse
import hmac
import json
import os
from pathlib import Path
import signal
import sys
import threading
import server as web


def initialize(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    web.DB_PATH = data_dir / 'vocabulary.db'
    if not web.DB_PATH.exists():
        # Build the initial database atomically. Never seed over existing user data.
        destination = web.DB_PATH
        web.DB_PATH = data_dir / 'vocabulary.initializing.db'
        web.DB_PATH.unlink(missing_ok=True)
        try:
            web.init_db()
            clean = web.validate_backup(json.loads((web.ROOT / 'initial-data.json').read_text(encoding='utf-8')))
            with web.db_connect() as con:
                con.execute('DELETE FROM vocabulary')
                con.execute('DELETE FROM vocabulary_lists')
                con.executemany('INSERT INTO vocabulary_lists(id,name,created_at) VALUES(:id,:name,:created_at)', clean['lists'])
                con.executemany('INSERT INTO vocabulary(id,english,vietnamese,list_id,created_at) VALUES(:id,:english,:vietnamese,:list_id,:created_at)', clean['vocabulary'])
                con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('progress',?)", (json.dumps(clean['progress'], ensure_ascii=False),))
            os.replace(web.DB_PATH, destination)
        finally:
            web.DB_PATH = destination
    web.init_db()


class DesktopHandler(web.AppHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def parse_request(self):
        if not super().parse_request():
            return False
        expected_host = '127.0.0.1:' + str(self.server.server_port)
        supplied = self.headers.get('X-English-Match-Desktop', '')
        valid = hmac.compare_digest(supplied.encode('utf-8'), self.server.desktop_token.encode('ascii'))
        if not valid or self.headers.get('Host') != expected_host:
            self.send_json({'error': 'Chỉ ứng dụng English Match được truy cập.'}, 403)
            return False
        return True

    def end_headers(self):
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        super().end_headers()

    def log_message(self, *_):
        pass


class DesktopHTTPServer(web.ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', required=True)
    args = parser.parse_args()
    token = os.environ.get('ENGLISH_MATCH_DESKTOP_TOKEN', '')
    if len(token) < 40 or not token.isascii():
        raise RuntimeError('Desktop launch token is required.')
    initialize(Path(args.data_dir).resolve())
    http = DesktopHTTPServer(('127.0.0.1', 0), DesktopHandler)
    http.desktop_token = token

    def stop(*_):
        threading.Thread(target=http.shutdown, daemon=True).start()

    def watch_parent():
        # The pipe closes even if Electron crashes, preventing orphan servers.
        sys.stdin.buffer.read()
        stop()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    threading.Thread(target=watch_parent, daemon=True).start()
    print(json.dumps({'event': 'ready', 'origin': 'http://127.0.0.1:' + str(http.server_port)}), flush=True)
    try:
        http.serve_forever(poll_interval=0.15)
    finally:
        http.server_close()


if __name__ == '__main__':
    main()
