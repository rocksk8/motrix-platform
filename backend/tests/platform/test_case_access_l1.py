"""案件存取守門下沉 L1 `helpers/case_access.py`（主持裁示 2026-09-26，DEPENDENCY-MAP §3.2；稽核 D AUDIT-D-C-case-access）。

① 同一份規則：modules.case.quotations 的同名匯入就是 L1 那一份，row_access 登錄的也是它
② 已知例外只有一個：L1（含 L0 core/）新增讀寫 M01 `quotations` 表的檔案 ⇒ 紅；既有的讀寫列在基線、只准變少。
   判準用 dep_scan 的 SQL 解析（與 dep_graph 同一份，CA-S1），另補逗號 join。f-string 插入的表名靜態無從得知（已知限制）。
③ 反向控制（CA-M1）：**表在、資料在、M01 沒載入** ⇒ `guard_case_access` 404、`case_access_allowed` False，連超級管理員也一樣。
   用真實 schema 的庫（`client` 夾具），不是空庫。
④ 只有 `no such table` 當成查無此案；資料庫被鎖等其他錯誤照樣丟出（CA-S2）
"""
import ast
import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

from core import registry, source_tree

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import dep_scan  # noqa: E402

TABLE = "quotations"
#: 逗號 join（`FROM cases c, quotations q`）dep_scan 目前不認得 ⇒ 補一條
_COMMA_JOIN = re.compile(r"\bFROM\s+[^;()]*?,\s*\"?%s\"?\b" % TABLE, re.I | re.S)

#: 2026-09-26 下沉當下，L1／L0 已經在讀（r）／寫（w）quotations 的檔案（DEPENDENCY-MAP §3.2：相依待各自切斷）。
#: 只准變少：拿掉某一檔的讀或寫時把這裡改小；新檔案不可以加進來——要讀案件資料，經 M01 的提供者或 case_access。
KNOWN_L1 = {
    "archive.py": "r", "db.py": "rw", "pdf_gen.py": "r",   # CA-O4（M01-PLAN §3-8 ①）：版本紀錄改經 case.doc_version ⇒ 只剩讀
    "helpers/audit.py": "r", "helpers/company_identity.py": "r", "helpers/google_calendar.py": "r",
    "routers/item_reads.py": "r", "routers/search.py": "r", "routers/system.py": "r",
    # 第六班列車交會（c-case-access × b-m08-3，2026-09-26）：以下兩檔不是新增的讀取，是既有讀取換了歸屬——
    # receivables.py＝M08 routers/reports.py 的應收收集逐字下沉 L1（主持裁示 a，ROADMAP A8b 中繼，M05 搬遷時收回）；
    # map_points.py＝地圖依 2026-09-21 使用者裁示歸 L1（b-m08-3 6838ade7 改 modules.json 歸屬）。
    # 主持裁示（RUN-PLAN §6，2026-09-26）：接受為有到期條件的例外；D 稽核確認是歸屬改變（AUDIT-D-C-case-access §6）。
    # 到期不靠人記：test_known_l1_baseline_is_not_stale（CA-S3）。兩筆都已到期、已刪：
    # 〔2026-09-26 M05 搬遷：receivables 收回 modules/arap，L1 只剩轉呼叫 provider 的殼、不再讀 quotations ⇒ 自本基線刪除〕
    # 〔2026-09-26 M01-PLAN §3-4：map_points 改走 M01 的 case.locations、不再讀 quotations ⇒ 自本基線刪除（到期題由紅轉綠）〕
}
OWNER = "helpers/case_access.py"


def _l1_files():
    """modules.json 的 L1 單位（router／helper／backend 頂層檔）＋ L0 `core/*.py`（CA-O1）。"""
    units = json.loads((REPO / "docs" / "platform" / "modules.json").read_text(encoding="utf-8"))["L1"]["units"]
    out = []
    for u in units:
        kind, _, name = u.partition(":")
        rel = {"router": "routers/%s.py", "helper": "helpers/%s.py", "core": "%s.py"}.get(kind)
        if rel and (source_tree.BACKEND / (rel % name)).is_file():
            out.append(rel % name)
    out += sorted("core/" + p.name for p in (source_tree.BACKEND / "core").glob("*.py"))
    return out


def access(src):
    """原始碼 ⇒ 對 quotations 的存取旗標（"r"、"w"、"rw" 或 ""）。"""
    chunks = dep_scan.string_chunks(ast.parse(src))
    r, w, _ddl, _dyn = dep_scan.sql_tables(chunks, {TABLE})
    read = TABLE in r or any(_COMMA_JOIN.search(c) for c in chunks)
    return ("r" if read else "") + ("w" if TABLE in w else "")


