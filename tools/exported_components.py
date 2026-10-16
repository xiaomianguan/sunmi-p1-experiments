#!/usr/bin/env python3
"""List exported components of an APK and the permission (if any) guarding them.

Parses `aapt dump xmltree ... AndroidManifest.xml`, tracking element nesting by
indentation. Prints, per component:

  KIND  EXPORTED  PERMISSION  NAME  [intent-filter actions]

Usage: exported_components.py <apk> [<apk> ...]
       exported_components.py --free <apk> ...   # only unguarded+exported
"""
import re
import subprocess
import sys

AAPT = "/home/puffercat/Android/Sdk/build-tools/30.0.3/aapt"
KINDS = ("activity", "service", "receiver", "provider")

RE_ELEM = re.compile(r"^(\s*)E: (\S+)")
RE_ATTR = re.compile(r"^(\s*)A: (\S+?)(?:\(0x[0-9a-f]+\))?=(.*)$")


def parse(apk):
    out = subprocess.run(
        [AAPT, "dump", "xmltree", apk, "AndroidManifest.xml"],
        capture_output=True, text=True).stdout
    stack = []
    comps = []
    for ln in out.splitlines():
        m = RE_ELEM.match(ln)
        if m:
            indent, kind = len(m.group(1)), m.group(2)
            while stack and stack[-1][0] >= indent:
                stack.pop()
            node = {"kind": kind, "attrs": {}, "children": []}
            if stack:
                stack[-1][1]["children"].append(node)
            stack.append((indent, node))
            if kind in KINDS:
                comps.append(node)
            continue
        m = RE_ATTR.match(ln)
        if m and stack:
            indent, name, val = len(m.group(1)), m.group(2), m.group(3)
            while stack and stack[-1][0] >= indent:
                stack.pop()
            raw = re.search(r'\(Raw: "(.*)"\)\s*$', val)
            if raw:
                val = raw.group(1)
            val = val.strip().strip('"')
            if stack:
                stack[-1][1]["attrs"][name.split(":")[-1]] = val
    return comps


def actions(node):
    out = []

    def walk(n):
        for c in n["children"]:
            if c["kind"] in ("action", "category", "data"):
                k = c["kind"]
                v = c["attrs"].get("name") or c["attrs"].get("scheme") or "?"
                out.append(k[0] + ":" + v)
            walk(c)

    walk(node)
    return out


def truthy(v):
    return v is not None and v not in ("0x0", "false", "0", "")


def main():
    argv = sys.argv[1:]
    free_only = False
    if argv and argv[0] == "--free":
        free_only = True
        argv = argv[1:]
    for apk in argv:
        print("===== %s" % apk)
        for c in parse(apk):
            perm = c["attrs"].get("permission")
            has_filter = any(x["kind"] == "intent-filter" for x in c["children"])
            # pre-API-31 semantics: an intent filter implies exported
            exp = truthy(c["attrs"].get("exported")) or has_filter
            if not (exp or has_filter):
                continue
            if free_only and perm:
                continue
            print("  %-8s exported=%-5s perm=%-28s %s  %s" % (
                c["kind"], exp, perm or "-", c["attrs"].get("name", "?"),
                " ".join(actions(c)[:6])))


if __name__ == "__main__":
    main()
