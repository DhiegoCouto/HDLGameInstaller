#!/usr/bin/env python3
from pathlib import Path
import sys

repo = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()

# Modern newlib uses the 3-argument wcstok interface.
osd_path = repo / "OSD.c"
if not osd_path.exists():
    raise SystemExit("OSD.c not found")

s = osd_path.read_text(encoding="utf-8")

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
osd_path.write_text(s, encoding="utf-8")

# mbslen was available in the old build environment but is not provided by
# current newlib. Count characters with the same mbtowc decoder used by the
# project's font renderer, so button centering follows the renderer exactly.
menu_path = repo / "menu.c"
if not menu_path.exists():
    raise SystemExit("menu.c not found")

s = menu_path.read_text(encoding="utf-8")
marker = 'static void DrawButton(const char *label, float x, float y, u64 TextColour, int IsSelected);'
helper = r'''static size_t GetMBStringLength(const char *string)
{
    const char *ptr;
    size_t count, remaining;
    wchar_t character;
    int charSize;

    if (string == NULL)
        return 0;

    ptr = string;
    count = 0;
    remaining = strlen(string) + 1;
    mbtowc(NULL, NULL, 0);

    while (*ptr != '\0') {
        charSize = mbtowc(&character, ptr, remaining);
        if (charSize <= 0) {
            /* Keep moving on malformed input instead of hanging. */
            charSize = 1;
            mbtowc(NULL, NULL, 0);
        }

        ptr += charSize;
        remaining -= charSize;
        count++;
    }

    return count;
}

'''
if marker not in s:
    raise SystemExit("DrawButton prototype marker not found")
s = s.replace(marker, helper + marker, 1)

old = '    FontPrintf(gsGlobal, (MAX_BTN_LAB_LEN - mbslen(label)) * BTN_FNT_CHAR_WIDTH + x, y, 1, 1.0f, TextColour, label);'
new = '    FontPrintf(gsGlobal, (MAX_BTN_LAB_LEN - GetMBStringLength(label)) * BTN_FNT_CHAR_WIDTH + x, y, 1, 1.0f, TextColour, label);'
if old not in s:
    raise SystemExit("mbslen call marker not found")
s = s.replace(old, new, 1)
menu_path.write_text(s, encoding="utf-8")

print("Legacy PS2SDK compatibility patch applied")
