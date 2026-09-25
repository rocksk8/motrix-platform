"""案件存取守門下沉 L1 `helpers/case_access.py`（主持裁示 2026-09-26，DEPENDENCY-MAP §3.2）。

① 同一份規則：helpers.quotations 的同名匯入就是 L1 那一份，row_access 登錄的也是它
② 已知例外只有一個：L1 新增讀 M01 `quotations` 表的檔案 ⇒ 紅（既有的讀取列在基線、次數只准變少）
③ 反向控制：M01 不在（案件表不存在）⇒ `guard_case_access` 回 404，不放行、不 500
"""
import json
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from core import source_tree

REPO = Path(__file__).resolve().parents[3]
_READ = re.compile(r"\b(FROM|JOIN)\s+quotations\b", re.I)

#: 2026-09-26 下沉當下，L1 裡已經在讀 quotations 的檔案與次數（DEPENDENCY-MAP §3.2：讀取相依待各自切斷）。
#: 只准變少：次數減少時把這裡改小；新檔案不可以加進來——要讀案件資料，經 M01 的提供者或 case_access。
KNOWN_L1_READERS = {
    "archive.py": 3, "db.py": 9, "pdf_gen.py": 5,
    "helpers/audit.py": 5, "helpers/company_identity.py": 2, "helpers/google_calendar.py": 4,
    "routers/item_reads.py": 1, "routers/search.py": 1, "routers/system.py": 2,
}
OWNER = "helpers/case_access.py"


def _l1_files():
    units = json.loads((REPO / "docs" / "platform" / "modules.json").read_text(encoding="utf-8"))["L1"]["units"]
    out = []
    for u in units:
        kind, _, name = u.partition(":")
        rel = {"router": "routers/%s.py", "helper": "helpers/%s.py", "core": "%s.py"}.get(kind)
        if rel and (source_tree.BACKEND / (rel % name)).is_file():
            out.append(rel % name)
    return out


def readers(files_text):
    """{相對路徑: 原始碼} ⇒ {相對路徑: 讀 quotations 的次數}（0 次不列）。"""
    return {f: n for f, t in files_text.items() if (n := len(_READ.findall(t)))}


def excess(found, known=KNOWN_L1_READERS, owner=OWNER):
    return sorted("%s：%d 次（基線 %d）" % (f, n, known.get(f, 0)) for f, n in found.items()
                  if f != owner and n > known.get(f, 0))


def test_same_rule_everywhere():
    from helpers import case_access as ca, quotations as hq, row_access as ra
    import helpers
    assert hq.CASE_ACCESS is ca.CASE_ACCESS and ra._REGISTRY["case"] is ca.CASE_ACCESS
    assert hq.guard_case_access is ca.guard_case_access is helpers.guard_case_access
    assert hq.is_document_approver is ca.is_document_approver is helpers.is_document_approver


def test_excess_positive_and_reverse_controls():
    assert excess({OWNER: 7, "routers/search.py": 1}) == []
    assert excess({"routers/search.py": 2}) == ["routers/search.py：2 次（基線 1）"]
    assert excess({"helpers/new_thing.py": 1}) == ["helpers/new_thing.py：1 次（基線 0）"]


def test_only_case_access_may_newly_read_quotations_in_l1():
    files = _l1_files()
    assert OWNER in files, "modules.json 的 L1 沒有 helper:case_access"
    found = readers({f: (source_tree.BACKEND / f).read_text(encoding="utf-8") for f in files})
    assert found.get(OWNER), "正對照：case_access 本身讀 quotations，掃不到就是掃描壞了"
    bad = excess(found)
    assert not bad, "L1 新增讀 M01 的 quotations 表（只准經 helpers/case_access.py；DEPENDENCY-MAP §3.2）：\n  " + "\n  ".join(bad)


def test_without_m01_access_is_404_never_allowed():
    """反向控制（主持裁示條件 3）：案件表不存在 ⇒ 404「找不到」，不是放行也不是 500。"""
    from helpers.case_access import guard_case_access
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    admin = {"id": 1, "username": "boss", "role": "superadmin", "modules": []}
    for kw in ({}, {"allow_approver": True}, {"allow_module": "case_manage"}):
        with pytest.raises(HTTPException) as e:
            guard_case_access(conn, "MQ-202609-001", admin, **kw)
        assert e.value.status_code == 404, kw
        conn = sqlite3.connect(":memory:")          # 擋下時守門會關掉連線（呼叫端的直線寫法）
        conn.row_factory = sqlite3.Row
