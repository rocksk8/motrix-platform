# -*- coding: utf-8 -*-
"""測試寫法守門：測試讀全域稽核表（audit_log）時必須依自己建立的使用者或 request 篩選（T87 A2；T86 正式閘門教訓）。

T86 的 test_quote_put_fail_reason_codes 用 `SELECT * FROM audit_log WHERE result='fail'` 讀「整個資料庫的失敗列」再斷言 `len(rows) == 1`；
單獨跑會綠，整包跑時別的測試留下的失敗列讓它紅。規則與掃描器在 tools/platform/audit_scope_scan.py（author_gate --quick 也會跑這一題）。

比對範圍只在 WHERE 子句（h11 F2）：沒有 WHERE ＝命中；SELECT 欄位清單、ORDER BY 裡出現的 username／target 不算「篩選」；
水位線 `id > ?` 要有綁定值，`id > 0` 這種數字常數等於沒篩。

棘輪（tools/platform/ratchet.py 三道檢查，與 text-anchor 守門同一套）：既有檔的命中數記在 audit_scope_baseline.json，**只准減少**。
  1. 逐檔貼合：基線 > 現場＝要重寫基線，而且只准往下寫；
  2. 基線對照合併基準上的基線：任何一檔變多、總數變多＝紅（抓不到基準＝明確 skip 並寫原因，不當通過）；
  3. 不另存上限常數。
**沒有逃生口**（T87 決定，h11 F1）：命中就改寫測試。
已知限制：只認「SQL 敘述開頭、FROM audit_log」的字串；用別的資料表名或動態拼出表名的讀取看不到；同檔「換一個命中」總數不變時看不出來——靠審查。
"""
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))

import audit_scope_scan as S  # noqa: E402
import ratchet as R  # noqa: E402

BASELINE_REL = "backend/tests/platform/audit_scope_baseline.json"


def _all_test_files():
    out = []
    for dirpath, dirnames, filenames in os.walk(REPO / "backend"):
        dirnames[:] = [d for d in dirnames if d not in (".venv", ".venv312", "node_modules", "__pycache__", ".git", "data")]
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(Path(dirpath, fn).relative_to(REPO).as_posix())
    return S.test_files(out)


def _read(f):
    return (REPO / f).read_text(encoding="utf-8", errors="replace")


@pytest.mark.parametrize("src", [
    'def _rows():\n    return conn.execute("SELECT * FROM audit_log WHERE result=\'fail\' ORDER BY id").fetchall()\n',     # T86 的原型
    'def _n():\n    return conn.execute("select count(*) from audit_log").fetchone()[0]\n',
    'Q = ("SELECT action, result FROM audit_log "\n     "WHERE action = ?")\n',                                          # 只篩動作＝全域
    'def _r(a):\n    return conn.execute(f"SELECT * FROM audit_log WHERE action = \'{a}\'")\n',
    'Q = """\\\n  SELECT *\n    FROM audit_log\n   WHERE result = \'fail\'"""\n',                                         # 多行字串
    # h11 F2 的探針：範圍欄位只出現在 SELECT 清單／ORDER BY，或水位線是數字常數
    'Q = "SELECT username, result FROM audit_log WHERE result=\'fail\'"\n',
    'Q = "SELECT * FROM audit_log WHERE id > 0"\n',
    'Q = "SELECT * FROM audit_log WHERE result=1 ORDER BY target"\n',
    'Q = "SELECT * FROM audit_log WHERE result=1 GROUP BY username"\n',
    'Q = "SELECT target, action FROM audit_log"\n',                                                                     # 沒有 WHERE，欄位清單有範圍欄位
    'Q = "SELECT * FROM audit_log " + "WHERE result = \'fail\'"\n',                                                     # `+` 拼接
])
def test_scanner_flags_global_audit_reads(src):
    assert len(S.scan_source(src)) == 1, S.scan_source(src)


