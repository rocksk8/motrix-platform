"""`JV22` · 傳票退回要留長期記憶（`docs/windows/SPEC-JV22.md` §7 驗收的後端那一半）。

使用者原話：「傳票如果有退回，需顯示上次退回跟這次編修的內容，長期記憶，這個不能刪除」。

```
① send_back 寫一筆**結構化** edit_log（狀態／退回原因／單號 舊->新），retention="permanent"
   ——在此之前只有 audit_log 那一句組好的字串，而 audit_log 兩年後會被清掉（§2b）
② GET /api/vouchers/{id}/edit-log 讀得回來（閘門與其餘傳票端點一致；不回 422）
③ 附件**新增**也要留紀錄（§4 缺口一：刪得掉的留得住，加上去的留不住）
④ 作廢之後紀錄仍然讀得到（§3 ③）
```
⚙️ 觀測點：②③④ 走 API 讀回；① 另外直接讀表確認 retention（API 不必回這個欄位）。
（資料庫層「刪不掉」由 `test_edit_log_no_delete_trigger_2026_09_24.py` 驗。）
"""
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_journal_voucher_flow_2026_09_23 import _act, _create, _get, _hdr  # noqa: E402

LOG = "/api/vouchers/%s/edit-log"


def _log(client, hdr, vid):
    r = client.get(LOG % vid, headers=hdr)
    assert r.status_code != 422, "edit-log 回 422 —— 路由被別的路徑吃掉了（§7 ⓔ）"
    assert r.status_code == 200, "讀不到編寫紀錄：%s %s" % (r.status_code, r.text[:200])
    return r.json()["entries"]


def _send_back(client, hdr, vid, reason):
    assert _act(client, hdr, vid, "submit").status_code == 200
    r = _act(client, hdr, vid, "send-back", {"reason": reason})
    assert r.status_code == 200, r.text[:200]
    return r.json()["voucher_no"]


def test_jv22_send_back_leaves_a_structured_permanent_record(client, make_user):
    _u, hdr = _hdr(client, make_user, "jv22_a")
    vid, j = _create(client, hdr)
    old_no = _get(client, hdr, vid)["voucher_no"]
    new_no = _send_back(client, hdr, vid, "科目代號選錯")

    entries = _log(client, hdr, vid)
    sb = [e for e in entries if any(c["field"] == "status" and c["to"] == "草稿"
                                    for c in e["changes"])]
    assert len(sb) == 1, "退回之後編寫紀錄裡沒有一筆「狀態 -> 草稿」：%r" % entries
    ch = {c["field"]: c for c in sb[0]["changes"]}
    assert ch["退回原因"]["to"] == "科目代號選錯", ch
    assert (ch["voucher_no"]["from"], ch["voucher_no"]["to"]) == (old_no, new_no), ch

    import db
    conn = db.get_db()
    try:
        ret = [r[0] for r in conn.execute(
            "SELECT retention FROM voucher_edit_log WHERE voucher_id = ? AND changes_json LIKE ?",
            (vid, '%退回原因%'))]
    finally:
        conn.close()
    assert ret == ["permanent"], (
        "退回那一列的 retention 是 %r —— 「長期記憶」要明著標 permanent，不要靠預設值 term。" % ret)


def test_jv22_edits_after_the_send_back_are_listed_after_it(client, make_user):
    _u, hdr = _hdr(client, make_user, "jv22_b")
    vid, _ = _create(client, hdr, summary="文具")
    _send_back(client, hdr, vid, "摘要寫錯")
    r = client.put("/api/vouchers/%s" % vid, json={"summary": "辦公用品"}, headers=hdr)
    assert r.status_code == 200, r.text[:200]

    entries = _log(client, hdr, vid)
    idx_sb = max(i for i, e in enumerate(entries)
                 if any(c["field"] == "退回原因" for c in e["changes"]))
    later = [c for e in entries[idx_sb + 1:] for c in e["changes"]]
    assert {"field": "summary", "from": "文具", "to": "辦公用品"} in later, (
        "退回之後的編修沒有排在那一筆後面：%r" % entries)


def test_jv22_adding_an_attachment_is_recorded_with_its_filename(client, make_user):
    _u, hdr = _hdr(client, make_user, "jv22_c")
    vid, _ = _create(client, hdr)
    r = client.post("/api/vouchers/%s/attachments" % vid, headers=hdr,
                    files={"files": ("發票0924.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")})
    assert r.status_code == 200, r.text[:200]
    added = [c for e in _log(client, hdr, vid) for c in e["changes"]
             if c["field"] == "attachment" and c["from"] in ("", None)]
    assert [c["to"] for c in added] == ["發票0924.pdf"], (
        "新增附件沒有留下檔名紀錄：%r —— 刪得掉的留得住，加上去的留不住（§4）。" % added)


def test_jv22_the_history_survives_voiding(client, make_user):
    _u, hdr = _hdr(client, make_user, "jv22_d")
    vid, _ = _create(client, hdr)
    _send_back(client, hdr, vid, "作廢前的退回")
    r = _act(client, hdr, vid, "void", {"reason": "重開"})
    assert r.status_code == 200, r.text[:200]
    reasons = [c["to"] for e in _log(client, hdr, vid) for c in e["changes"]
               if c["field"] == "退回原因"]
    assert reasons == ["作廢前的退回"], "作廢之後退回紀錄看不到了：%r" % reasons


def test_jv22_the_log_is_behind_the_same_gate_as_the_voucher(client, make_user):
    _u, hdr = _hdr(client, make_user, "jv22_e")
    vid, _ = _create(client, hdr)
    _u2, outsider = _hdr(client, make_user, "jv22_out", role="user", modules=("reports",))
    r = client.get(LOG % vid, headers=outsider)
    assert r.status_code == 403, "沒有出納模組的人讀得到傳票編寫紀錄：%s" % r.status_code
