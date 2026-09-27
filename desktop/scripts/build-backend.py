"""Build on each target OS/architecture; PyInstaller does not cross-compile."""
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
        '--name', 'english-match-backend', '--distpath', str(ROOT/'build'/'backend'),
        '--workpath', str(ROOT/'build'/'pyinstaller'), '--specpath', str(ROOT/'build')]
for name in ['index.html', 'app.js', 'review.js', 'initial-data.json']:
    args += ['--add-data', str(ROOT/'backend'/name) + ':.']
args += [str(ROOT/'backend'/'desktop_server.py')]
subprocess.run(args, cwd=ROOT, check=True)
