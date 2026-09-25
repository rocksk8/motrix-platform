"""連簽蓋章（cascade_self_tiers）補記「誰簽的」——只加欄位，六種單據的判斷一格都不變。

2026-09-25（使用者關心「紀錄要看得出誰簽的」，經 hichan-0a）：原本連簽蓋掉的格子只有
status／approvedAt／cascadedFrom，分不出是誰蓋的、是不是代理。現在另寫 approvedBy／approvedByDisplay，
代理時記 onBehalfOf（被代理的人）。

回歸：把改之前的實作凍結在這裡當對照組，逐一比對各種層配置——拿掉新欄位之後，
回傳值與每一格的 status／approvedAt／cascadedFrom 必須完全相同。
六個呼叫端（報價單、請款、承攬商匯款、開票、完工、出貨）都只看回傳值與 status ⇒ 判斷不變。
"""
import copy
import itertools
import re
from pathlib import Path

from helpers import tiered_approval as ta

NEW_KEYS = ("approvedBy", "approvedByDisplay", "onBehalfOf")
CALLERS = ["completion_notes.py", "contractor_vouchers.py", "invoice_vouchers.py",
           "payment_requests.py", "quotations.py", "shipping_notes.py"]


def _old_cascade_self_tiers(tiers, ct_idx, username, now, conn=None):
    """2026-09-25 之前的寫法（凍結；不要改）。"""
    plan = ta.plan_self_cascade(tiers, ct_idx, username, conn=conn)
    for ti in plan:
        for a in (tiers[ti].get("approvers") or []):
            if a.get("status") != "approved":
                a["status"] = "approved"
                a["approvedAt"] = now
                a["cascadedFrom"] = ct_idx
    return plan


def _strip(tiers):
    return [[{k: v for k, v in a.items() if k not in NEW_KEYS} for a in (t.get("approvers") or [])]
            for t in tiers]


def _configs():
    people = ["me", "other"]
    shapes = []
    for n in (2, 3):
        for combo in itertools.product([("me",), ("other",), ("me", "other"), ("other", "me")], repeat=n):
            shapes.append(combo)
    for shape in shapes:
        for pre_signed in (False, True):
            tiers = []
            for i, members in enumerate(shape):
                apps = [{"username": u, "display_name": u} for u in members]
                if pre_signed and i == 1 and len(apps) > 1:
                    apps[0].update(status="approved", approvedAt="2026-01-01T00:00:00")
                tiers.append({"approvers": apps})
            yield tiers
    assert people


def test_same_decisions_as_before_on_every_configuration():
    n = 0
    for tiers in _configs():
        for ct in range(len(tiers)):
            a, b = copy.deepcopy(tiers), copy.deepcopy(tiers)
            old = _old_cascade_self_tiers(a, ct, "me", "T")
            new = ta.cascade_self_tiers(b, ct, "me", "T")
            assert new == old, (tiers, ct)
            assert _strip(b) == _strip(a), (tiers, ct)
            n += 1
    assert n > 100


def test_cascaded_cells_record_the_signer():
    tiers = [{"approvers": [{"username": "me"}]}, {"approvers": [{"username": "me"}]}]
    assert ta.cascade_self_tiers(tiers, 0, "me", "T") == [1]
    cell = tiers[1]["approvers"][0]
    assert cell["status"] == "approved" and cell["approvedBy"] == "me" and cell["approvedByDisplay"] == "me"
    assert "onBehalfOf" not in cell
    assert "approvedBy" not in tiers[0]["approvers"][0], "只動被連簽掉的層；當層由呼叫端自己蓋"


