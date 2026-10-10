"""Render build: reproducible dependencies, translations and static assets."""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
for args in [
    ['-m', 'pip', 'install', '--require-hashes', '-r', 'requirements.lock'],
    ['scripts/compile_messages.py'],
    ['scripts/check_translations.py'],
    ['manage.py', 'collectstatic', '--noinput'],
    ['manage.py', 'check'],
]:
    subprocess.run([sys.executable, *args], cwd=root, check=True)
