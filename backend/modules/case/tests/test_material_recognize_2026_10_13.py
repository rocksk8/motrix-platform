# -*- coding: utf-8 -*-
"""T57 材料卡片『認列已核准採購單』（MATERIAL-LINK-BUG-T57）：卡片持有伺服器驗證的 poLink；不建材料申請、不繞過核准、不產生付款路徑。
權限（非最高管理者整件取消＋稽核＋寄信去重）、到貨日與確認人由伺服器記、過期、雙向占用、取消認列、系統路徑不接受新連結。"""
import json

import db
from modules.case import material_guard as MG
from modules.case import material_notify as MN
from modules.case import material_recognize as MR
from modules.case.tests.test_material_link_booking_2026_10_02 import _won_case  # noqa: F401
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _ln, _login, _mk, _status, _submit  # noqa: F401

CASE = "/api/quotations/%s/case-record" % NO


def _po(c, h, lines, vendor="不在主檔的廠商"):
    r = _mk(c, h, "purchase_order", lines, data={"vendor": vendor}).json()
    assert _submit(c, h, r["id"]).status_code == 200
    return r


def _cr():
    cn = db.get_db()
    try:
        return json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"]).get("caseRecord") or {}
    finally:
        cn.close()


def _card(**kw):
    d = {"id": "c1", "name": "交換器", "ordered": False, "arrived": False, "orderItemId": ""}
    d.update(kw)
    return d


def _put(c, h, cards, **extra):
    cr = _cr()
    cr["materials"] = cards
    cr.update(extra)
    return c.patch(CASE, json={"case_record": cr}, headers=h)


def _stored(cid="c1"):
    return next((m for m in _cr().get("materials", []) if m.get("id") == cid), None)


def _rows(sql, *a):
    cn = db.get_db()
    try:
        return [dict(r) for r in cn.execute(sql, a).fetchall()]
    finally:
        cn.close()


def _codes(r):
    return [x["code"] for x in (r.json().get("rejected") or [])]


def _mails(monkeypatch):
    sent = []
    monkeypatch.setattr(MN._en, "send_registered", lambda key, **kw: sent.append((key, kw)) if key == "material_recognize_denied" else True)   # 只記認列被拒的信
    return sent


def _other(client, make_user, name="rc_admin"):
    u, p = make_user(username=name, role="admin")
    return _login(client, u, p)


def test_superadmin_recognizes_and_it_persists_without_application_or_payment(W):
    c, h = W
    po = _po(c, h, [_ln("a", 3, unitCost=1000)])
    r = _put(c, h, [_card(poLink={"key": "item:a", "price": 999}, ordered=True)])
    assert r.status_code == 200 and not r.json().get("rejected"), r.text
    m = _stored()
    pl = m["poLink"]
    assert pl["key"] == "item:a" and pl["vendor"] == "不在主檔的廠商" and pl["docCodes"] == [po["docCode"]] and pl["claimedBy"] == "pl_sa" and pl["claimedAt"]
    assert "price" not in pl and not any(k in json.dumps(pl) for k in ("unitCost", "totalPrice", "unitPrice")), pl
    assert m["ordered"] is True and not m["arrived"]
    assert _rows("SELECT * FROM case_material_approvals WHERE quote_no=?", NO) == []
    assert len(_rows("SELECT 1 FROM audit_log WHERE action='material.recognize' AND target_id=?", NO)) == 1
    g = {x["key"]: x for x in c.get("/api/quotations/%s/material-coverage" % NO, headers=h).json()["groups"]}["item:a"]
    assert g["recognized"] == "c1" and g["vendor"] == "不在主檔的廠商"
    r2 = _put(c, h, [dict(m, note="x", poLink={"key": "item:a"})])                    # 再存一次：冪等，伺服器值不變
    assert not r2.json().get("rejected") and _stored()["poLink"] == pl


def test_flags_without_recognition_are_still_refused_and_missing_poLink_key_keeps_the_link(W):
    c, h = W
    _po(c, h, [_ln("a", 3)])
    r = _put(c, h, [_card(ordered=True)])
    assert "order_not_approved" in _codes(r) and not _stored()["ordered"]
    assert not _put(c, h, [_card(poLink={"key": "item:a"}, ordered=True)]).json().get("rejected")
    r = _put(c, h, [_card(ordered=True)])                                              # 舊頁面不帶 poLink ⇒ 保留伺服器現值
    assert not r.json().get("rejected") and _stored()["poLink"]["key"] == "item:a"


