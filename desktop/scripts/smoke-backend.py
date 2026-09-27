"""Exercise the real private server, then restart it and verify persisted data."""
import argparse
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('--frozen', action='store_true')
args = p.parse_args()
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with tempfile.TemporaryDirectory(prefix='English Match data ') as folder:
    token = secrets.token_hex(32)
    executable = ROOT/'build'/'backend'/'english-match-backend'/('english-match-backend.exe' if os.name == 'nt' else 'english-match-backend')
    command = [str(executable)] if args.frozen else [sys.executable, str(ROOT/'backend'/'desktop_server.py')]
    for stage in range(2):
        child = subprocess.Popen(command+['--data-dir',folder], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ,'ENGLISH_MATCH_DESKTOP_TOKEN':token,'PYTHONUNBUFFERED':'1','PYTHONIOENCODING':'utf-8'})
        try:
            lines = queue.Queue()
            threading.Thread(target=lambda: lines.put(child.stdout.readline()),daemon=True).start()
            line = lines.get(timeout=45)
            if not line:
                raise AssertionError(child.stderr.read().decode(errors='replace'))
            origin = json.loads(line)['origin']
            def api(method, path, data=None, status=200, authorized=True, extra=None):
                headers={'Content-Type':'application/json'}
                if authorized: headers['X-English-Match-Desktop']=token
                headers.update(extra or {})
                req=urllib.request.Request(origin+path,method=method,headers=headers,data=None if data is None else json.dumps(data).encode())
                try:
                    with opener.open(req,timeout=10) as r: code,body=r.status,r.read()
                except urllib.error.HTTPError as e: code,body=e.code,e.read()
                assert code==status,(code,status,body)
                return json.loads(body)
            api('GET','/api/stats',status=403,authorized=False)
            api('GET','/api/stats',status=403,extra={'Host':'example.com'})
            api('POST','/api/lists',{'name':'blocked'},status=403,extra={'Origin':'https://example.com'})
            for private in ['/server.py','/vocabulary.db','/../vocabulary.db','/initial-data.json']:
                api('GET',private,status=404)
            backup=api('GET','/api/backup')
            if stage==0:
                assert len(backup['vocabulary'])==16
                api('POST','/api/vocabulary',{'english':'persistent desktop word','vietnamese':'từ được lưu','list_id':1},201)
                words=api('GET','/api/vocabulary')['items']
                ids=[w['id'] for w in words];pages=[ids[i:i+8] for i in range(0,len(ids),8)]
                progress={'version':1,'scope':'all','words':words,'pages':pages,'pageIndex':0,'updatedAt':100,'pageStates':[{'matched':row[:1], 'wrong':0,'wrongIds':[], 'order':[f'{i}-{side}' for i in row for side in ('en','vi')]} for row in pages]}
                api('PUT','/api/progress',{'database_id':api('GET','/api/progress')['database_id'],'item':progress})
                backup=api('GET','/api/backup')
                preview=api('POST','/api/restore/preview',{'backup':backup})
                restored=api('POST','/api/restore',{'backup':backup,'token':preview['token']})
                assert (Path(folder)/'backups'/restored['safety_backup']).is_file()
            else:
                assert len(backup['vocabulary'])==17
                assert backup['progress']==progress
        finally:
            child.stdin.close()
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill();child.wait();raise AssertionError('Backend did not exit when parent pipe closed')
            assert child.returncode==0,child.stderr.read().decode(errors='replace')
    print('BACKEND_SMOKE_OK: access gate, seed, restore snapshot, persistence, graceful shutdown')
