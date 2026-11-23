"""Inspect the PDF for a ToUnicode CMap or an encoding we can use."""
import re
import sys

path = r"D:\AI-Projects\laya-gateway\docs\MASTER_CONTEXT.pdf"
raw = open(path, "rb").read()

print("size:", len(raw))
print("header:", raw[:16])
print("has /ToUnicode:", raw.count(b"/ToUnicode"))
print("has /Font:", raw.count(b"/Font"))
print("has /Encoding:", raw.count(b"/Encoding"))
print("has /Differences:", raw.count(b"/Differences"))
print("has ObjStm:", raw.count(b"/ObjStm"))
print("has /XRef:", raw.count(b"/XRef"))
print("producer:", re.findall(rb"/Producer\s*\(([^)]*)\)", raw)[:3])
print("creator:", re.findall(rb"/Creator\s*\(([^)]*)\)", raw)[:3])
print("filters:", set(re.findall(rb"/Filter\s*/(\w+)", raw)))
print("subtypes:", set(re.findall(rb"/Subtype\s*/(\w+)", raw)))
print("basefonts:", set(re.findall(rb"/BaseFont\s*/([\w+#-]+)", raw)))
print("pages:", raw.count(b"/Type /Page"), raw.count(b"/Type/Page"))