def test_arrival_needs_a_date_server_stamps_confirmer_and_devices_revert_when_refused(W):
    c, h = W
    _po(c, h, [_ln("a", 3)])
    _put(c, h, [_card(poLink={"key": "item:a"}, ordered=True)])
    r = _put(c, h, [_card(poLink={"key": "item:a"}, ordered=True, arrived=True, devices=[{"sn": "SN1"}])])
    assert "receipt_missing" in _codes(r), r.text
    s = _stored()
    assert not s["arrived"] and not s.get("devices")
    r = _put(c, h, [_card(poLink={"key": "item:a", "arrivedOn": "2026-10-13", "arrivedBy": "forged", "arrivedAt": "x"}, ordered=True, arrived=True)])
    assert not r.json().get("rejected"), r.text
    pl = _stored()["poLink"]
    assert pl["arrivedOn"] == "2026-10-13" and pl["arrivedBy"] == "pl_sa" and pl["arrivedAt"] != "x"
    assert _rows("SELECT 1 FROM audit_log WHERE action='material.recognize_arrived'")
    _put(c, h, [_card(poLink={"key": "item:a"}, ordered=True, arrived=False)])
    assert "arrivedOn" not in _stored()["poLink"] and _rows("SELECT 1 FROM audit_log WHERE action='material.recognize_unarrived'")


def test_one_group_cannot_be_claimed_twice_even_within_one_payload(W):
    c, h = W
    _po(c, h, [_ln("a", 3)])
    r = _put(c, h, [_card(id="c1", poLink={"key": "item:a"}), _card(id="c2", poLink={"key": "item:a"})])
    assert "bad_recognize" in _codes(r)
    assert _stored("c1")["poLink"]["key"] == "item:a" and "poLink" not in _stored("c2")             # 正對照：第一張成立、第二張被拒
    r = _put(c, h, [_stored("c1"), _card(id="c3", poLink={"key": "item:a"})])
    assert "bad_recognize" in _codes(r) and "poLink" not in _stored("c3")


def test_unknown_key_and_group_with_live_application_are_refused(W):
    c, h = W
    _po(c, h, [_ln("a", 3)])
    assert "bad_recognize" in _codes(_put(c, h, [_card(poLink={"key": "item:zzz"})]))
    assert "bad_recognize" in _codes(_put(c, h, [_card(poLink={"key": "po:MQ-OTHER-0001"})]))
    order = {"itemId": "n1", "itemName": "交換器", "quantity": 1, "unit": "台", "unitPrice": 1, "totalPrice": 1, "quoteItemId": "a", "supplierId": 1}
    cn = db.get_db()
    try:
        d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d.setdefault("caseRecord", {})["materialOrders"] = [order]
        cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        cn.execute("INSERT INTO case_material_approvals (quote_no, item_id, status) VALUES (?,?,?)", (NO, "n1", "草稿"))   # 草稿也算占用
        cn.commit()
    finally:
        cn.close()
    assert "bad_recognize" in _codes(_put(c, h, [_card(poLink={"key": "item:a"})]))


def test_claimed_group_cannot_get_a_material_application(W):
    c, h = W
    po = _po(c, h, [_ln("a", 3)])
    _put(c, h, [_card(poLink={"key": "item:a"})])
    order = {"itemId": "n2", "itemName": "交換器", "quantity": 3, "unit": "台", "unitPrice": 1, "totalPrice": 3, "quoteItemId": "a", "supplierId": 1,
             "poDocCode": po["docCode"], "poLine": 1}
    r = _put(c, h, [_stored()], materialOrders=[order])
    assert "bad_link" in _codes(r), r.text
    assert "已認列" in " ".join(x["message"] for x in r.json()["rejected"] if x["code"] == "bad_link")
    assert not [o for o in _cr().get("materialOrders", []) if o.get("itemId") == "n2"]


def test_non_superadmin_is_cancelled_with_audit_one_mail_and_dedupe(W, client, make_user, monkeypatch):
    c, h = W
    sent = _mails(monkeypatch)
    _po(c, h, [_ln("a", 3)])
    adm = _other(client, make_user)
    r = _put(c, adm, [_card(name="改過的名稱", poLink={"key": "item:a"}, ordered=True, arrived=True, devices=[{"sn": "S"}])])
    assert r.status_code == 200, r.text
    assert "recognize_denied" in _codes(r)
    s = _stored()
    assert "poLink" not in s and not s["ordered"] and not s["arrived"] and not s.get("devices") and s["name"] == "改過的名稱"        # 其他欄位照存
    rows = _rows("SELECT detail FROM audit_log WHERE action='material.recognize_denied' AND username='rc_admin'")
    assert len(rows) == 1 and json.loads(rows[0]["detail"])["mailed"] is True
    assert len(sent) == 1 and sent[0][0] == "material_recognize_denied" and sent[0][1].get("to_group") is True
    blob = json.dumps(sent[0][1], ensure_ascii=False)
    assert "不在主檔" not in blob and "1000" not in blob and NO in blob and "rc_admin" in blob
    _put(c, adm, [_card(poLink={"key": "item:a"})])                                  # 同人同案件同組再試 ⇒ 稽核照寫、信不再寄
    assert len(_rows("SELECT 1 FROM audit_log WHERE action='material.recognize_denied'")) == 2 and len(sent) == 1
    _put(c, h, [_card(poLink={"key": "item:a"})])                                    # 正對照：最高管理者照常成立
    assert _stored()["poLink"]["key"] == "item:a"


