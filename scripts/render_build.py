"""Render build: reproducible dependencies, translations and static assets."""
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent


def run(*args, env=None):
    subprocess.run([sys.executable, *args], cwd=root, check=True, env=env)


run('-m', 'pip', 'install', '--require-hashes', '-r', 'requirements.lock')
run('scripts/compile_messages.py')
run('scripts/check_translations.py')
# Build the runtime manifest even when the image build uses local Django defaults.
run('manage.py', 'collectstatic', '--noinput', env={**os.environ, 'NEHEDROU_BUILD_STATIC_MANIFEST': '1'})
run('manage.py', 'check')
