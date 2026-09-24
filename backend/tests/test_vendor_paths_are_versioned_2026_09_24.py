# -*- coding: utf-8 -*-
"""`/static/vendor/` 的每一項都要帶版本號（2026-09-24 NEXT：leaflet 目錄改帶版本）。

`main.py` 對 `/static/vendor/` 一律回 `Cache-Control: immutable`（一年）——前提是「升版一定換名字」。
名字不帶版本的話，升版後瀏覽器會繼續用舊檔一年，而沒有任何錯誤訊息。

另外兩道：
- 前端引用的 `static/vendor/...` 路徑都要真的存在（改名之後舊引用不能留著變 404）；
- leaflet 目錄的位元組仍是 PROVENANCE 記的那一份（搬目錄不可以動到內容）。
"""
import hashlib
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
VENDOR = os.path.join(ROOT, "frontend", "static", "vendor")
VERSION_RE = re.compile(r"\d+\.\d+(\.\d+)?")


def test_every_vendor_entry_carries_a_version():
    names = sorted(os.listdir(VENDOR))
    assert names, "vendor 目錄是空的——這一題的前提不成立"
    bad = [n for n in names if not VERSION_RE.search(n)]
    assert not bad, "這些 vendor 項目名稱沒有版本號（immutable 快取下升版會被卡一年）：%r" % bad


def _vendor_refs():
    refs = set()
    pat = re.compile(r"static/vendor/([^'\"`)\s?#]+)")
    for base in ("pages", "js", "."):
        d = os.path.join(ROOT, "frontend", base)
        for fn in os.listdir(d):
            if fn.endswith((".html", ".js")):
                text = open(os.path.join(d, fn), encoding="utf-8", errors="replace").read()
                refs.update(pat.findall(text))
    return refs


def test_every_vendor_reference_in_the_frontend_exists():
    refs = _vendor_refs()
    assert any(r.startswith("leaflet-") for r in refs), "正對照：map.html 對 leaflet 的引用要被掃到"
    missing = []
    for r in refs:
        # 字串拼接的前綴（例如 '.../leaflet.markercluster-1.5.3/' + f）只驗目錄
        p = os.path.join(VENDOR, *r.split("/"))
        if not os.path.exists(p):
            missing.append(r)
    assert not missing, "前端引用了不存在的 vendor 路徑：%r" % sorted(missing)


def test_leaflet_bytes_still_match_provenance():
    d = [n for n in os.listdir(VENDOR) if n.startswith("leaflet-")]
    assert d == ["leaflet-1.9.4"], d
    prov = open(os.path.join(VENDOR, d[0], "PROVENANCE.md"), encoding="utf-8").read()
    rows = re.findall(r"^([0-9a-f]{64})\s+(\S+)\s+(\d+) bytes$", prov, re.M)
    assert len(rows) == 5, rows
    for sha, rel, size in rows:
        data = open(os.path.join(VENDOR, d[0], *rel.split("/")), "rb").read()
        assert (hashlib.sha256(data).hexdigest(), len(data)) == (sha, int(size)), rel


def test_gitattributes_keeps_leaflet_bytes_raw():
    attrs = open(os.path.join(ROOT, ".gitattributes"), encoding="utf-8").read()
    assert "frontend/static/vendor/leaflet-1.9.4/** -text" in attrs
    assert "frontend/static/vendor/leaflet/** -text" not in attrs, "舊目錄的規則要跟著改名，不留死規則"
