"""已結案變更申請：簽核畫面要看到可讀的變更摘要，不是 raw JSON（2026-09-14 交辦）。

使用者附截圖：`case_record_update` 的「核准後會套用的內容」整包印出
`{"stages":[...],"payment":{"items":[{...,"writeOffRequestedAt":"...",
"invoiceFiles":[{"path":"..."}]}]}}`——**審核者無從判斷要不要核准**。

而且不只是難讀。`approve_case_change()` 對 `case_record_update` 的第一件事是
`new_case_record["stages"] = cr.get("stages")`，也就是 **payload 裡的 stages
根本不會被套用**。把它印在「核准後會套用的內容」底下是告訴審核者一件不會發生
的事——所以摘要刻意不收 stages，這裡有一題釘住。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
skip_module_unless("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')   # 本檔在模組層就 import M01（或 import 會略過的題檔）
import json

import pytest

import modules.case.api.quotations as rq
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _cr(**over):
    base = {
        "stages": [{"id": 41, "label": "訂單確認", "done": True}],
        "payment": {"items": [{
            "type": "訂金款", "amount": 1085280, "pct": 38.1,
            "received": True, "receivedAt": "2026-01-20",
            "invoiceNo": "ZP37778050", "invoiceDate": "2026-03-31",
            # 內部欄位：不該出現在摘要裡
            "writeOffStatus": "approved", "writeOffRequestedAt": "2026-08-05T09:01:35Z",
            "invoiceFiles": [{"id": "dd46ab68", "path": "quotation_payment_items/x/y.pdf"}],
        }]},
        "materials": [],
        "devices": [],
        "contract": {"deliveryAddress": "台北市", "contactPerson": "王小明"},
        "roles": {"filler": "黃玉龍", "sales": "高晟耀", "executor": "黃玉龍"},
        "projectTimeline": {"startDate": "", "endDate": "", "status": "on_track"},
    }
    base.update(over)
    return base


# ── 攤平：只收審核時真的要看的欄位 ──────────────────────────────────────────

def test_flatten_excludes_internal_fields():
    flat = rq._flatten_case_record(_cr())
    joined = json.dumps(flat, ensure_ascii=False)
    for internal in ("writeOffStatus", "writeOffRequestedAt", "invoiceFiles", "path"):
        assert internal not in joined, f"內部欄位 {internal} 不該出現在給人看的摘要裡"


def test_flatten_excludes_stages():
    """核准時 stages 會被現有值覆蓋（approve_case_change 第一行），
    印出來等於告訴審核者一件不會發生的事。"""
    flat = rq._flatten_case_record(_cr())
    joined = json.dumps(flat, ensure_ascii=False)
    assert "訂單確認" not in joined and "stages" not in joined


def test_flatten_keeps_what_matters():
    flat = rq._flatten_case_record(_cr())
    assert flat["角色·業務負責"] == "高晟耀"
    assert flat["合約·交貨地址"] == "台北市"
    assert flat["款項 #1·金額"] == 1085280
    assert flat["款項 #1·已收款"] == "是"
    assert flat["款項 #1·發票號碼"] == "ZP37778050"


# ── 摘要：只列有變動的欄位 ──────────────────────────────────────────────────

def test_case_record_update_lists_only_changed_fields():
    old = _cr()
    new = _cr(roles={"filler": "黃玉龍", "sales": "蔡紋惠", "executor": "黃玉龍"})
    out = rq._summarize_case_change("case_record_update", {"case_record": new}, old, [])

    assert list(out["after"].keys()) == ["角色·業務負責"], out["after"]
    assert out["before"]["角色·業務負責"] == "高晟耀"
    assert out["after"]["角色·業務負責"] == "蔡紋惠"


def test_case_record_update_with_no_diff_says_so_instead_of_dumping_json():
    same = _cr()
    out = rq._summarize_case_change("case_record_update", {"case_record": same}, same, [])
    joined = json.dumps(out, ensure_ascii=False)
    assert "無可辨識的欄位變動" in joined
    assert "writeOffRequestedAt" not in joined


def test_stage_only_change_does_not_look_like_it_will_be_applied():
    """只有 stages 不同時，摘要不能顯示成「有東西要被套用」——那些不會被套用。"""
    old = _cr()
    new = _cr(stages=[{"id": 41, "label": "訂單確認", "done": False}])
    out = rq._summarize_case_change("case_record_update", {"case_record": new}, old, [])
    assert "無可辨識的欄位變動" in json.dumps(out, ensure_ascii=False)


def test_payment_amount_change_is_visible():
    old = _cr()
    new = _cr(payment={"items": [dict(_cr()["payment"]["items"][0], amount=2000000)]})
    out = rq._summarize_case_change("case_record_update", {"case_record": new}, old, [])
    assert out["after"]["款項 #1·金額"] == 2000000
    assert out["before"]["款項 #1·金額"] == 1085280


# ── 其他變更類型 ────────────────────────────────────────────────────────────

def test_payment_mark_shows_before_and_after_for_touched_fields_only():
    cr = _cr(payment={"items": [{"type": "訂金款", "amount": 100, "received": False}]})
    out = rq._summarize_case_change(
        "payment_mark", {"idx": 0, "body": {"received": True, "receivedAt": "2026-09-14"}},
        cr, [])
    assert "款項 #1" in out["label"]
    assert out["before"]["已收款"] == "否" and out["after"]["已收款"] == "是"
    assert out["after"]["收款日期"] == "2026-09-14"
    assert "金額" not in out["after"], "沒有被這次申請動到的欄位不該列出來"


def test_upload_summarizes_files_not_paths():
    out = rq._summarize_case_change(
        "material_file_upload", {"idx": 2}, _cr(),
        [{"id": "a", "filename": "出貨照片.jpg", "path": "x/y/a.jpg"}])
    assert out["after"]["檔案數"] == 1
    assert "出貨照片.jpg" in out["after"]["檔案"]
    assert "叫料項目 #3" in out["after"]["動作"]
    assert "x/y/a.jpg" not in json.dumps(out, ensure_ascii=False), "不要把實體路徑給人看"


def test_delete_names_the_file_being_removed():
    cr = _cr(materials=[{"files": [{"id": "f1", "filename": "估價單.pdf"}]}])
    out = rq._summarize_case_change(
        "material_file_delete", {"idx": 0, "file_id": "f1"}, cr, [])
    assert out["after"]["檔案"] == "估價單.pdf"
    assert "刪除" in out["after"]["動作"]


def test_unknown_action_type_does_not_dump_raw_payload():
    """新增變更類型忘了補摘要時，退路是「講清楚看不懂」，不是倒 raw JSON。"""
    out = rq._summarize_case_change(
        "brand_new_action", {"secret": {"deep": "payload"}}, _cr(), [])
    joined = json.dumps(out, ensure_ascii=False)
    assert "brand_new_action" in joined
    assert "deep" not in joined and "payload" not in joined


# ── 端點層：實際打 API 拿到的就是摘要 ───────────────────────────────────────

def test_detail_endpoint_returns_summary_not_raw_payload(client, make_user):
    from db import get_db

    u, p = make_user(username="sa_chg", role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    headers = {"Authorization": f"Bearer {r.json()['token']}"}

    conn = get_db()
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
        "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?)",
        ("MQ-202608-777", "已送出", "京城凱悅", "影視對講機",
         json.dumps({"caseRecord": _cr()}, ensure_ascii=False),
         "2026-08-01", "2026-08-01", "已結案"))
    new_cr = _cr(roles={"filler": "黃玉龍", "sales": "蔡紋惠", "executor": "黃玉龍"})
    cur = conn.execute(
        "INSERT INTO case_change_requests (quote_no, action_type, summary, payload_json, "
        "staged_files_json, status, requested_by, requested_by_display, requested_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("MQ-202608-777", "case_record_update", "更新案件記錄",
         json.dumps({"case_record": new_cr}, ensure_ascii=False), "[]", "pending",
         u, "高晟耀", "2026-09-14T21:06:04"))
    cid = cur.lastrowid
    conn.commit()
    conn.close()

    res = client.get("/api/approval-queue/detail",
                     params={"type": "case_change", "id": str(cid)}, headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    changes = body.get("changes")
    assert changes, "沒有回變更摘要"
    assert changes["after"] == {"角色·業務負責": "蔡紋惠"}, changes["after"]

    raw = json.dumps(body, ensure_ascii=False)
    for internal in ("writeOffRequestedAt", "invoiceFiles", "quotation_payment_items"):
        assert internal not in raw, f"回應裡還有內部欄位 {internal}"


# ── 代碼值不得原樣外流（2026-09-14 使用者回報「專案期間·狀態 on_track」）──────

def test_enum_values_are_translated_not_raw():
    """摘要是給人看的，不該出現 `on_track` 這種內部代碼。"""
    flat = rq._flatten_case_record(_cr(projectTimeline={"startDate": "", "endDate": "",
                                                        "status": "on_track"}))
    assert flat["專案期間·狀態"] == "進行中"
    assert "on_track" not in json.dumps(flat, ensure_ascii=False)


def test_unknown_enum_value_is_shown_as_is_not_guessed():
    """沒見過的值原樣顯示——硬翻一個中文會讓人以為系統認得它。"""
    flat = rq._flatten_case_record(_cr(projectTimeline={"startDate": "", "endDate": "",
                                                        "status": "some_new_state"}))
    assert flat["專案期間·狀態"] == "some_new_state"


def test_status_change_summary_shows_both_sides_translated():
    old = _cr(projectTimeline={"startDate": "", "endDate": "", "status": "on_track"})
    new = _cr(projectTimeline={"startDate": "", "endDate": "", "status": "delayed"})
    out = rq._summarize_case_change("case_record_update", {"case_record": new}, old, [])
    assert out["before"]["專案期間·狀態"] == "進行中"
    assert out["after"]["專案期間·狀態"] == "已延遲"
