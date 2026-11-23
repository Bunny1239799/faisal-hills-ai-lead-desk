import re
import sys

sys.path.insert(0, r"D:\AI-Projects\laya-gateway\tools")
from _pdf_text import parse_objects, parse_cmap, inflate

path = r"D:\AI-Projects\laya-gateway\docs\MASTER_CONTEXT.pdf"
raw = open(path, "rb").read()
objects = parse_objects(raw)

print("objects:", len(objects))

tounicode = {}
for num, (d, s) in objects.items():
    if s is None:
        continue
    if b"/CMapName" in s or b"beginbfchar" in s or b"beginbfrange" in s:
        tounicode[num] = parse_cmap(s)
        print("cmap obj %d -> %d entries" % (num, len(tounicode[num])))
        if tounicode[num]:
            items = list(tounicode[num].items())[:8]
            print("     sample:", items)

print()
print("--- font objects (/ToUnicode refs) ---")
name_to_cmap = {}
for num, (d, s) in objects.items():
    m = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", d)
    if m:
        name_to_cmap[num] = int(m.group(1))
        print("font obj %d -> cmap %d ; dict head: %r" % (
            num, int(m.group(1)), d[:160]))
print()
print("--- pages and their /Font dicts ---")
for num, (d, s) in objects.items():
    if re.search(rb"/Type\s*/Page\b", d):
        print("page obj", num)
        fm = re.search(rb"/Font\s*<<(.*?)>>", d, re.DOTALL)
        print("   /Font raw:", (fm.group(1)[:300] if fm else None))
        print("   /Resources raw:", re.findall(rb"/Resources[^\n]{0,200}", d)[:2])
        print("   dict head:", d[:300])
        break