def test_denied_without_mail_option_and_mail_cap(W, client, make_user, monkeypatch):
    c, h = W
    sent = _mails(monkeypatch)
    _po(c, h, [_ln("a", 3), _ln("b", 1)])
    adm = _other(client, make_user)
    monkeypatch.setattr(MR, "_setting", lambda k, d, conn=None: {"on_denied": 2}.get(k, d))
    _put(c, adm, [_card(poLink={"key": "item:a"})])
    assert not sent and _rows("SELECT 1 FROM audit_log WHERE action='material.recognize_denied'")
    monkeypatch.setattr(MR, "_setting", lambda k, d, conn=None: {"mail_cap": 1}.get(k, d))
    _put(c, adm, [_card(poLink={"key": "item:a"})])
    _put(c, adm, [_card(poLink={"key": "item:b"})])                                  # 不同組但已達上限 ⇒ 不寄
    assert len(sent) == 1


def test_anyone_option_lets_a_case_writer_recognize(W, client, make_user, monkeypatch):
    c, h = W
    _po(c, h, [_ln("a", 3)])
    adm = _other(client, make_user)
    monkeypatch.setattr(MR, "_setting", lambda k, d, conn=None: {"who_may": 2}.get(k, d))
    assert not _put(c, adm, [_card(poLink={"key": "item:a"}, ordered=True)]).json().get("rejected")
    assert _stored()["poLink"]["claimedBy"] == "rc_admin"


def test_non_superadmin_cannot_remove_or_alter_an_existing_link_and_unlink_reverts_flags(W, client, make_user, monkeypatch):
    c, h = W
    _mails(monkeypatch)
    _po(c, h, [_ln("a", 3)])
    _put(c, h, [_card(poLink={"key": "item:a"}, ordered=True)])
    adm = _other(client, make_user)
    r = _put(c, adm, [_card(poLink=None, ordered=True, note="n")])
    assert "recognize_denied" in _codes(r) and _stored()["poLink"]["key"] == "item:a" and _stored()["ordered"] and _stored()["note"] == "n"
    r = _put(c, h, [_card(poLink=None, ordered=True)])                                  # 最高管理者取消認列 ⇒ 旗標一併取消
    assert not r.json().get("rejected") and not _stored().get("poLink") and not _stored()["ordered"]
    assert len(_rows("SELECT 1 FROM audit_log WHERE action='material.recognize_undo'")) == 1                 # 寫入漏斗再過一次閘也只記一筆


def test_system_path_keeps_valid_link_but_never_accepts_a_new_one(W):
    c, h = W
    _po(c, h, [_ln("a", 3), _ln("b", 1)])
    _put(c, h, [_card(poLink={"key": "item:a"})])
    cn = db.get_db()
    try:
        data = {"caseRecord": {"materials": [_card(poLink={"key": "item:a"}, ordered=True), _card(id="c2", poLink={"key": "item:b"}, ordered=True)]}}
        rej = MG.enforce(cn, NO, data, actor=None)
        cn.commit()
    finally:
        cn.close()
    m = {x["id"]: x for x in data["caseRecord"]["materials"]}
    assert m["c1"]["poLink"]["key"] == "item:a" and not m["c1"]["ordered"]                 # 系統不能代為勾旗標
    assert "poLink" not in m["c2"] and not m["c2"]["ordered"]
    assert {"recognize_denied"} <= {x["code"] for x in rej}


def test_revoked_po_makes_the_link_stale_and_frees_coverage(W):
    c, h = W
    po = _po(c, h, [_ln("a", 3)])
    _put(c, h, [_card(poLink={"key": "item:a"}, ordered=True)])
    _status(po["id"], "草稿")                                                          # 採購單被撤銷
    r = _put(c, h, [_card(poLink={"key": "item:a"}, ordered=True, arrived=True)])
    codes = _codes(r)
    assert "recognize_stale" in codes and not _stored()["arrived"] and _stored()["ordered"], r.text   # 旗標歷史保留、不能再勾
    assert _stored()["poLink"].get("stale") is True
    groups = {x["key"] for x in c.get("/api/quotations/%s/material-coverage" % NO, headers=h).json()["groups"]}
    assert "item:a" not in groups


