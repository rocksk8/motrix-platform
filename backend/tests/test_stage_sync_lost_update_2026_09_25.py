"""階段同步回 data_json 不可以蓋掉同時存進來的收款（lost update）。

☠️ 2026-09-25（e2e invoice 題在全量負載下紅兩次：畫面「已儲存」，DB 的收款回到填值之前）：
   案件頁一開啟就連打 5 次「建立階段」。`create_case_stage` 先 commit，之後才呼叫 `_sync_stages_to_json`；
   後者在**交易之外** `SELECT data_json`（sqlite3 不為 SELECT 開交易），處理完才整包 `save_quotation_json`。
   ⇒ 讀與寫之間若有收款的 PATCH commit，會被這份舊的整包蓋回去；負載越高空窗越大。
   ⚠️ 單跑幾乎碰不到（空窗只有幾毫秒）⇒ 這一題在空窗裡**確定地**插入一次 PATCH。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
skip_module_unless("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')   # 本檔在模組層就 import M01（或 import 會略過的題檔）
import json
import threading

import modules.case.api.quotations as q
from tests.test_case_money_mask_2026_09_24 import NO, _db_data, _login, _seed
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def test_a_payment_saved_while_stages_sync_is_not_overwritten(client, make_user, monkeypatch):
    u, pw = make_user(username="sync_race", role="superadmin")
    _seed(assigned=[])
    h = _login(client, u, pw)
    base_payment = _db_data()["caseRecord"]["payment"]
    new_payment = json.loads(json.dumps(base_payment))
    new_payment["items"][1]["invoicePretax"] = 6000
    new_payment["items"][1]["invoiceTax"] = 300

    result = {}
    fired = threading.Event()
    original = q.save_quotation_json

    def patch_in_the_gap():
        r = client.patch(f"/api/quotations/{NO}/case-record", headers=h,
                         json={"segments": {"payment": new_payment}, "base": {"payment": base_payment}, "defaults": {}})
        result["status"] = r.status_code

    def save_with_gap(conn, quote_no, data, **kw):
        # 只在第一次（階段同步那一次）插入：讀完 data_json、還沒寫回之前，另一條連線存了收款
        if not fired.is_set():
            fired.set()
            t = threading.Thread(target=patch_in_the_gap)
            t.start()
            t.join(2)          # 修正後 PATCH 會等到這裡的寫鎖釋放才進得去 ⇒ 不可以無限等
            result["thread"] = t
        return original(conn, quote_no, data, **kw)

    monkeypatch.setattr(q, "save_quotation_json", save_with_gap)
    r = client.post(f"/api/quotations/{NO}/stages", headers=h, json={"label": "訂單確認"})
    assert r.status_code == 201, r.text
    assert fired.is_set(), "探針沒有插進階段同步（被測路徑變了）"
    result["thread"].join(40)
    assert result.get("status") == 200, "收款存檔沒有成功：%s" % result.get("status")
    items = _db_data()["caseRecord"]["payment"]["items"]
    assert (items[1].get("invoicePretax"), items[1].get("invoiceTax")) == (6000, 300), \
        "階段同步用讀到的舊 data_json 整包寫回，蓋掉了同時存進來的收款"
    assert _db_data()["caseRecord"].get("stages"), "階段沒有同步回 data_json"
