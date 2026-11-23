"""Extract text from this PDF using only the standard library.

The file is a Chromium/Skia PDF with Type0/CIDFontType2 subset fonts and
four /ToUnicode CMaps. A CID font's byte codes are glyph indices, not
characters, so the strings in a content stream are meaningless until they
are mapped through the matching CMap.

The approach:
  1. parse every indirect object,
  2. find the /ToUnicode streams and parse their CMap into a
     code -> unicode table per font,
  3. map each page's /Resources /Font name to the CMap that belongs to it,
  4. decode the page's content strings two bytes at a time (CID fonts use
     two-byte codes) through that CMap.

No third-party library: H5 forbids a new dependency.
"""
import re
import sys
import zlib


# ---------------------------------------------------------------- objects

def parse_objects(raw):
    """Return {object_number: (dict_bytes, stream_bytes_or_None)}."""
    objects = {}
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", raw):
        num = int(m.group(1))
        start = m.end()
        end = raw.find(b"endobj", start)
        if end == -1:
            continue
        body = raw[start:end]
        stream = None
        smatch = re.search(rb"stream\r?\n", body)
        if smatch:
            sstart = smatch.end()
            send = body.find(b"endstream", sstart)
            if send == -1:
                send = len(body)
            stream = body[sstart:send]
            if stream.endswith(b"\r\n"):
                stream = stream[:-2]
            elif stream.endswith(b"\n") or stream.endswith(b"\r"):
                stream = stream[:-1]
            dict_part = body[:smatch.start()]
        else:
            dict_part = body
        objects[num] = (dict_part, stream)
    return objects


def inflate(data):
    try:
        return zlib.decompress(data)
    except zlib.error:
        d = zlib.decompressobj()
        try:
            return d.decompress(data)
        except zlib.error:
            return b""


# ----------------------------------------------------------------- cmaps

def parse_cmap(text):
    """Parse a ToUnicode CMap into {code_int: unicode_string}."""
    table = {}

    # bfchar: <src> <dst>
    for block in re.findall(rb"beginbfchar(.*?)endbfchar", text,
                            re.DOTALL):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>",
                                    block):
            code = int(src, 16)
            value = _utf16be(dst)
            if value is not None:
                table[code] = value

    # bfrange: <lo> <hi> <dst>   or   <lo> <hi> [ <d1> <d2> ... ]
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", text,
                            re.DOTALL):
        for m in re.finditer(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(\[[^\]]*\]|<[0-9A-Fa-f]*>)",
                block):
            lo = int(m.group(1), 16)
            hi = int(m.group(2), 16)
            target = m.group(3)
            if target.startswith(b"["):
                items = re.findall(rb"<([0-9A-Fa-f]*)>", target)
                for offset, item in enumerate(items):
                    value = _utf16be(item)
                    if value is not None:
                        table[lo + offset] = value
            else:
                hexval = target.strip(b"<>")
                base = _utf16be(hexval)
                if base is None:
                    continue
                for offset in range(hi - lo + 1):
                    if len(base) == 1:
                        table[lo + offset] = chr(ord(base) + offset)
                    else:
                        table[lo + offset] = base
    return table


def _utf16be(hexbytes):
    """Decode a UTF-16BE hex string from a CMap."""
    if not hexbytes:
        return ""
    try:
        raw = bytes.fromhex(hexbytes.decode("ascii"))
    except ValueError:
        return None
    if len(raw) % 2:
        raw += b"\x00"
    try:
        return raw.decode("utf-16-be")
    except UnicodeDecodeError:
        return raw.decode("utf-16-be", "replace")


# -------------------------------------------------------------- content

def content_strings(data):
    """Yield the byte strings shown by Tj / TJ / ' / " operators."""
    out = []
    i = 0
    n = len(data)
    while i < n:
        ch = data[i]
        if ch == 0x28:  # '('
            depth = 1
            i += 1
            buf = bytearray()
            while i < n and depth:
                c = data[i]
                if c == 0x5C:
                    i += 1
                    if i < n:
                        esc = data[i]
                        mapping = {0x6E: 10, 0x72: 13, 0x74: 9,
                                   0x62: 8, 0x66: 12}
                        if esc in mapping:
                            buf.append(mapping[esc])
                            i += 1
                        elif 0x30 <= esc <= 0x37:
                            digits = ""
                            while (i < n and len(digits) < 3
                                   and 0x30 <= data[i] <= 0x37):
                                digits += chr(data[i])
                                i += 1
                            buf.append(int(digits, 8) & 0xFF)
                        else:
                            buf.append(esc)
                            i += 1
                    continue
                if c == 0x28:
                    depth += 1
                elif c == 0x29:
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                buf.append(c)
                i += 1
            out.append(bytes(buf))
            continue
        if ch == 0x3C and i + 1 < n and data[i + 1] != 0x3C:  # hex
            i += 1
            digits = bytearray()
            while i < n and data[i] != 0x3E:
                c = data[i]
                if chr(c) in "0123456789abcdefABCDEF":
                    digits.append(c)
                i += 1
            i += 1
            if len(digits) % 2:
                digits.append(0x30)
            try:
                out.append(bytes.fromhex(digits.decode("ascii")))
            except ValueError:
                out.append(b"")
            continue
        i += 1
    return out


