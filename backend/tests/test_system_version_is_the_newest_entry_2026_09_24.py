# -*- coding: utf-8 -*-
"""登入頁版本號 `GET /api/system/version` 必須是 manifest 裡**最新**的一筆，而不是第一筆。

HANDOFF T10：原本取 `entries[0]`，而 `version_manifest.json` **沒有排序保證**
⇒ 正式機 `c5b1e84` 回 `2026-09-22c`，同檔實際最新是 `2026-09-22g`。
2026-09-24 寫這支題時又撞到一次：第一筆是 `2026-09-24e`，最大是 `2026-09-24f`
（「前端介面」那一筆升了版本而位置沒動）。

版本字串是 `YYYY-MM-DD` ＋ 字母序號；序號比到 `z` 之後是 `aa` ⇒ **不可以直接比字串**
（字串比較下 `aa` < `z`）。
"""
import json
import random


def _write(tmp_path, entries):
    p = tmp_path / "version_manifest.json"
    p.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return str(p)


def _entry(version, date=None):
    return {"module": "m", "version": version, "date": date or version[:10], "time": "", "content": ""}


def test_a_shuffled_manifest_still_reports_the_newest_version(client, tmp_path, monkeypatch):
    import routers.auth as auth
    versions = ["2026-09-22c", "2026-09-22g", "2026-09-21", "2026-09-22a", "2026-09-20z"]
    rnd = random.Random(3)
    rnd.shuffle(versions)
    if versions[0] == "2026-09-22g":                    # 刻意讓「第一筆」不是最大的
        versions.append(versions.pop(0))
    monkeypatch.setattr(auth, "_MANIFEST_PATH", _write(tmp_path, [_entry(v) for v in versions]))
    r = client.get("/api/system/version")
    assert r.status_code == 200
    assert r.json() == {"version": "2026-09-22g", "date": "2026-09-22"}


def test_two_letter_suffix_is_newer_than_z(client, tmp_path, monkeypatch):
    import routers.auth as auth
    monkeypatch.setattr(auth, "_MANIFEST_PATH",
                        _write(tmp_path, [_entry("2026-09-24z"), _entry("2026-09-24aa"), _entry("2026-09-24b")]))
    assert client.get("/api/system/version").json()["version"] == "2026-09-24aa"


def test_the_date_comes_from_the_chosen_entry(client, tmp_path, monkeypatch):
    """有的舊條目 `version` 前綴與 `date` 不同（例如 2026-08-20k 的 date 是 08-21）⇒ 回傳那一筆自己的 date。"""
    import routers.auth as auth
    monkeypatch.setattr(auth, "_MANIFEST_PATH",
                        _write(tmp_path, [_entry("2026-08-20j", "2026-08-21"), _entry("2026-08-20k", "2026-08-21")]))
    assert client.get("/api/system/version").json() == {"version": "2026-08-20k", "date": "2026-08-21"}


def test_the_real_manifest_reports_its_maximum(client):
    """對真的 manifest：回傳值必須等於整份檔案裡最新的一筆（不論它排在哪）。"""
    import os
    import routers.auth as auth
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "version_manifest.json")
    entries = json.load(open(path, encoding="utf-8-sig"))
    want = max(entries, key=lambda e: auth._version_sort_key(e.get("version", "")))
    assert client.get("/api/system/version").json()["version"] == want["version"]
    assert want["version"] >= "2026-09-24"               # 量尺：不是空字串或很舊的一筆
