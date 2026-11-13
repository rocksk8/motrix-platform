# -*- coding: utf-8 -*-
"""U0a 回應鍵集基準（凍結條件）：每條靜態 GET 路由的 JSON 鍵路徑與匯出表頭，與『U0 之前的樹』逐項相同；內部欄位名不得出現。

記錄基準（機器空檔、在 U0 之前的父提交上）：`U0A_RECORD=1 python -m pytest tests/platform/test_response_keys_baseline.py -q`
→ 寫入 `tests/platform/response_keys_baseline.json`。之後（含 U0 遷移加欄之後）本檔比對：差異必須為空。
正對照：①故意不剝除（把中介層的剝除函式換成恆等）＋表加欄 ⇒ 記錄器必須回報洩漏；②未剝除的 csv／xlsx 表頭 ⇒ 必須回報；③下限：記到的路由數與『有列』的清單數不得過少（防止空洞）。
"""
import io
import json
import os
from pathlib import Path

import pytest

from tests.platform import _response_keys as RK

BASELINE = Path(__file__).with_name("response_keys_baseline.json")
ROUTE_FLOOR = 340            # 靜態 GET 路由記到的數量下限
ROWFUL_FLOOR = 300            # 回傳『非空鍵集』的路由下限（種子有列才有鍵）
EXPORT_FLOOR = 4             # 狀態 200 的匯出（表頭可比）下限