def decode_with(blob, table, two_byte):
    """Map a content string through a CMap table."""
    if not table:
        return blob.decode("latin-1", "replace")
    out = []
    if two_byte:
        for i in range(0, len(blob) - 1, 2):
            code = (blob[i] << 8) | blob[i + 1]
            out.append(table.get(code, ""))
    else:
        for byte in blob:
            out.append(table.get(byte, chr(byte)))
    return "".join(out)


def main(path):
    raw = open(path, "rb").read()
    objects = parse_objects(raw)

    # tounicode: {font object number: table}
    tounicode = {}
    for num, (d, s) in objects.items():
        if s is None:
            continue
        if b"/CMapName" in s or b"beginbfchar" in s or b"beginbfrange" in s:
            tounicode[num] = parse_cmap(s)

    # font resource name -> tounicode object number
    name_to_cmap = {}
    for num, (d, s) in objects.items():
        m = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", d)
        if m:
            name_to_cmap[num] = int(m.group(1))

    # /Font << /F1 5 0 R ... >> maps the resource name to the font object
    resource_map = {}
    for num, (d, s) in objects.items():
        if b"/Type" in d and b"/Font" in d:
            for name, ref in re.findall(rb"/(\w+)\s+(\d+)\s+\d+\s+R", d):
                resource_map[(num, name.decode("ascii"))] = int(ref)

    # Page -> font resource name -> tounicode table
    pages = []
    for num, (d, s) in objects.items():
        if b"/Type" in d and re.search(rb"/Type\s*/Page\b", d):
            fonts = {}
            fm = re.search(rb"/Font\s*<<(.*?)>>", d, re.DOTALL)
            if fm:
                for name, ref in re.findall(
                        rb"/(\w+)\s+(\d+)\s+\d+\s+R", fm.group(1)):
                    font_obj = int(ref)
                    cmap_obj = name_to_cmap.get(font_obj)
                    if cmap_obj is not None and cmap_obj in tounicode:
                        fonts[name.decode("ascii")] = tounicode[cmap_obj]
            content_refs = [int(x) for x in
                            re.findall(rb"/Contents\s+(\d+)\s+\d+\s+R", d)]
            pages.append((num, fonts, content_refs))

    # Fall back: any object with a /Font resource dict.
    if not pages:
        for num, (d, s) in objects.items():
            fm = re.search(rb"/Font\s*<<(.*?)>>", d, re.DOTALL)
            if fm and b"/Type" not in d:
                fonts = {}
                for name, ref in re.findall(
                        rb"/(\w+)\s+(\d+)\s+\d+\s+R", fm.group(1)):
                    font_obj = int(ref)
                    cmap_obj = name_to_cmap.get(font_obj)
                    if cmap_obj is not None and cmap_obj in tounicode:
                        fonts[name.decode("ascii")] = tounicode[cmap_obj]
                refs = [int(x) for x in
                        re.findall(rb"/Contents\s+(\d+)\s+\d+\s+R", d)]
                if refs:
                    pages.append((num, fonts, refs))

    for num, fonts, content_refs in pages:
        print("=== page object %d ===" % num)
        for ref in content_refs:
            d, s = objects.get(ref, (b"", None))
            if s is None:
                continue
            data = inflate(s) if b"FlateDecode" in d else s
            if not data:
                continue
            # Which font is current? Track /Fx Tf operators.
            current = None
            for token in re.finditer(
                    rb"/(\w+)\s+[\d.]+\s+Tf|(\((?:[^()\\]|\\.|\([^)]*\))*\))"
                    rb"|<([0-9A-Fa-f\s]*)>", data):
                if token.group(1):
                    current = token.group(1).decode("ascii")
                    continue
                blob = None
                if token.group(2):
                    blob = _literal_bytes(token.group(2))
                elif token.group(3) is not None:
                    hexs = re.sub(rb"\s", b"", token.group(3))
                    if len(hexs) % 2:
                        hexs += b"0"
                    try:
                        blob = bytes.fromhex(hexs.decode("ascii"))
                    except ValueError:
                        blob = b""
                if blob is None:
                    continue
                table = fonts.get(current)
                text = decode_with(blob, table, two_byte=bool(table))
                if text.strip():
                    print(text)


def _literal_bytes(token):
    """Strip the parentheses and unescape a literal string token."""
    body = token[1:-1]
    out = bytearray()
    i = 0
    while i < len(body):
        c = body[i]
        if c == 0x5C:
            i += 1
            if i < len(body):
                esc = body[i]
                mapping = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}
                if esc in mapping:
                    out.append(mapping[esc])
                    i += 1
                elif 0x30 <= esc <= 0x37:
                    digits = ""
                    while (i < len(body) and len(digits) < 3
                           and 0x30 <= body[i] <= 0x37):
                        digits += chr(body[i])
                        i += 1
                    out.append(int(digits, 8) & 0xFF)
                else:
                    out.append(esc)
                    i += 1
            continue
        out.append(c)
        i += 1
    return bytes(out)


if __name__ == "__main__":
    main(sys.argv[1])