@pytest.mark.parametrize("src", [
    'Q = "SELECT * FROM audit_log WHERE username = ? ORDER BY id"\n',
    'Q = "SELECT * FROM audit_log WHERE request_id = ?"\n',
    'Q = "SELECT * FROM audit_log WHERE id > ? ORDER BY id"\n',                    # 查詢前的水位線：只看自己這次新增的列
    'Q = "SELECT * FROM audit_log WHERE target = ? AND action = ?"\n',
    'Q = "SELECT * FROM audit_log WHERE result=1 AND username IN (?, ?)"\n',
    'Q = "SELECT * FROM audit_log " + "WHERE username = ?"\n',
    'Q = "SELECT * FROM other_table"\n',
    'DOC = "這個欄位記錄 FROM audit_log 的說明文字"\n',                              # 不是 SQL 敘述開頭
])
def test_scanner_leaves_scoped_reads_alone(src):
    assert S.scan_source(src) == []


@pytest.mark.parametrize("reason", ["", "x", "這支測試用獨立資料庫，沒有別的測試寫入"])
def test_there_is_no_escape_hatch_any_more(reason):
    """h11 F1：舊的 `# audit-scope-ok: <理由>` 註解不再蓋住命中。"""
    assert len(S.scan_source('Q = "SELECT * FROM audit_log"  # audit-scope-ok: %s\n' % reason)) == 1


def test_scanner_module_has_no_hatch_api():
    assert not hasattr(S, "hatch_uses") and not hasattr(S, "hatches_in_tree")


def test_syntax_error_file_is_not_this_guards_business():
    assert S.scan_source("def broken(:\n") == []


def test_scan_scope_includes_conftest_and_non_test_helpers():
    got = S.test_files(["backend/tests/conftest.py", "backend/tests/_helper.py", "backend/modules/case/tests/test_x.py", "backend/helpers/x.py"])
    assert got == ["backend/modules/case/tests/test_x.py", "backend/tests/_helper.py", "backend/tests/conftest.py"]


# ── 棘輪：只准減少 ───────────────────────────────────────────────────────

def test_baseline_is_internally_consistent():
    b = S.load_baseline()
    assert b.get("files"), "audit_scope_baseline.json 讀不到或是空的"
    assert sum(b["files"].values()) == b["total"], "基線檔的 total 與各檔加總不符"
    assert "hatches" not in b, "基線不再記逃生口（沒有逃生口）"


def test_baseline_hugs_the_tree_exactly_no_stale_slack():
    cur = S.scan_tree(_all_test_files(), _read)
    stale = R.slack(cur, S.load_baseline()["files"])
    assert not stale, "基線有空位（請重寫基線，只准往下：python tools/platform/audit_scope_scan.py --write-baseline）：%s" % stale[:5]


def test_baseline_is_not_higher_than_the_merge_base_baseline():
    res = R.check_against_base(BASELINE_REL, S.load_baseline(), REPO, env_base=os.environ.get("MOTRIX_RATCHET_BASE"))
    if res["status"] == "no_base":
        pytest.skip("未跑：抓不到合併基準（%s）——這一題需要 git 與主線分支；整合者的閘門必須在有基準的環境跑" % res["note"])
    assert not res["violations"], "基線比合併基準高（基線只准減少；改寫測試，不要調基線）：%s %s" % (res["violations"][:8], res["note"])


def test_no_test_file_exceeds_its_baseline():
    files = _all_test_files()
    assert len(files) > 500, "掃到的測試檔太少（%d）——掃描範圍壞了，不可當成通過" % len(files)
    cur = S.scan_tree(files, _read)
    bad = S.over_baseline(cur, S.load_baseline()["files"])
    msg = ["  %s:%d %s（此檔 %d 處，基線 %d）" % (f, ln, snip, n, b) for f, n, b in bad[:10] for ln, snip in S.scan_source(_read(f))[:3]]
    assert not bad, ("測試讀全域稽核表卻沒有依自己的使用者／request 篩選（整包跑時別的測試的列會混進來）：\n" + "\n".join(msg) +
                     "\n沒有逃生口——改寫測試：WHERE 加上自己建立的 username／request_id／target，或先記下 max(id) 再用 `id > ?` 只看新增的列。")


def test_baseline_files_still_exist():
    missing = [f for f in S.load_baseline()["files"] if not (REPO / f).is_file()]
    assert not missing, "基線裡有不存在的檔，請 `python tools/platform/audit_scope_scan.py --write-baseline`（只准總數減少）：%s" % missing[:5]
