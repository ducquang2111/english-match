"""Old desktop databases must survive schema upgrades without losing words/progress."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import desktop_server


class UpgradeTests(unittest.TestCase):
    def test_old_words_progress_and_database_identity_survive(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder)/'vocabulary.db'
            old_progress = {'version':1,'scope':'all','updatedAt':100,'words':[{'id':7,'english':'my saved word','vietnamese':'từ đã lưu','list_id':2}], 'pages':[[7]],'pageIndex':0,'pageStates':[{'matched':[7],'wrong':1,'wrongIds':[7],'order':['7-en','7-vi']}]}
            with closing(sqlite3.connect(db)) as con:
                con.executescript('''
                    CREATE TABLE app_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                    CREATE TABLE vocabulary_lists(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL COLLATE NOCASE UNIQUE,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                    CREATE TABLE vocabulary(id INTEGER PRIMARY KEY AUTOINCREMENT,english TEXT NOT NULL COLLATE NOCASE,vietnamese TEXT NOT NULL,list_id INTEGER,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,UNIQUE(english,vietnamese));
                    INSERT INTO vocabulary_lists(id,name) VALUES(2,'My existing list');
                    INSERT INTO vocabulary(id,english,vietnamese,list_id) VALUES(7,'my saved word','từ đã lưu',2);
                    INSERT INTO app_meta VALUES('seeded','1');
                    INSERT INTO app_meta VALUES('database_id','existing-desktop-id');
                ''')
                con.execute('INSERT INTO app_meta VALUES(?,?)', ('progress', json.dumps(old_progress)))
                con.commit()
            previous = desktop_server.web.DB_PATH
            try:
                desktop_server.initialize(Path(folder))
                desktop_server.initialize(Path(folder))
                with desktop_server.web.db_connect() as con:
                    self.assertEqual(con.execute('SELECT count(*) FROM vocabulary').fetchone()[0],1)
                    details = con.execute('SELECT part_of_speech,phonetic FROM vocabulary').fetchone()
                    self.assertEqual(tuple(details), ('', ''))
                    self.assertEqual(con.execute('SELECT name FROM vocabulary_lists').fetchone()[0],'My existing list')
                    self.assertEqual(desktop_server.web.database_id(con),'existing-desktop-id')
                    self.assertEqual(desktop_server.web.get_progress(con),old_progress)
                    self.assertIsNone(desktop_server.web.review_progress(con))
                    self.assertEqual(desktop_server.web.learning_export(con)['sessions'],[])
            finally:
                desktop_server.web.DB_PATH=previous
