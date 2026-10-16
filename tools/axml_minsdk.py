#!/usr/bin/env python3
"""Minimal Android binary-XML (AXML) reader.

Extracts the android:minSdkVersion / targetSdkVersion from an APK's
AndroidManifest.xml without needing aapt.

Usage: axml_minsdk.py path/to/app.apk
"""
import struct
import sys
import zipfile

# AXML chunk types
RES_STRING_POOL = 0x0001
RES_XML_START_ELEMENT = 0x0102
RES_XML_RESOURCE_MAP = 0x0180

# attribute data types
TYPE_STRING = 0x03
TYPE_REFERENCE = 0x01
TYPE_ATTRIBUTE = 0x02
TYPE_INT_DEC = 0x10
TYPE_INT_HEX = 0x11

# android resource ids
ATTR_MIN_SDK = 0x0101020C
ATTR_TARGET_SDK = 0x01010270


def read_string_pool(buf, off):
    """Return list of strings from a RES_STRING_POOL chunk at `off`."""
    (_type, _hs, size) = struct.unpack_from("<HHI", buf, off)
    (string_count, style_count, flags, strings_start, styles_start) = struct.unpack_from(
        "<IIIII", buf, off + 8)
    utf8 = bool(flags & (1 << 8))
    offsets = struct.unpack_from("<%dI" % string_count, buf, off + 28)
    base = off + strings_start
    out = []
    for o in offsets:
        p = base + o
        if utf8:
            # u8 len (possibly 2 bytes), u8 byte-length (possibly 2 bytes), bytes, \0
            n = buf[p]
            if n & 0x80:
                n = ((n & 0x7F) << 8) | buf[p + 1]
                p += 2
            else:
                p += 1
            blen = buf[p]
            if blen & 0x80:
                blen = ((blen & 0x7F) << 8) | buf[p + 1]
                p += 2
            else:
                p += 1
            out.append(buf[p:p + blen].decode("utf-8", "replace"))
        else:
            n = struct.unpack_from("<H", buf, p)[0]
            p += 2
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", buf, p)[0]
                p += 2
            out.append(buf[p:p + n * 2].decode("utf-16-le", "replace"))
    return out, size


def parse(buf):
    magic, filesize = struct.unpack_from("<II", buf, 0)
    if magic != 0x00080003:
        raise ValueError("not an AXML file (magic=%#x)" % magic)

    strings = []
    result = {}
    off = 8
    while off + 8 <= len(buf):
        ctype, chdr, csize = struct.unpack_from("<HHI", buf, off)
        if csize == 0:
            break
        if ctype == RES_STRING_POOL:
            strings, _ = read_string_pool(buf, off)
        elif ctype == RES_XML_START_ELEMENT:
            # res1(4) line(4) comment(4) ns(4) name(4) attrStart(2) attrSize(2)
            # attrCount(2) idIdx(2) classIdx(2) styleIdx(2)
            (_ns, name_idx, attr_start, attr_size, attr_count) = struct.unpack_from(
                "<IIHHH", buf, off + 16)
            elem = strings[name_idx] if name_idx < len(strings) else "?"
            attrs = {}
            aoff = off + 16 + attr_start
            for i in range(attr_count):
                a = aoff + i * attr_size
                (_ans, aname, araw, _tsize, _res0, dtype, data) = struct.unpack_from(
                    "<IIIHBBI", buf, a)
                key = strings[aname] if aname < len(strings) else ("%#x" % aname)
                if dtype == TYPE_STRING:
                    val = strings[data] if data < len(strings) else ("<str#%d>" % data)
                else:
                    val = data
                attrs[key] = (val, dtype, aname)
            result.setdefault(elem, []).append(attrs)
        off += csize
    return result


def main():
    apk = sys.argv[1]
    with zipfile.ZipFile(apk) as z:
        data = z.read("AndroidManifest.xml")
    tree = parse(data)
    print("APK:", apk)
    for elem, attrlist in tree.items():
        for attrs in attrlist:
            interesting = {k: v for k, v in attrs.items()
                           if k in ("minSdkVersion", "targetSdkVersion", "compileSdkVersion",
                                    "package", "versionName", "versionCode", "name",
                                    "platformBuildVersionCode", "platformBuildVersionName")}
            if interesting:
                print(" <%s>" % elem, interesting)


if __name__ == "__main__":
    main()
