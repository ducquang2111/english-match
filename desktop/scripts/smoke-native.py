"""Start the packaged application twice on a real Windows/macOS runner."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if sys.platform == 'win32':
    executable = ROOT/'release'/'win-unpacked'/'English Match.exe'
elif sys.platform == 'darwin':
    matches = list((ROOT/'release').glob('mac*/English Match.app/Contents/MacOS/English Match'))
    assert len(matches) == 1, matches
    executable = matches[0]
else:
    raise SystemExit('Run this on a Windows or macOS runner.')
with tempfile.TemporaryDirectory(prefix='English Match native ') as folder:
    for stage in ['create','verify']:
        env = {**os.environ, 'EM_SMOKE_DATA':folder, 'EM_SMOKE_OUTPUT':str(ROOT/'test-results'), 'EM_SMOKE_STAGE':stage}
        subprocess.run([str(executable),'--smoke-test'], env=env, timeout=90, check=True)
        assert (ROOT/'test-results'/f'{stage}.json').is_file(), 'Application exited without completing the smoke test'
print('PACKAGED_NATIVE_APP_OK: both launches, matching, flashcards, typing, wrong-word review, history, saving, isolated renderer')
