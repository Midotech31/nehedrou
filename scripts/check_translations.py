"""Check literal UI gettext keys against each shipped translation catalogue."""
import ast
import gettext
import re
from pathlib import Path

root = Path(__file__).resolve().parent.parent
keys = set()
for folder in ['core', 'care', 'catalog']:
    for path in (root / folder).rglob('*.py'):
        if 'migrations' in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == '_' and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                keys.add(node.args[0].value)
for path in (root / 'templates').rglob('*.html'):
    matches = re.findall(r'''{%\s*(?:translate|trans)\s+(?:"([^"]+)"|'([^']+)')''', path.read_text(encoding='utf-8'))
    keys.update(a or b for a, b in matches)
failed = False
for language in ['fr', 'en', 'ar']:
    with (root / 'locale' / language / 'LC_MESSAGES' / 'django.mo').open('rb') as file:
        catalogue = gettext.GNUTranslations(file)._catalog
    missing = sorted(key for key in keys if key not in catalogue or not catalogue[key])
    print(language, len(keys), 'UI keys;', len(missing), 'missing')
    for key in missing:
        print('  ' + key)
    failed |= bool(missing)
raise SystemExit(1 if failed else 0)
