# -*- coding: utf-8 -*-
"""G5：總帳費用單據入帳的突變守門（固定題）。

做法：把 backend 複製到系統暫存，對複本裡的一個檔做**一處**字面取代（突變），在複本裡跑偵測題；
偵測題必須**失敗**（returncode==1）才算守住。還原（＝不突變的複本）必須全綠（正向控制）；錨點字串在原檔必須恰好出現一次
（原碼改寫了而錨點沒跟著改 ⇒ 這裡紅，不會靜默變成「沒突變」）。
編譯錯／收集錯（returncode 2）不算偵測到（突變假陽性）。突變只發生在複本，不碰工作樹。
偵測題：G1 對應檔＋引擎行科目檔；G2 驗收檔（需案件 0003 欄位，沒有就 skip）不列入——它在列車整合樹上另行必須 passed。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
DETECTORS = [
    "modules/accounting/tests/test_category_map_g1_2026_10_01.py",
    "modules/accounting/tests/test_engine_line_account_code_2026_10_01.py",
]

# (代號, 檔, 錨點, 突變後, 說明)
MUTATIONS = [
    ("M1-no-category-map-call", "modules/accounting/ledger/contract.py",
     "e = _apply_category_map(conn, e)", "e = e",
     "引擎收集不套類別對應 ⇒ 類別行沒有科目、拆稅不發生"),
    ("M2-caseless-defaults-to-project-cost", "modules/accounting/ledger/category_map.py",
     'ln["role"] = _ROLE_COST if (ln.get("case_no") or ev.get("case_no")) else _ROLE_OTHER', 'ln["role"] = _ROLE_COST',
     "無案件沒對應也記專案成本"),
    ("M3-engine-ignores-line-account-code", "modules/accounting/ledger/engine.py",
     'code = (line.get("account_code") or "").strip()', 'code = ""',
     "引擎忽略事件行指定的科目（付款科目 1111 失效）"),
    ("M4-tax-split-ignores-doc-type", "modules/accounting/ledger/category_map.py",
     'deductible = bool(tax) and doc_type == "invoice" and', 'deductible = bool(tax) and',
     "收據／國外憑證也拆進項稅"),
    ("M5-tax-split-ignores-nondeductible", "modules/accounting/ledger/category_map.py",
     'and not (m and m["nondeductible"])', "",
     "類別設為不可扣抵仍拆進項稅"),
    ("M6-provider-lists-inactive-categories", "modules/accounting/api/ledger_category_map.py",
     "_cm.list_categories(conn, only_active=True)", "_cm.list_categories(conn, only_active=False)",
     "停用的類別出現在 expense.categories 提供者"),
]


def _copy_backend(dst: Path) -> Path:
    shutil.copytree(BACKEND, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "data", "db_backups", ".pytest_cache"))
    return dst


def _run(root: Path):
    env = {k: v for k, v in os.environ.items() if k not in ("MOTRIX_TRAIN", "PYTEST_CURRENT_TEST", "PYTEST_XDIST_WORKER")}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    tmp = root.parent / "bt"
    return subprocess.run([sys.executable, "-m", "pytest", *DETECTORS, "-q", "-x", "-p", "no:cacheprovider", "-W", "ignore",
                           "--basetemp", str(tmp)], cwd=str(root), env=env, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=600)


@pytest.fixture(scope="module")
def pristine(tmp_path_factory):
    """正向控制：不突變的複本，偵測題全綠（否則「突變後紅」證明不了任何事）。"""
    root = _copy_backend(tmp_path_factory.mktemp("mut_ok") / "backend")
    r = _run(root)
    assert r.returncode == 0, "正向控制失敗：未突變的複本偵測題不是全綠\n" + (r.stdout + r.stderr)[-1500:]
    return r


def _mutate_and_run(tmp_path, rel, old, new):
    src = (BACKEND / rel).resolve()
    text = src.read_text(encoding="utf-8")
    assert text.count(old) == 1, "錨點在 %s 出現 %d 次（要恰好 1 次）⇒ 原碼改寫了，請更新突變清單：%r" % (rel, text.count(old), old)
    root = _copy_backend(tmp_path / "backend")
    (root / src.relative_to(BACKEND)).write_text(text.replace(old, new), encoding="utf-8", newline="")
    return _run(root)


@pytest.mark.parametrize("mid,rel,old,new,why", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_mutation_is_caught_by_detectors(pristine, tmp_path, mid, rel, old, new, why):
    r = _mutate_and_run(tmp_path, rel, old, new)
    out = (r.stdout + r.stderr)[-1500:]
    assert r.returncode == 1, "%s（%s）：突變後 returncode=%s（0＝沒有題目守住；2＝收集／編譯錯，不算偵測到）
%s" % (mid, why, r.returncode, out)
    assert "failed" in r.stdout, "%s：returncode=1 但沒有 failed 摘要（不是題目紅）
%s" % (mid, out)


def test_rc_harmless_mutation_stays_green(pristine, tmp_path):
    """反向控制：只改註解文字的『突變』偵測題必須仍綠——證明上面的紅是突變造成的，不是複本環境本身會紅。"""
    r = _mutate_and_run(tmp_path, "modules/accounting/api/ledger_category_map.py",
                        "IP `expense.categories`：啟用中的費用類別", "IP `expense.categories`：啟用中的費用類別（註解改字）")
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