def excess(found, known=KNOWN_L1, owner=OWNER):
    return sorted("%s：%s（基線 %s）" % (f, flags, known.get(f, "無")) for f, flags in found.items()
                  if f != owner and not set(flags) <= set(known.get(f, "")))


def stale(found, files, known=KNOWN_L1):
    """基線上的條目已經過期 ⇒ 問題清單：不再是 L1 檔、不再讀寫 quotations、或權限縮小（基線要跟著縮）。
    讓「到期後自基線刪除」自己觸發（D 稽核 CA-S3：原本只寫在散文與別人的 scratchpad，到期後會安靜留著）。"""
    out = []
    for f, flags in known.items():
        if f not in files:
            out.append("%s：已不是 L1 檔（基線 %s）⇒ 自 KNOWN_L1 刪除" % (f, flags))
        elif not found.get(f):
            out.append("%s：已不讀寫 quotations（基線 %s）⇒ 自 KNOWN_L1 刪除" % (f, flags))
        elif set(found[f]) < set(flags):
            out.append("%s：只剩 %s（基線 %s）⇒ 縮小基線" % (f, found[f], flags))
    return sorted(out)


def test_stale_positive_and_reverse_controls():
    known = {"helpers/a.py": "r", "helpers/b.py": "rw", "helpers/c.py": "r"}
    files = ["helpers/a.py", "helpers/b.py"]
    assert stale({"helpers/a.py": "r", "helpers/b.py": "rw", "helpers/c.py": "r"}, files + ["helpers/c.py"], known) == []
    got = stale({"helpers/a.py": "", "helpers/b.py": "r"}, files, known)
    assert got == ["helpers/a.py：已不讀寫 quotations（基線 r）⇒ 自 KNOWN_L1 刪除",
                   "helpers/b.py：只剩 r（基線 rw）⇒ 縮小基線",
                   "helpers/c.py：已不是 L1 檔（基線 r）⇒ 自 KNOWN_L1 刪除"], got


def test_known_l1_baseline_is_not_stale():
    files = _l1_files()
    found = {f: a for f in files if (a := access((source_tree.BACKEND / f).read_text(encoding="utf-8")))}
    bad = stale(found, files)
    assert not bad, "KNOWN_L1 基線有過期條目（到期條件已觸發，請自基線刪除或縮小）：\n  " + "\n  ".join(bad)


def test_same_rule_everywhere():
    from helpers import case_access as ca, row_access as ra
    from modules.case import quotations as hq
    import helpers
    assert hq.CASE_ACCESS is ca.CASE_ACCESS and ra._REGISTRY["case"] is ca.CASE_ACCESS
    assert hq.guard_case_access is ca.guard_case_access is helpers.guard_case_access
    assert hq.is_document_approver is ca.is_document_approver is helpers.is_document_approver


@pytest.mark.parametrize("src,flags", [
    ('x("SELECT 1 FROM a JOIN quotations q ON 1")', "r"),
    ('x("SELECT 1 FROM a WHERE k IN (SELECT y FROM quotations)")', "r"),
    ('x("SELECT * FROM cases c, quotations q")', "r"),                 # 逗號 join（CA-S1）
    ("x('SELECT * FROM \"quotations\"')", "r"),                        # 加引號（CA-S1）
    ('x("SELECT * FROM " "quotations")', "r"),                         # 隱式串接（CA-S1）
    ('x("UPDATE quotations SET a=1")', "w"),                           # 寫入（CA-S1）
    ('x("INSERT INTO quotations (a) VALUES (1)")', "w"),
    ('x("SELECT * FROM quotations_archive")', ""),                     # 反向控制：別的表
    ('"""SELECT * FROM quotations 只是說明文字"""', ""),                 # 反向控制：docstring 不算
])
def test_access_parser(src, flags):
    assert access(src) == flags


def test_excess_positive_and_reverse_controls():
    assert excess({OWNER: "r", "routers/search.py": "r", "db.py": "rw"}) == []
    assert excess({"routers/search.py": "rw"}) == ["routers/search.py：rw（基線 r）"]
    assert excess({"helpers/new_thing.py": "r"}) == ["helpers/new_thing.py：r（基線 無）"]


def test_only_case_access_may_newly_read_or_write_quotations_in_l1():
    files = _l1_files()
    assert OWNER in files, "modules.json 的 L1 沒有 helper:case_access"
    found = {f: a for f in files if (a := access((source_tree.BACKEND / f).read_text(encoding="utf-8")))}
    assert found.get(OWNER) == "r", "正對照：case_access 本身讀 quotations，掃不到就是掃描壞了"
    bad = excess(found)
    assert not bad, "L1 新增讀寫 M01 的 quotations 表（只准經 helpers/case_access.py；DEPENDENCY-MAP §3.2）：\n  " + "\n  ".join(bad)


