#!/usr/bin/env python3
from pathlib import Path
import sys

repo = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
path = repo / "OSD.c"
if not path.exists():
    raise SystemExit("OSD.c not found")

s = path.read_text(encoding="utf-8")

old = '    wchar_t *line, *value, *buffer;'
new = '    wchar_t *line, *value, *buffer, *wcstokContext;'
if old not in s:
    raise SystemExit("ParseIconSysFile declaration marker not found")
s = s.replace(old, new, 1)

old = '        line = wcstok(buffer, L"\\r\\n");'
new = '        wcstokContext = NULL;\n        line = wcstok(buffer, L"\\r\\n", &wcstokContext);'
if old not in s:
    raise SystemExit("first wcstok marker not found")
s = s.replace(old, new, 1)

old = '            while ((line = wcstok(NULL, L"\\r\\n")) != NULL) {'
new = '            while ((line = wcstok(NULL, L"\\r\\n", &wcstokContext)) != NULL) {'
if old not in s:
    raise SystemExit("second wcstok marker not found")
s = s.replace(old, new, 1)

path.write_text(s, encoding="utf-8")
print("Legacy PS2SDK compatibility patch applied")
