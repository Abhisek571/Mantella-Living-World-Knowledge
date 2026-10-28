"""Stream Skyrim pages out of MediaWiki XML dumps (UESP .bz2, Fandom .7z or plain .xml).

Output: one JSON line per page {src, title, text} in a gzip file, so the slow
dump pass runs once and the lore build can be re-run quickly.
"""
import bz2
import gzip
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

SEVEN_ZIP_CANDIDATES = [
    "7z", "7za",
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
]


def _find_7z():
    for c in SEVEN_ZIP_CANDIDATES:
        p = shutil.which(c) or (c if os.path.isfile(c) else None)
        if p:
            return p
    raise RuntimeError("7-Zip not found; extract the .7z dump to .xml first")


def open_dump(path):
    """Return a binary stream of the XML inside path."""
    low = path.lower()
    if low.endswith(".bz2"):
        return bz2.open(path, "rb")
    if low.endswith(".7z"):
        proc = subprocess.Popen([_find_7z(), "e", "-so", path], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
        return proc.stdout
    return open(path, "rb")


def iter_pages(stream):
    """Yield (ns, title, text, is_redirect) for each page; memory stays flat."""
    ctx = ET.iterparse(stream, events=("start", "end"))
    _, root = next(ctx)
    ns = title = text = None
    redirect = False
    for ev, el in ctx:
        if ev != "end":
            continue
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "title":
            title = el.text or ""
        elif tag == "ns":
            ns = int(el.text or 0)
        elif tag == "redirect":
            redirect = True
        elif tag == "text":
            text = el.text or ""
        elif tag == "page":
            yield ns, title, text or "", redirect
            ns = title = text = None
            redirect = False
            root.clear()


def uesp_wanted(ns, title, text, redirect):
    return title.startswith("Skyrim:") and not redirect


def fandom_wanted(ns, title, text, redirect):
    if ns != 0 or redirect:
        return False
    return "[[Category:Skyrim" in text or "{{Skyrim" in text[:400]


def uesp_redirects(ns, title, text, redirect):
    return title.startswith("Skyrim:") and redirect


def extract(dump, src, out_path):
    wanted = uesp_wanted if src == "uesp" else fandom_wanted
    n = 0
    redirects = {}
    with gzip.open(out_path, "wt", encoding="utf-8") as out:
        for ns, title, text, redirect in iter_pages(open_dump(dump)):
            if redirect and title.startswith("Skyrim:"):
                tgt = text.split("[[", 1)[-1].split("]]", 1)[0].split("#", 1)[0]
                redirects[title] = tgt
                continue
            if wanted(ns, title, text, redirect):
                out.write(json.dumps({"src": src, "title": title, "text": text}) + "\n")
                n += 1
        if redirects:
            out.write(json.dumps({"src": src, "title": "__redirects__", "redirects": redirects}) + "\n")
    return n


if __name__ == "__main__":
    dump, src, out_path = sys.argv[1:4]
    print(src, extract(dump, src, out_path), "pages")
