"""Create bounded transport parts for clients with a 32 MiB download limit."""
from pathlib import Path
import hashlib
import json

root = Path(__file__).resolve().parents[1]
files = [p for p in (root/'release').iterdir() if p.suffix in ('.exe','.dmg')]
assert len(files) == 1, files
installer = files[0]
output = root/'delivery'
output.mkdir(exist_ok=True)
manifest = {'filename':installer.name, 'bytes':installer.stat().st_size, 'sha256':hashlib.sha256(installer.read_bytes()).hexdigest(), 'parts':[]}
with installer.open('rb') as src:
    for index in range(1,9):
        chunk = src.read(28*1024*1024)
        if not chunk: break
        name = f'part-{index}.bin'
        (output/name).write_bytes(chunk)
        manifest['parts'].append({'name':name,'bytes':len(chunk),'sha256':hashlib.sha256(chunk).hexdigest()})
    assert not src.read(1), 'Installer exceeds delivery capacity'
(output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print('Prepared',len(manifest['parts']),'transport parts for',installer.name)