def test_deleting_a_recognized_card_needs_the_same_permission_and_is_audited(W, client, make_user, monkeypatch):
    c, h = W
    _mails(monkeypatch)
    _po(c, h, [_ln("a", 3)])
    _put(c, h, [_card(poLink={"key": "item:a"}, ordered=True), _card(id="c2")])
    adm = _other(client, make_user)
    r = _put(c, adm, [_card(id="c2")])                                                   # 非最高管理者把認列中的卡片從清單拿掉
    assert "recognize_denied" in _codes(r)
    assert _stored("c1") and _stored("c1")["poLink"]["key"] == "item:a" and _stored("c1")["ordered"]       # 卡片還在、認列還在
    rows = _rows("SELECT detail FROM audit_log WHERE action='material.recognize_denied'")
    assert rows and json.loads(rows[0]["detail"])["attempt"] == "remove_card"
    r = _put(c, h, [_card(id="c2")])                                                      # 正對照：最高管理者可以，留 undo 稽核
    assert not r.json().get("rejected") and _stored("c1") is None
    und = _rows("SELECT detail FROM audit_log WHERE action='material.recognize_undo'")
    assert len(und) == 1 and json.loads(und[0]["detail"])["removedWithCard"] is True
    assert "poLink" not in (_stored("c2") or {})


def test_system_path_never_deletes_a_recognized_card(W):
    c, h = W
    _po(c, h, [_ln("a", 3)])
    _put(c, h, [_card(poLink={"key": "item:a"})])
    cn = db.get_db()
    try:
        data = {"caseRecord": {"materials": []}}
        rej = MG.enforce(cn, NO, data, actor=None)
        cn.commit()
    finally:
        cn.close()
    assert [m["id"] for m in data["caseRecord"]["materials"]] == ["c1"] and "recognize_denied" in {x["code"] for x in rej}


def test_a_stale_claim_still_holds_the_key_so_re_approval_cannot_make_two_active_claims(W):
    c, h = W
    po = _po(c, h, [_ln("a", 3)])
    _put(c, h, [_card(id="A", poLink={"key": "item:a"})])
    _status(po["id"], "草稿")
    _put(c, h, [_stored("A")])                                                            # A 過期
    assert _stored("A")["poLink"].get("stale") is True
    _status(po["id"], "已核准")                                                           # 採購單重新核准
    r = _put(c, h, [_stored("A"), _card(id="B", poLink={"key": "item:a"})])
    assert "bad_recognize" in _codes(r) and "poLink" not in _stored("B")                    # B 搶不到：A 還持有
    _put(c, h, [_stored("A"), _card(id="B")])
    active = [m for m in _cr()["materials"] if (m.get("poLink") or {}).get("key") == "item:a" and not m["poLink"].get("stale")]
    assert [m["id"] for m in active] == ["A"]


def test_who_may_option_two_is_limited_to_roles_that_can_edit_material_orders(W, client, make_user, monkeypatch):
    c, h = W
    _mails(monkeypatch)
    _po(c, h, [_ln("a", 3)])
    u, p = make_user(username="rc_sales", role="sales", modules=["quotation"])
    sales = _login(client, u, p)
    monkeypatch.setattr(MR, "_setting", lambda k, d, conn=None: {"who_may": 2}.get(k, d))
    _put(c, sales, [_card(poLink={"key": "item:a"})])                                     # 不論端點放不放行，業務都不能認列
    assert not (_stored() or {}).get("poLink")


def test_two_requests_each_write_their_own_audit_row_and_rollback_leaves_no_marker(W):
    c, h = W
    _po(c, h, [_ln("a", 3)])
    _put(c, h, [_card(poLink={"key": "item:a"})])
    _put(c, h, [_card(poLink=None)])
    _put(c, h, [_card(poLink={"key": "item:a"})])                                         # 同樣的事、另一個請求（另一條連線）⇒ 不可被去重吞掉
    assert len(_rows("SELECT 1 FROM audit_log WHERE action='material.recognize'")) == 2
    cn = db.get_db()
    try:
        cn.execute("BEGIN IMMEDIATE")
        MG.enforce(cn, NO, {"caseRecord": {"materials": [_card(id="c9", poLink={"key": "item:a"})]}}, actor={"username": "x", "role": "superadmin"})
        cn.rollback()
        try:
            left = cn.execute("SELECT COUNT(*) FROM temp._rg_seen").fetchone()[0]
        except Exception:                                                                 # noqa: BLE001 — 表也一併回滾了
            left = 0
        assert left == 0
    finally:
        cn.close()


def test_closed_case_change_request_cannot_carry_a_recognition(W):
    c, h = W
    _po(c, h, [_ln("a", 3)])
    cn = db.get_db()
    cn.execute("UPDATE quotations SET deal_tag='已結案', case_semi_unlocked=1 WHERE quote_no=?", (NO,))
    cn.commit()
    cn.close()
    r = _put(c, h, [_card(poLink={"key": "item:a"})])
    assert r.status_code == 409 and "認列" in r.text
    assert not _rows("SELECT 1 FROM case_change_requests WHERE quote_no=?", NO)