@pytest.fixture
def seeded(client, make_user):
    import db
    u, p = make_user(username="rk_admin", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    c = db.get_db()
    try:
        RK.seed_every_table(c)
    finally:
        c.close()
    return {"Authorization": "Bearer " + tok}


def _paths():
    import main
    return RK.get_targets(main.app)


def _why_few_routes(targets) -> str:
    """路由太少時的診斷：app 的路由總數、/api GET 數、載入失敗的模組與原因（模組沒掛上 ⇒ 路由不見，不是記錄器壞了）。"""
    import main
    from core import registry
    try:
        failed = registry.failed()
    except Exception as e:                                                   # noqa: BLE001
        failed = "registry.failed() 丟例外：%r" % (e,)
    return "targets=%d app.routes=%d failed_modules=%s" % (len(targets), len(main.app.routes), str(failed)[:1500])


def test_record_or_compare_against_baseline(client, seeded, monkeypatch):
    # 日期釘住：/api/tender-radar/status 的 notices[] 會隨『今天』變（週末／國定假日 ⇒ no_mail_day、假日表到期前 60 天 ⇒ calendar_expiring），
    # 基準錄在平日；不釘的話週六日跑本題必紅（2026-11-07 週六就是這樣紅的，與沙箱無關）。釘到涵蓋範圍內的平日。
    import datetime as _dt
    from modules.tender_radar import source as _tsrc
    monkeypatch.setattr(_tsrc, "today", lambda: _dt.date(2026, 9, 30))
    assert _tsrc.no_mail_today()[0] is False, "釘住的日期必須是平日（否則 notices[] 會有 no_mail_day）"
    targets = _paths()
    assert len(targets) >= ROUTE_FLOOR, "GET /api 目標太少（模組可能沒載入）：" + _why_few_routes(targets)
    rec = RK.record(client, seeded, targets)
    if os.environ.get("U0A_RECORD") == "1":
        BASELINE.write_text(json.dumps(rec, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        st = {"routes": len(rec), "withkeys": sum(1 for e in rec.values() if e.get("k")),
              "exports200": sum(1 for e in rec.values() if e.get("hdr") and e["s"] == 200),
              "status0": sum(1 for e in rec.values() if e["s"] == 0), "leaks": len(RK.leaks(rec))}
        pytest.skip("基準已寫入 %s：%s" % (BASELINE.name, st))
    assert RK.leaks(rec) == [], "回應鍵集含內部欄位：%s" % RK.leaks(rec)[:10]
    assert len(rec) >= ROUTE_FLOOR, "只記到 %d 條路由（下限 %d）：記錄器可能失效" % (len(rec), ROUTE_FLOOR)
    assert sum(1 for e in rec.values() if e.get("k")) >= ROWFUL_FLOOR, "有鍵集的路由太少：種子可能沒有產生資料列"
    assert sum(1 for e in rec.values() if e.get("hdr") and e["s"] == 200) >= EXPORT_FLOOR, "可比對表頭的匯出太少"
    assert BASELINE.exists(), "缺 response_keys_baseline.json：先在 U0 之前的父提交以 U0A_RECORD=1 記錄"
    d = RK.diff(json.loads(BASELINE.read_text(encoding="utf-8")), rec)
    assert d["missing"] == [] and d["changed"] == {}, "回應鍵集與基準不同：%s" % json.dumps(d, ensure_ascii=False)[:2000]
    # added（現在才有的路由）只在同一提交新增路由時出現；那種提交必須重錄基準，所以這裡也要求空
    assert d["added"] == [], "新增了基準沒有的 GET 路由：%s（重錄基準）" % d["added"][:10]


# ── 正對照（記錄器本身不是假綠燈）────────────────────────────────────────────────────

def test_positive_control_unstripped_json_is_detected(client, seeded, monkeypatch):
    import db
    c = db.get_db()
    try:
        if "owner_unit_id" not in [r[1] for r in c.execute("PRAGMA table_info(parts)")]:      # U0 遷移之後的樹上已經有；之前的樹上（基準錄製）才需要補
            c.execute("ALTER TABLE parts ADD COLUMN owner_unit_id INTEGER NOT NULL DEFAULT 1")      # /api/parts＝SELECT * ＋ dict(r)：真的會帶出新欄位
        c.commit()
    finally:
        c.close()
    from core import internal_cols as IC      # 惰性匯入：基準要能在『還沒有 internal_cols』的父提交上記錄
    ok = RK.record(client, seeded, ["/api/parts"])
    assert RK.leaks(ok) == [] and ok["/api/parts"]["k"], "剝除開著 ⇒ 乾淨，且仍有鍵可比"
    monkeypatch.setattr(IC, "strip_internal_cols", lambda o: o)                           # 故意不剝除
    bad = RK.record(client, seeded, ["/api/parts"])
    assert RK.leaks(bad), "不剝除時記錄器必須回報洩漏（否則整個基準是假綠燈）"


def test_positive_control_unstripped_csv_and_xlsx_headers_are_detected():
    import openpyxl
    csv_body = "id,owner_unit_id,名稱\n1,1,甲\n".encode("utf-8")
    rec = {"/x.csv": {"s": 200, "ct": "text/csv", "hdr": RK.export_header("text/csv", csv_body)}}
    assert RK.leaks(rec) == [("/x.csv", "id,owner_unit_id,名稱")] or RK.leaks(rec) != []
    wb = openpyxl.Workbook()
    wb.active.append(["id", "unit_id", "名稱"])
    buf = io.BytesIO()
    wb.save(buf)
    ct = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    rec2 = {"/x.xlsx": {"s": 200, "ct": ct, "hdr": RK.export_header(ct, buf.getvalue())}}
    assert RK.leaks(rec2), "xlsx 表頭含 unit_id 必須被抓到"
    clean = {"/y.csv": {"s": 200, "ct": "text/csv", "hdr": RK.export_header("text/csv", "id,名稱\n".encode("utf-8"))}}
    assert RK.leaks(clean) == []


def test_diff_reports_added_removed_and_changed_keys():
    base = {"/a": {"s": 200, "k": ["x"]}, "/b": {"s": 200, "k": ["y"]}}
    now = {"/a": {"s": 200, "k": ["x", "owner_unit_id"]}, "/c": {"s": 200, "k": []}}
    d = RK.diff(base, now)
    assert d["missing"] == ["/b"] and d["added"] == ["/c"] and list(d["changed"]) == ["/a"]
    assert RK.diff(base, base) == {"missing": [], "added": [], "changed": {}}


def test_key_paths_records_keys_of_every_list_element_not_only_the_first_50():
    """T84：陣列只取前 50 筆時，設定中心群組一過 51 個，排在後面的群組（tender_closing 的 closing_soon_days）掉出取樣，
    基準「少了」鍵、而陣列後段新增／消失的鍵會被靜默漏看。守門：第 51 筆以後、含巢狀陣列裡的鍵也要被記到。
    正對照：同一份資料只取前 50 筆（舊行為）時，這些鍵確實記不到——證明這題有牙齒。"""
    rows = [{"id": i} for i in range(60)]
    rows[54]["late_key"] = 1                                          # 第 55 筆才有的鍵
    rows[59]["nested"] = [{"a": i} for i in range(55)]                # 最後一筆裡的巢狀陣列，其第 55 筆才有 deep_key
    rows[59]["nested"][54]["deep_key"] = 1
    got = RK.key_paths({"groups": rows})
    assert "groups[].late_key" in got, "第 55 筆的鍵沒被記到：陣列又被截斷了"
    assert "groups[].nested[].deep_key" in got, "巢狀陣列第 55 筆的鍵沒被記到"
    assert "groups[].id" in got and "groups[].nested[].a" in got
    old = RK.key_paths({"groups": rows[:50]})                         # 舊行為的樣子
    assert "groups[].late_key" not in old and "groups[].nested" not in old, "正對照失效：前 50 筆本來就不含這些鍵"
    assert RK.key_paths({"groups": []}) == ["groups"] and RK.key_paths([]) == [] and RK.key_paths({"a": [1, 2, 3]}) == ["a"]
    # 巢狀截斷單獨成立（h5 note 1）：外層只有一筆、巢狀陣列放在第 1 筆裡，外層截斷不可能遮住它
    inner = [{"a": i} for i in range(55)]
    inner[54]["deep_key"] = 1
    only_nested = {"groups": [{"nested": inner}]}
    assert "groups[].nested[].deep_key" in RK.key_paths(only_nested), "巢狀陣列第 55 筆的鍵沒被記到（只截斷巢狀的情況）"
    assert "groups[].nested[].deep_key" not in RK.key_paths({"groups": [{"nested": inner[:50]}]}), "正對照失效：前 50 筆本來就不含 deep_key"


def test_seed_every_table_creates_rows_so_lists_have_keys(client):
    import db
    c = db.get_db()
    try:
        n = RK.seed_every_table(c)
        assert n > 50
        assert c.execute("SELECT COUNT(*) FROM customers").fetchone()[0] >= 1
    finally:
        c.close()


def test_diff_tolerates_rate_limit_flip_only_on_listed_routes():
    """限流 429↔200 只在 RATE_LIMITED 清單內放行；正對照：200→403 翻轉、清單外的 429↔200、鍵集變動都必須報。"""
    r = "/api/reports/tax-export"
    rl, ok = {"s": 429, "k": ["detail"]}, {"s": 200}
    assert RK.diff({r: rl}, {r: ok})["changed"] == {} and RK.diff({r: ok}, {r: rl})["changed"] == {}
    assert RK.diff({r: ok}, {r: {"s": 403, "k": ["detail"]}})["changed"], "200→403 必須報"
    assert RK.diff({r: rl}, {r: {"s": 500, "k": ["detail"]}})["changed"], "429→500 必須報"
    other = "/api/not-rate-limited"
    assert RK.diff({other: rl}, {other: ok})["changed"], "清單外的 429↔200 必須報"


# ── 動態月份鍵正規化（T84，h11）────────────────────────────────────────────────────────
# /api/dashboard/bundle（expenses.otherBreakdown.<YYYY-MM>）與 /api/dashboard/expenses-monthly（otherBreakdown.<YYYY-MM>）用『最近 12 個月』當物件鍵，
# 視窗隨今天滾動；基準錄在 11 月，不正規化的話 12/1 起必紅（與程式無關）。

def _months(first_year, first_month, n=12):
    out, y, m = [], first_year, first_month
    for _ in range(n):
        out.append("%04d-%02d" % (y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def test_month_keys_rolling_window_is_not_a_diff():
    """滾動視窗：2025-12…2026-11 → 2026-01…2026-12，鍵集『相同』（12 個月）；key_paths 的原始輸出確實不同（正對照：沒正規化就會紅）。"""
    route = "/api/dashboard/bundle"
    mk = lambda months: {"expenses": {"otherBreakdown": {m: 0 for m in months}, "items": [{"total": 1}]}}   # noqa: E731
    old, new = mk(_months(2025, 12)), mk(_months(2026, 1))
    assert RK.key_paths(old) != RK.key_paths(new), "正對照失效：原始鍵路徑本來就該不同"
    b = {route: {"s": 200, "k": RK.norm_keys(RK.key_paths(old))}}
    n = {route: {"s": 200, "k": RK.norm_keys(RK.key_paths(new))}}
    assert RK.diff(b, n) == {"missing": [], "added": [], "changed": {}}
    # 舊格式基準（含 12 個具體月份、尚未正規化）對新記錄也不報：diff 兩側都走 norm_keys
    raw = {route: {"s": 200, "k": RK.key_paths(old)}}
    assert RK.diff(raw, n)["changed"] == {}
    assert RK.norm_keys(RK.key_paths(old)) == ["expenses", "expenses.items", "expenses.items[].total",
                                               "expenses.otherBreakdown", "expenses.otherBreakdown.<月>"]


def test_month_keys_real_key_changes_are_still_reported():
    """正規化不可吞掉真的變動：新增／消失的真鍵、月份底下的子鍵、狀態類別都照報。"""
    route = "/api/dashboard/expenses-monthly"
    base = {route: {"s": 200, "k": RK.norm_keys(RK.key_paths({"otherBreakdown": {"2026-10": 1}, "total": 1}))}}
    extra = {route: {"s": 200, "k": RK.norm_keys(RK.key_paths({"otherBreakdown": {"2026-11": 1}, "total": 1, "owner_unit_id": 1}))}}
    assert list(RK.diff(base, extra)["changed"]) == [route], "多了真鍵必須報"
    gone = {route: {"s": 200, "k": RK.norm_keys(RK.key_paths({"otherBreakdown": {"2026-11": 1}}))}}
    assert list(RK.diff(base, gone)["changed"]) == [route], "少了真鍵必須報"
    sub = {route: {"s": 200, "k": RK.norm_keys(RK.key_paths({"otherBreakdown": {"2026-11": {"x": 1}}, "total": 1}))}}
    assert list(RK.diff(base, sub)["changed"]) == [route], "月份底下新增子鍵必須報"
    assert list(RK.diff(base, {route: {"s": 500, "k": base[route]["k"]}})["changed"]) == [route], "200→500 必須報"
    assert RK.leaks({route: extra[route]}), "owner_unit_id 洩漏檢查不受正規化影響"


def test_norm_keys_only_collapses_whole_year_month_segments():
    """只換『整段』YYYY-MM；日期、前後黏字、不存在的月份、冪等、None。"""
    N = RK.norm_keys
    assert N(["a.2026-11"]) == ["a.<月>"] and N(["a.2025-12.b", "a.2026-01.b"]) == ["a.<月>.b"]
    assert N(["2026-11"]) == ["<月>"] and N(["a[].2026-11"]) == ["a[].<月>"]
    keep = ["a.2026-11-05", "a.2026-13", "a.2026-00", "a.x2026-11", "a.2026-11x", "a.12026-11", "a.1899-11", "a.2026-1"]
    assert N(keep) == sorted(keep), "日／13 月／黏字／非 19xx-20xx 不可被換掉"
    assert N(N(["a.2026-11", "a.2026-12"])) == ["a.<月>"], "冪等"
    assert N(None) is None and N([]) == []
    assert N(["b", "a.2026-11", "a.2026-12", "a"]) == ["a", "a.<月>", "b"], "去重＋排序"

def test_export_header_month_year_tokens_are_masked_but_structure_is_compared():
    """匯出表頭裡的『YYYY-MM』『YYYY 年 M 月』『YYYY年度』隨執行月／年變動：遮掉才不會 12/1、1/1 無故轉紅；欄位名／工作表名變了照報。"""
    M = RK._mask_dates
    a = ["當月收支|2026-11 當月收支明細", "本期收款明細|本期收款明細 — 2026 年 11 月", "今年度收支|2026年度收支總表", "未收款清單|未收款清單 — 截至 2026-11-13"]
    b = [h.replace("2026-11-13", "2026-12-01").replace("2026-11", "2026-12").replace("2026 年 11 月", "2027 年 1 月").replace("2026年度", "2027年度") for h in a]
    assert b != a and M(a) == M(b), "換月／換年不該有差異"
    assert M(M(a)) == M(a) and M(None) is None, "冪等＋None"
    assert M(["x|2026-13 y", "x|a2026-11b"]) == ["x|2026-13 y", "x|a2026-11b"], "13 月／黏字不遮"
    route = "/api/reports/export"
    base = {route: {"s": 200, "ct": "x", "hdr": M(a)}}
    same = {route: {"s": 200, "ct": "x", "hdr": M(b)}}
    assert RK.diff(base, same)["changed"] == {}
    renamed = {route: {"s": 200, "ct": "x", "hdr": M([h.replace("當月收支", "本月收支") for h in b])}}
    assert list(RK.diff(base, renamed)["changed"]) == [route], "工作表名／表頭文字變了必須報"
