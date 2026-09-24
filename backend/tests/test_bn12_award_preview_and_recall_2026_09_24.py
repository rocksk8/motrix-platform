"""`BN12` · 申請與匯出兩階段都有詳細預覽（`docs/windows/SPEC-BN11-BN12.md` §1①／§4／§5）。

後端要驗的：
① 預覽端點 `GET /awards/{id}/preview` 與匯出端點**分開**：預覽**不看簽核狀態**，匯出才擋
② 預覽與 PDF 來自同一支 `build_award_html()`（同一套精算表列）
③ 浮水印順序照搬 `JV11`：**作廢優先於未簽核**
   ⚙️ 用一張**還沒簽核就作廢**的單（§5 ⓔ），否則兩條規則的順序驗不出來
④ recall（§1①）：只有**原送審申請人**能把待審核／簽核中收回草稿，清簽核，留編寫紀錄
   ⚙️ 對照組：另一位 superadmin（有權限、不是申請人）要被拒 —— 否則「只有申請人」量不到
"""

# ── 2026-09-24 移除（SPEC-BONUS §十一）───────────────────────────────────────
# 舊「獎金項目＋分潤單」流程停用：寫入端點回 410、bonus.html 改為以案件為中心的新頁面
# （使用者：「上一次開發的內容我無法接受」「重做成新流程」、舊單「舊的都是開發機測試用，直接作廢」）。
# 本檔下列題驗的是已停用的流程，已移除；新流程的題見 test_bonus_case_*_2026_09_24.py、
# test_e2e_bonus_case_page_2026_09_24.py、test_bonus_legacy_retired_2026_09_24.py。
# 移除：test_bn12_a_draft_cannot_be_recalled、test_bn12_another_superadmin_cannot_recall_someone_elses_award、test_bn12_the_requester_can_recall_a_pending_award
# 同檔其餘題驗的是仍在運作的部分（讀取端點、群組、輔助函式），保留。
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bonus_award_approval_2026_09_23 import AWARDS, _hdr, _seed_award  # noqa: E402

UNSIGNED = "尚未簽核完成"
VOIDED = "已作廢"


def _wm_titles(html):
    """浮水印格子裡的標題（`<div class='wm-item'><b>…</b>`）。
    ⚠️ 不可以對整份 HTML 做子字串比對：版面的 CSS 註解本來就寫著「已作廢的浮水印」，
       第一版那樣比 ⇒ 每一張單都「有已作廢」（作廢那題假綠、已核准那題假紅）。"""
    import re
    return set(re.findall(r"<div class='wm-item'><b>([^<]*)</b>", html))


def _seed_case(quote_no):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax,"
            " deal_tag, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "BN12 客戶", "BN12 案", 0, 0, "已結案",
             json.dumps({"settlement": {"status": "finalized", "summary": {"netProfit": 50000}}}),
             "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _preview(client, hdr, aid):
    r = client.get("%s/%s/preview" % (AWARDS, aid), headers=hdr)
    assert r.status_code == 200, "預覽被擋或不存在：%s %s" % (r.status_code, r.text[:200])
    return r.text


def test_bn12_a_pending_award_previews_with_the_unsigned_watermark_but_cannot_export(client, make_user):
    _seed_case("MQ-BN12-P")
    _u, sup = _hdr(client, make_user, "bn12_p")
    aid = _seed_award("MQ-BN12-P", ["bn12_p"], status="待審核")
    html = _preview(client, sup, aid)
    assert any(UNSIGNED in t for t in _wm_titles(html)), "待審核的預覽沒有「尚未簽核完成」浮水印"
    assert "真實淨利" in html, "預覽裡沒有精算明細表（與 PDF 不是同一份版面？）"
    r = client.get("%s/%s/pdf-download" % (AWARDS, aid), headers=sup)
    assert r.status_code == 400, "待審核的單竟然匯得出 PDF（%s）—— 匯出閘門不見了" % r.status_code


def test_bn12_voided_wins_over_unsigned(client, make_user):
    """§5 ⓔ：還沒簽核就作廢 ⇒ 印「已作廢」不是「尚未簽核」（否則有人會去把它簽完）。"""
    _seed_case("MQ-BN12-V")
    _u, sup = _hdr(client, make_user, "bn12_v")
    aid = _seed_award("MQ-BN12-V", ["bn12_v"], status="待審核")
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE bonus_awards SET voided_at='2026-09-24T00:00:00' WHERE id=?", (aid,))
        conn.commit()
    finally:
        conn.close()
    titles = _wm_titles(_preview(client, sup, aid))
    assert any(VOIDED in t for t in titles) and not any(UNSIGNED in t for t in titles), (
        "作廢優先序錯了：浮水印標題是 %r" % titles)


def test_bn12_an_approved_award_previews_without_a_watermark(client, make_user):
    _seed_case("MQ-BN12-A")
    _u, sup = _hdr(client, make_user, "bn12_a")
    aid = _seed_award("MQ-BN12-A", ["bn12_a"], status="已核准")
    titles = _wm_titles(_preview(client, sup, aid))
    assert not titles, "已核准的單不該蓋浮水印：%r" % titles


def _pending_by(client, make_user, quote_no, requester):
    _seed_case(quote_no)
    aid = _seed_award(quote_no, [requester], status="待審核",
                      approval_json=json.dumps({"tiers": [], "currentTier": 0,
                                                "requestedBy": requester}))
    return aid