def test_a_delegated_cascade_records_on_behalf_of(client, make_user):
    """代理：他代理 boss 的層也可以一起蓋掉 ⇒ 那一格記 approvedBy=他、onBehalfOf=boss、顯示名稱查得到。"""
    from tests.test_bonus_case_api_2026_09_24 import _delegate
    make_user(username="cs_me", role="admin")
    make_user(username="cs_boss", role="admin")
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET display_name='代簽的人' WHERE username='cs_me'")
        conn.commit()
        _delegate("cs_boss", "cs_me")
        tiers = [{"approvers": [{"username": "cs_me"}]}, {"approvers": [{"username": "cs_boss"}]}]
        assert ta.cascade_self_tiers(tiers, 0, "cs_me", "T", conn=conn) == [1]
    finally:
        conn.close()
    cell = tiers[1]["approvers"][0]
    assert cell["approvedBy"] == "cs_me" and cell["onBehalfOf"] == "cs_boss" and cell["approvedByDisplay"] == "代簽的人"


def test_all_six_document_types_go_through_the_shared_helper():
    """六種單據的連簽都走同一個 helper（有人改回自己蓋章時這一題會抓到）。"""
    from core import source_tree
    root = Path(__file__).resolve().parents[1] / "routers"
    files = {p.name: p for p in source_tree.router_files()}      # 端點檔可能已搬進模組（外包工班：modules/subcontract/api/）
    for f in CALLERS:
        src = files[f].read_text(encoding="utf-8")
        assert re.search(r"cascade_self_tiers\(", src), f
    xe = (root / "case_extra_expenses.py").read_text(encoding="utf-8")
    assert xe.count("cascade_self_tiers(") == 2 and "tier_completes_on_first" not in xe


def test_frontend_prediction_matches_the_backend_on_every_configuration():
    """畫面上的「一次簽完」確認視窗（approval-cascade.js）與後端 plan_self_cascade 同一個答案。
    ☠️ 2026-09-25 之前額外支出／獎金分潤在前端走 completesOnFirst，會預告一次簽掉「同層還有別人」的層。"""
    import json as _json
    import shutil
    import subprocess
    import pytest
    node = shutil.which("node")
    if not node:
        pytest.skip("這台機器沒有 node —— ⚠️ skip 不是驗過")
    js = (Path(__file__).resolve().parents[2] / "frontend" / "static" / "approval-cascade.js").read_text(encoding="utf-8")
    cases = []
    for tiers in _configs():
        for ct in range(len(tiers)):
            # 前端判斷「目前這一層我簽下去會不會結束」；後端 cascade 只在當層完成後才呼叫——對齊兩者的前提
            cur_pending = [a for a in tiers[ct]["approvers"] if a.get("status") != "approved"]
            cur_done = bool(cur_pending) and all(a["username"] == "me" for a in cur_pending)
            back = [i + 1 for i in ta.plan_self_cascade(copy.deepcopy(tiers), ct, "me")] if cur_done else []
            cases.append({"tiers": tiers, "ct": ct, "want": back})
    script = ("var window = {};\n" + js + "\n"
              "var cases = " + _json.dumps(cases) + ";\n"
              "var bad = cases.filter(function (c) { return JSON.stringify(window.MotrixApproval.selfCascadeTiers("
              "c.tiers, c.ct, 'me', [])) !== JSON.stringify(c.want); });\n"
              "console.log(JSON.stringify({n: cases.length, bad: bad.slice(0, 3)}));")
    # 腳本走 stdin：案例清單很長，用 -e 會撞到 Windows 命令列長度上限（WinError 206）
    out = subprocess.run([node], input=script, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr[-600:]
    res = _json.loads(out.stdout.strip().splitlines()[-1])
    assert res["n"] > 100 and not res["bad"], res


def test_no_page_asks_for_the_removed_any_one_semantics():
    """前端不可以再傳 completesOnFirst（上一題驗的是函式本身；這一題驗呼叫端沒有把它打開）。"""
    fe = Path(__file__).resolve().parents[2] / "frontend"
    hits = [str(f.relative_to(fe)) for f in list(fe.rglob("*.html")) + list(fe.rglob("*.js"))
            if re.search(r"completesOnFirst\s*:", f.read_text(encoding="utf-8", errors="ignore"))]
    assert not hits, hits
