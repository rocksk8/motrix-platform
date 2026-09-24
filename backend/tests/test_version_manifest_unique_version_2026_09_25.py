"""版本紀錄：新條目的版本號不可與任何其他條目重複。

☠️ 2026-09-25（hichan-8d）：rebase 後兩筆條目同為 `2026-09-25e`（供應商狀態下拉／登入頁 Enter），
`test_version_manifest_2026_09_22.py` 全綠——它驗「一個模組一筆」（VR3），沒有任何一題驗版本號唯一。
各視窗平行寫 manifest、先推先拿號，撞號只會在 rebase 之後出現，而那時沒有人會回頭看號碼。

⚠ 不可追溯要求：歷史上本來就有 23 個版本號同時掛在不同模組上（最晚 2026-09-11l）。
   ⇒ 只要求**日期在 CUTOFF 以後**的條目，其版本號在整份檔案裡唯一（也不可以撿舊的號碼重用）。
"""
import collections
import json
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent.parent / "version_manifest.json"

#: 這一天起的條目要求版本號唯一（使用者裁示 2026-09-25，經 hichan-0a）
CUTOFF = "2026-09-25"


def _entries():
    # utf-8-sig：與產品讀法相同（PS 5.1 重寫過會帶 BOM）
    with MANIFEST.open(encoding="utf-8-sig") as f:
        return json.load(f)


def colliding_versions(entries, since=CUTOFF):
    """回傳 {版本號: [模組, …]}：至少有一筆日期 >= since、而版本號被兩筆以上條目使用。"""
    by_ver = collections.defaultdict(list)
    for e in entries:
        by_ver[e.get("version")].append(e)
    return {v: [e.get("module") for e in es] for v, es in by_ver.items()
            if len(es) > 1 and any((e.get("date") or "") >= since for e in es)}


def test_new_entries_have_unique_version_numbers():
    bad = colliding_versions(_entries())
    assert not bad, ("版本號重複（rebase 後撞號？先推的人拿號，後到的改用下一個字母）：%s" % bad)


def test_the_guard_catches_a_collision_and_leaves_history_alone():
    """正對照＋不追溯。"""
    new_a = {"version": "2026-09-26a", "date": "2026-09-26", "module": "甲"}
    new_b = {"version": "2026-09-26a", "date": "2026-09-26", "module": "乙"}
    assert colliding_versions([new_a, new_b]) == {"2026-09-26a": ["甲", "乙"]}
    # 新條目撿一個舊的號碼重用也算
    old = {"version": "2026-09-11l", "date": "2026-09-11", "module": "系統設定"}
    reuse = {"version": "2026-09-11l", "date": "2026-09-26", "module": "丙"}
    assert colliding_versions([old, reuse]) == {"2026-09-11l": ["系統設定", "丙"]}
    # 歷史上的重複（兩筆都早於 CUTOFF）不追究
    old2 = {"version": "2026-09-11l", "date": "2026-09-11", "module": "營運報表/應收帳款"}
    assert colliding_versions([old, old2]) == {}
    # 真實檔案：歷史重複確實存在（否則「不追溯」這個分支從來沒被走過）
    hist = colliding_versions(_entries(), since="0000")
    assert hist, "預期真實檔案裡有歷史重複（2026-07～09-11）；若已被清掉，這一段可以拿掉"
    assert all(v < CUTOFF for v in hist), "歷史重複以外出現了新的重複：%s" % sorted(v for v in hist if v >= CUTOFF)
