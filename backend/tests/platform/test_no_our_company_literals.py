# -*- coding: utf-8 -*-
"""守門：產品碼不可以寫死本公司的資料（2026-09-27 H10；使用者：「要把原先的 logo、名稱、電話這些都換成客戶的」）。

掃描規則與例外登記在 `_our_company_literals.py`。
- 真實題：產品碼的掃描結果 × 登記表沒有任何問題；
- 正對照：已知一定存在的那一筆（凍結 migration `_m106` 的統編判準）要被掃到——掃描器壞掉時不會安靜變綠；
- 反向控制：合成樹上塞一筆（含大小寫變化、tests 目錄內外各一筆）要照規則紅／不紅；登記表被寫成「全部豁免」、
  登記頁面檔、登記不存在的類別、次數對不上、登記過期，都要紅。
"""
from tests.platform import _our_company_literals as L


def test_product_code_has_no_unregistered_company_literals():
    probs = L.problems(L.scan())
    assert not probs, "\n".join(probs)


def test_positive_control_the_known_frozen_migration_hit_is_found():
    hits = L.scan()
    assert hits.get(("backend/db.py", "統編"), 0) >= 1, (
        "掃描器沒有掃到凍結 migration _m106 的統編判準——掃描範圍或樣式壞了，其他「沒有」都不可信")
    # 範圍要含 modules/（§G5 #10）；拿掉所有模組的樹（core-only）沒有模組檔可掃 ⇒ 不驗這一句
    if any((L.REPO / "backend" / "modules").glob("*/module.json")):
        assert any(rel.startswith("backend/modules/") for rel, _ in _all_scanned_files()), "掃描範圍沒有包含 modules/"


def _all_scanned_files():
    """掃描範圍內的檔（給範圍正對照用）：用不可能出現的樣式掃一次，回傳檔名集合。"""
    out = set()
    for top in L.ROOTS:
        base = L.REPO / top
        for path in base.rglob("*.py"):
            rel = path.relative_to(L.REPO)
            if L._scannable(rel.parts[:-1], path.suffix) and not path.name.startswith("conftest"):
                out.add((rel.as_posix(), ""))
    return out


def _tree(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def test_reverse_control_synthetic_tree(tmp_path):
    root = _tree(tmp_path, {
        "backend/helpers/x.py": 'NAME = "允碩整合"\n',
        "frontend/static/p.html": "<div>Motrix SYNERGY Integration ERP</div>\n",
        "backend/modules/m/api.py": "TEL = '04-3610-6566'\n",
        "frontend/static/s.js": "img.src = up + 'static/logo.png'\n",
        "backend/tests/test_x.py": 'OURS = "60575481"\n',               # tests 不掃
        "backend/modules/m/tests/test_y.py": 'OURS = "允碩"\n',          # 模組的 tests 也不掃
        "backend/conftest.py": 'OURS = "允碩"\n',
        "docs/a.md": "允碩\n",                                              # 不在 ROOTS
        "backend/README.md": "允碩\n",                                      # .md 不掃
    })
    hits = L.scan(root)
    assert hits == {
        ("backend/helpers/x.py", "公司名（允碩）"): 1,
        ("frontend/static/p.html", "英文名（Synergy Integration）"): 1,
        ("backend/modules/m/api.py", "電話"): 1,
        ("frontend/static/s.js", "直接引用預設圖檔"): 1,
    }, hits
    probs = L.problems(hits, allowed={})
    assert len(probs) == 4 and all(p.startswith("寫死本公司資料") for p in probs), probs


def test_reverse_control_allowlist_cannot_become_a_blanket_exemption(tmp_path):
    root = _tree(tmp_path, {"backend/helpers/x.py": 'A = "允碩"\nB = "允碩"\n',
                            "frontend/static/p.html": "允碩\n"})
    hits = L.scan(root)
    ok_cat = next(iter(L.CATEGORIES))
    # 次數不符（登記 1、實際 2）
    assert any(p.startswith("次數不符") for p in L.problems(hits, {
        ("backend/helpers/x.py", "公司名（允碩）"): (1, ok_cat, "r"),
        ("frontend/static/p.html", "公司名（允碩）"): (1, ok_cat, "r")}))
    # 頁面不可以登記（即使次數對）
    assert any(p.startswith("頁面不可以登記") for p in L.problems(hits, {
        ("backend/helpers/x.py", "公司名（允碩）"): (2, ok_cat, "r"),
        ("frontend/static/p.html", "公司名（允碩）"): (1, ok_cat, "r")}))
    # 類別不在清單
    assert any(p.startswith("登記的類別不在清單裡") for p in L.problems(hits, {
        ("backend/helpers/x.py", "公司名（允碩）"): (2, "隨便寫的類別", "r")}))
    # 登記過期
    assert any(p.startswith("登記過期") for p in L.problems({}, {
        ("backend/helpers/x.py", "公司名（允碩）"): (2, ok_cat, "r")}))


def test_reverse_control_shipped_vbs_and_pyw_are_scanned_in_any_encoding(tmp_path):
    """稽核 D 建議（fc5c47f4）：.vbs／.pyw 也會出貨 ⇒ 要掃；.vbs 常存成 UTF-16 或 cp950，不可以因為讀不懂就略過。"""
    base = tmp_path / "backend"
    base.mkdir()
    (base / "a.vbs").write_text('MsgBox "允碩整合"\r\n', encoding="utf-8")
    (base / "b.vbs").write_text('MsgBox "允碩整合"\r\n', encoding="utf-16")         # 有 BOM
    (base / "c.vbs").write_bytes('MsgBox "允碩整合"\r\n'.encode("cp950"))
    (base / "d.pyw").write_text('TEL = "04-3610-6566"\n', encoding="utf-8")
    hits = L.scan(tmp_path)
    assert hits == {
        ("backend/a.vbs", "公司名（允碩）"): 1,
        ("backend/b.vbs", "公司名（允碩）"): 1,
        ("backend/c.vbs", "公司名（允碩）"): 1,
        ("backend/d.pyw", "電話"): 1,
    }, hits
    assert all(p.startswith("寫死本公司資料") for p in L.problems(hits, allowed={}))


def test_every_real_allowlist_entry_is_outside_frontend_and_has_a_known_category():
    for (rel, name), (count, category, reason) in L.ALLOWED.items():
        assert not rel.startswith("frontend/"), rel
        assert category in L.CATEGORIES, (rel, category)
        assert name in L.NEEDLES and count >= 1 and reason.strip(), (rel, name)
