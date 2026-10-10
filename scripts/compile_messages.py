"""Compile the included simple msgid/msgstr PO files without system gettext.
For advanced/plural PO entries, use Django compilemessages with GNU gettext.
"""
import json
import struct
from pathlib import Path

root = Path(__file__).resolve().parent.parent
for file in (root / 'locale').glob('*/LC_MESSAGES/django.po'):
    messages = {}
    key = None
    for line in file.read_text(encoding='utf-8').splitlines():
        if line.startswith('msgid '):
            key = json.loads(line[6:])
        elif line.startswith('msgstr '):
            messages[key] = json.loads(line[7:])
    originals, translations, ot, tt = b'', b'', [], []
    count = len(messages)
    offset = 28 + 16 * count
    for key in sorted(messages):
        a, b = key.encode(), messages[key].encode()
        ot.append((len(a), offset + len(originals)))
        tt.append((len(b), len(translations)))
        originals += a + b'\0'
        translations += b + b'\0'
    data = struct.pack('<7I', 0x950412de, 0, count, 28, 28 + 8 * count, 0, 0)
    data += b''.join(struct.pack('<2I', *row) for row in ot)
    data += b''.join(struct.pack('<2I', size, offset + len(originals) + pos) for size, pos in tt)
    file.with_suffix('.mo').write_bytes(data + originals + translations)
    print(file.parent.parent.name, count, 'messages')