# ── ③ CA-M1：表在、M01 沒載入 ─────────────────────────────────────────────────

def _without_m01(monkeypatch):
    orig = registry.providers
    monkeypatch.setattr(registry, "providers", lambda cap: {} if cap == "case.access" else orig(cap))


def _seed_case(quote_no, owner_id):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, "
                     "sales_person_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (quote_no, "草稿", "客", "案", 0, 0, "{}", owner_id, "2026-09-26", "2026-09-26"))
        conn.commit()
    finally:
        conn.close()


def test_without_m01_access_is_404_even_though_the_table_and_row_exist(client, make_user, monkeypatch):
    """反向控制（主持裁示條件 3、稽核 D CA-M1）：真實 schema、案件列在、使用者是擁有者也是超級管理員 ⇒ M01 在時放行；
    M01 沒載入 ⇒ 404「找不到」，不放行。"""
    import db
    from helpers.case_access import case_access_allowed, case_module_present, guard_case_access
    name = make_user(username="ca_m1_boss", role="superadmin")[0]
    conn = db.get_db()
    uid = conn.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()["id"]
    conn.close()
    user = {"id": uid, "username": name, "role": "superadmin", "modules": []}
    _seed_case("MQ-CAM1-001", uid)
    assert case_module_present() is True                                  # 正對照：M01 在
    conn = db.get_db()
    q = guard_case_access(conn, "MQ-CAM1-001", user)
    assert q is not None and case_access_allowed(conn, q, user) is True
    conn.close()

    _without_m01(monkeypatch)
    assert case_module_present() is False
    conn = db.get_db()
    assert conn.execute("SELECT 1 FROM quotations WHERE quote_no='MQ-CAM1-001'").fetchone()   # 表與資料都還在
    assert case_access_allowed(conn, q, user) is False
    with pytest.raises(HTTPException) as e:
        guard_case_access(conn, "MQ-CAM1-001", user, allow_approver=True, allow_module="case_manage")
    assert e.value.status_code == 404


def test_missing_table_is_404_and_a_locked_database_is_not(monkeypatch):
    """CA-S2：只有 `no such table` 當成查無此案（404）；其他 OperationalError（例：database is locked）照樣丟出。"""
    from helpers import case_access as ca
    monkeypatch.setattr(ca, "case_module_present", lambda: True)
    admin = {"id": 1, "username": "boss", "role": "superadmin", "modules": []}
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with pytest.raises(HTTPException) as e:
        ca.guard_case_access(conn, "MQ-202609-001", admin)
    assert e.value.status_code == 404

    class _Locked:
        def execute(self, *a, **k):
            raise sqlite3.OperationalError("database is locked")

        def close(self):
            pass
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        ca.guard_case_access(_Locked(), "MQ-202609-001", admin)


def test_both_paths_agree_when_m01_is_absent(client, make_user, monkeypatch):
    """主持裁示：M01 不在時，L1 案件存取守門與經 IP-12 `case.access` 的取用方（網路規劃書）結果一致——都不放行。
    兩條路看同一個訊號（`case.access`），拿掉它 ⇒ L1 的 guard 404，規劃書依案件查詢也 404 並明說「案件模組未安裝」。"""
    from core import source_tree
    if not source_tree.module_installed("modules/netplan/"):   # 第六班列車 core-only 反向控制：取用方（網路規劃書）不在 ⇒ 無對象；
        pytest.skip("需要網路規劃模組（取用方）；L1 那一半由 test_without_m01_access_is_404_even_though_the_table_and_row_exist 負責")   # L1 guard 404 另有題
    import db
    from helpers.case_access import guard_case_access
    from modules.netplan import api as netplan
    name = make_user(username="ca_both_boss", role="superadmin")[0]
    conn = db.get_db()
    uid = conn.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()["id"]
    conn.close()
    user = {"id": uid, "username": name, "role": "superadmin", "modules": []}
    _seed_case("MQ-CABOTH-01", uid)
    au, apw = make_user(username="ca_both_api", role="superadmin")[:2]
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": au, "password": apw}).json()["token"]}
    url = "/api/quotations/MQ-CABOTH-01/network-plan"
    assert client.get(url, headers=h).status_code in (200, 404)          # 正對照：M01 在時是否有規劃書與本題無關，只要不是「未安裝」
    assert netplan.CASE_MISSING not in client.get(url, headers=h).text

    _without_m01(monkeypatch)
    conn = db.get_db()
    with pytest.raises(HTTPException) as e:
        guard_case_access(conn, "MQ-CABOTH-01", user)
    assert e.value.status_code == 404
    r = client.get(url, headers=h)
    assert r.status_code == 404 and netplan.CASE_MISSING in r.json()["detail"]
