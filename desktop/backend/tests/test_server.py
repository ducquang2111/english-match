"""Run: python3 -m unittest discover -s tests -v. Disposable databases only."""
import importlib.util
import json
import shutil
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
import urllib.request
import urllib.error
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        spec = importlib.util.spec_from_file_location('app', ROOT/'server.py')
        self.app = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.app)
        self.app.ROOT = self.folder; self.app.DB_PATH = self.folder/'vocabulary.db'
        for n in ('index.html','app.js','server.py'): shutil.copy2(ROOT/n, self.folder/n)
        self.app.init_db(); self.app.AppHandler.log_message = lambda *a: None
        self.http = self.app.ThreadingHTTPServer(('127.0.0.1',0), self.app.AppHandler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True); self.thread.start()
        self.url = 'http://127.0.0.1:'+str(self.http.server_port)
    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join(); self.tmp.cleanup()
    def api(self, method, path, data=None, expected=200):
        req = urllib.request.Request(self.url+path, method=method, data=None if data is None else json.dumps(data).encode(), headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req) as r: status, raw = r.status, r.read()
        except urllib.error.HTTPError as e: status, raw = e.code, e.read()
        self.assertEqual(status,expected,raw)
        return json.loads(raw)
    def progress(self):
        words=self.api('GET','/api/vocabulary')['items']; pages=[[w['id'] for w in words[:8]],[w['id'] for w in words[8:]]]
        return {'version':1,'scope':'all','words':words,'pages':pages,'pageIndex':0,'updatedAt':100,
                'pageStates':[{'matched':ids[:1], 'wrong':1, 'wrongIds':ids[:1], 'order':[f'{i}-{side}' for i in ids for side in ('en','vi')]} for ids in pages]}
    def test_crud_rename_restart(self):
        self.api('PUT','/api/lists/1',{'name':'Travel'})
        l=self.api('POST','/api/lists',{'name':'Work'},201)['item']['id']
        w=self.api('POST','/api/vocabulary',{'english':' test  word ','vietnamese':'từ thử','list_id':1},201)['item']
        self.assertEqual(w['english'],'test word')
        self.api('PUT',f"/api/vocabulary/{w['id']}",{'english':'edited','vietnamese':'đã sửa','list_id':l})
        self.api('DELETE',f'/api/lists/{l}',expected=409)
        self.app.init_db()
        self.assertEqual([x['name'] for x in self.api('GET','/api/lists')['items']],['Travel','Work'])
        self.api('DELETE',f"/api/vocabulary/{w['id']}")
        self.api('DELETE',f'/api/lists/{l}')
    def test_import_preview_apply_and_duplicates(self):
        data={'list_id':1,'text':'english,vietnamese\nnoon,giữa trưa\nnew,"nghĩa, mới"\nNEW,"nghĩa, mới"'}
        r=self.api('POST','/api/import/preview',data)
        self.assertEqual((r['new'],r['duplicates'],r['errors']),(1,2,0))
        self.assertEqual(self.api('GET','/api/stats')['total_vocabulary'],16)
        self.api('POST','/api/import',data)
        self.assertEqual(self.api('GET','/api/stats')['total_vocabulary'],17)
    def test_import_error_is_atomic(self):
        self.api('POST','/api/import',{'list_id':1,'text':'another | khác\nmissing','delimiter':'|'},400)
        self.assertEqual(self.api('GET','/api/vocabulary?search=another')['total'],0)
        for text,d in [('tab\tnghĩa tab','auto'),('pipe | nghĩa gạch','|'),('semi;nghĩa chấm phẩy',';')]:
            self.assertEqual(self.api('POST','/api/import',{'list_id':1,'text':text,'delimiter':d})['new'],1)
    def test_progress_and_restore(self):
        dbid=self.api('GET','/api/progress')['database_id']; p=self.progress()
        self.api('PUT','/api/progress',{'database_id':dbid,'item':p}); self.app.init_db()
        self.assertEqual(self.api('GET','/api/progress')['item'],p)
        backup=self.api('GET','/api/backup'); self.api('DELETE','/api/vocabulary/1')
        preview=self.api('POST','/api/restore/preview',{'backup':backup})
        r=self.api('POST','/api/restore',{'backup':backup,'token':preview['token']})
        with closing(sqlite3.connect(self.folder/'backups'/r['safety_backup'])) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM vocabulary').fetchone()[0],15)
        self.assertEqual(self.api('GET','/api/stats')['total_vocabulary'],16)
        self.assertEqual(self.api('GET','/api/progress')['item'],p)
        self.api('PUT','/api/progress',{'database_id':dbid,'item':p},409)
    def test_invalid_restore_untouched(self):
        b=self.api('GET','/api/backup'); b['vocabulary'][0]['list_id']=999
        self.api('POST','/api/restore/preview',{'backup':b},400)
        self.assertEqual(self.api('GET','/api/stats')['total_vocabulary'],16)
        b=self.api('GET','/api/backup'); t=self.api('POST','/api/restore/preview',{'backup':b})['token']
        b['vocabulary'][0]['english']='changed'
        self.api('POST','/api/restore',{'backup':b,'token':t},400)
    def test_empty_backup_stays_empty(self):
        b={'format':'english-match-backup','version':1,'lists':[],'vocabulary':[],'progress':None}
        t=self.api('POST','/api/restore/preview',{'backup':b})['token']
        self.api('POST','/api/restore',{'backup':b,'token':t}); self.app.init_db()
        self.assertEqual(self.api('GET','/api/stats'),{'total_vocabulary':0,'total_lists':0})
    def test_private_files_blocked(self):
        for p in ['/vocabulary.db','/server.py','/backups/x.db','/../server.py','/api/no']:
            self.api('GET',p,expected=404)
    def test_invalid_json_and_progress(self):
        self.api('POST','/api/lists',['bad'],400)
        self.api('POST','/api/lists',{'name':{}},400)
        self.api('POST','/api/lists',{'name':'LIST 1'},409)
        p=self.progress(); p['pageStates'][0]['matched']=[999]
        self.api('PUT','/api/progress',{'item':p,'database_id':self.api('GET','/api/progress')['database_id']},400)
    def test_old_database_migration(self):
        old=self.folder/'legacy.db'
        with closing(sqlite3.connect(old)) as c:
            c.execute('CREATE TABLE vocabulary(id INTEGER PRIMARY KEY AUTOINCREMENT,english TEXT NOT NULL COLLATE NOCASE,vietnamese TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,UNIQUE(english,vietnamese))')
            c.execute("INSERT INTO vocabulary(english,vietnamese) VALUES('legacy custom','dữ liệu cũ')")
            c.commit()
        self.app.DB_PATH=old; self.app.init_db()
        self.assertEqual(self.api('GET','/api/vocabulary?search=legacy')['total'],1)

if __name__=='__main__': unittest.main()
