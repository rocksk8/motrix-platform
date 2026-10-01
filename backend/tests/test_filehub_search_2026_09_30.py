# -*- coding: utf-8 -*-
"""附件目錄 P3（設計 proposal-attachments-search-preview §4-4、§7）：檔案中心 `GET /api/filehub/search` ＋各提供者的 `search`／`count`。

核心題（test_catalog_search_matches_open）：對每個使用者，**搜尋列得出來的檔都打得開、打得開的檔都列得出來**（目錄不得比原單據寬、也不得窄到擁有者搜不到）。
另驗：看不到的不列也不回個數、項目沒有 path、條件篩選、分頁與 page≤20、模組不在／提供者壞掉明說、沒有「檔案中心」模組的人不能全域瀏覽（但可帶 quote_no）。
反向控制見各題註解（提供者忽略 user ⇒ 紅；回了 path ⇒ 紅；吞掉 unavailable ⇒ 紅）。"""
import pytest

from core import registry
from helpers import attachment_search as S
from helpers import uploads as up
from tests.test_attachments_open_2026_09_30 import PNG, Q, _login, _open, world  # noqa: F401  (world 是 fixture)


def _search(client, h, **params):
    return client.get("/api/filehub/search", headers=h, params=params)


def _upload_quotation_signed(client, H, name="s.png"):
    r = client.post(f"/api/quotations/{Q}/signed-files", headers=H["ct_admin"], files=[("files", (name, PNG, "image/png"))])
    assert r.status_code in (200, 201), r.text
    return r.json()["files"][-1]["id"]


def _keys(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)
    return out


# ── 純函式（共用件）──────────────────────────────────────────────────────

def _item(**kw):
    base = S.make_item("quotation_signed", "MQ-1", "報價單 MQ-1", {"id": "f1", "filename": "回簽.PDF", "size": 10, "uploadedBy": "amy",
                                                                   "uploadedAt": "2026-09-10T10:00:00"}, quote_no="MQ-1", customer="甲客戶", project="工程")
    base.update(kw)
    return base


def test_normalize_crit_and_item_shape():
    c = S.normalize_crit({"q": " 回簽 ", "types": "a,b,a", "exts": ".PDF, png", "take": "99999", "zzz": 1})
    assert c["q"] == "回簽" and c["types"] == ["a", "b"] and c["exts"] == ["pdf", "png"] and c["take"] == S.MAX_TAKE and "zzz" not in c
    assert S.normalize_crit(None)["take"] == 50 and S.normalize_crit({"take": "x"})["take"] == 50
    it = _item()
    assert set(it) == set(S.ITEM_KEYS) and "path" not in it and it["ext"] == "pdf" and it["size"] == 10


def test_matches_semantics_and_finish_order():
    it = _item()
    m = lambda **kw: S.matches(it, S.normalize_crit(kw))
    assert m() and m(q="回簽") and m(q="mq-1") and m(q="甲客戶") and m(q="工程") and not m(q="沒有這個字")
    assert m(types="quotation_signed") and not m(types="voucher")
    assert m(exts="pdf") and not m(exts="png")
    assert m(date_from="2026-09-10", date_to="2026-09-10") and not m(date_from="2026-09-11") and not m(date_to="2026-09-09")
    assert m(uploader="AM") and not m(uploader="bob")
    assert m(quote_no="mq-1") and not m(quote_no="MQ")                     # 案件號是精確比對（案件頁固定用它）
    assert m(doc_no="MQ") and m(customer="甲")
    older = _item(uploadedAt="2026-09-01T00:00:00", fileId="f0")
    newer = _item(uploadedAt="2026-09-20T00:00:00", fileId="f2")
    assert [x["fileId"] for x in S.finish([older, it, newer], S.normalize_crit({"take": 2}))] == ["f2", "f1"]
    assert S.count_by_type([it, older, _item(sourceType="voucher")], S.normalize_crit({"types": "voucher"})) == {"quotation_signed": 2, "voucher": 1}


# ── 核心：搜尋列得出來 ⇔ 打得開 ────────────────────────────────────────────

def test_catalog_search_matches_open(client, world):
    """**反向控制**：提供者忽略 user ⇒ ct_out／ct_none 會搜到打不開的檔 ⇒ 第一個迴圈紅；規則寫得比原端點窄 ⇒ 第二個迴圈紅。"""
    H, note_no, f = world
    fid = _upload_quotation_signed(client, H)
    known = [("completion_note", note_no, f["id"]), ("quotation_signed", Q, fid)]
    for who in H:
        r = _search(client, H[who], quote_no=Q, size=50)
        if r.status_code == 403:                                # ct_* 都沒有檔案中心模組，但帶 quote_no 一律 200
            pytest.fail("帶 quote_no 不該 403：%s" % who)
        assert r.status_code == 200, (who, r.text)
        listed = {(i["sourceType"], i["docNo"], i["fileId"]) for i in r.json()["items"]}
        for t, d, fi in listed:
            assert _open(client, H[who], t, d, fi).status_code == 200, ("列得出來卻打不開", who, t, d)
        for t, d, fi in known:
            if _open(client, H[who], t, d, fi).status_code == 200:
                assert (t, d, fi) in listed, ("打得開卻搜不到", who, t, d)


def test_hidden_files_are_not_listed_not_counted_and_no_hidden_count_field(client, world):
    H, note_no, f = world
    _upload_quotation_signed(client, H)
    out = _search(client, H["ct_out"], quote_no=Q, q="sign").json()                  # ct_out 不是該案的人
    assert out["items"] == [] and out["facets"]["byType"].get("completion_note", 0) == 0
    flat = {k.lower() for k in _keys(out)}
    assert not any("hidden" in k or "denied" in k or "forbidden" in k for k in flat), flat    # 不回「因權限未列出 N 個」
    assert "sign.png" not in str(out)                                                 # 連檔名都不出現在任何欄位（facets／unavailable）
    mine = _search(client, H["ct_owner"], quote_no=Q).json()
    assert {i["sourceType"] for i in mine["items"]} >= {"quotation_signed"}


def test_items_have_only_the_fixed_keys_and_never_a_path(client, world):
    H, note_no, f = world
    _upload_quotation_signed(client, H)
    body = _search(client, H["ct_admin"], quote_no=Q).json()
    assert body["items"]
    for it in body["items"]:
        assert set(it) <= set(S.ITEM_KEYS), set(it) - set(S.ITEM_KEYS)
    assert "path" not in _keys(body) and "abs_path" not in _keys(body)
    assert f["path"] not in str(body)                                                 # 檔案路徑不在任何欄位
    it = next(i for i in body["items"] if i["sourceType"] == "completion_note")
    assert it["quoteNo"] == Q and it["customerName"] == "客戶" and it["projectName"] == "工程" and it["link"].startswith("case-management.html?q=")


# ── 條件、分頁 ──────────────────────────────────────────────────────────

def test_filters_types_exts_q_and_pagination(client, world):
    H, note_no, f = world
    for n in ("a.png", "b.png", "c.png"):
        _upload_quotation_signed(client, H, n)
    base = dict(quote_no=Q)
    allr = _search(client, H["ct_admin"], size=50, **base).json()
    names = {i["filename"] for i in allr["items"]}
    assert {"a.png", "b.png", "c.png", "sign.png"} <= names
    assert {i["filename"] for i in _search(client, H["ct_admin"], q="b.p", **base).json()["items"]} == {"b.png"}
    only = _search(client, H["ct_admin"], types="completion_note", **base).json()
    assert {i["sourceType"] for i in only["items"]} == {"completion_note"}
    assert only["facets"]["byType"].get("quotation_signed", 0) >= 3                   # 分類數字不受 types 條件影響
    assert _search(client, H["ct_admin"], exts="pdf", **base).json()["items"] == []
    p1 = _search(client, H["ct_admin"], size=2, page=1, **base).json()
    p2 = _search(client, H["ct_admin"], size=2, page=2, **base).json()
    k = lambda r: [(i["sourceType"], i["docNo"], i["fileId"]) for i in r["items"]]
    assert len(p1["items"]) == 2 and p1["hasMore"] is True and not set(k(p1)) & set(k(p2))        # 翻頁穩定、不重複
    assert _search(client, H["ct_admin"], size=2, page=21, **base).status_code == 400
    cats = {c["type"]: c for c in allr["categories"]}
    assert {"quotation_signed", "completion_note", "shipping_note", "invoice_voucher", "voucher", "payslip_signed", "dev_log"} <= set(cats)
    assert all({"type", "label", "doc", "module", "count"} <= set(c) for c in cats.values())


def test_uploader_and_date_filters(client, world):
    H, _, _ = world
    _upload_quotation_signed(client, H, "d.png")
    assert _search(client, H["ct_admin"], quote_no=Q, date_from="2999-01-01").json()["items"] == []
    assert _search(client, H["ct_admin"], quote_no=Q, date_to="2000-01-01").json()["items"] == []
    assert _search(client, H["ct_admin"], quote_no=Q, uploader="nobody_xyz").json()["items"] == []
    assert _search(client, H["ct_admin"], quote_no=Q, uploader="ct_admin").json()["items"]


# ── 權限與缺席 ──────────────────────────────────────────────────────────

def test_global_browse_needs_the_file_center_module_but_a_case_filter_does_not(client, world, make_user):
    H, _, _ = world
    assert _search(client, H["ct_owner"]).status_code == 403                          # 沒有檔案中心模組：不能全域瀏覽
    assert _search(client, H["ct_owner"], quote_no=Q).status_code == 200
    u, p = make_user(username="fc_user", role="sales", modules=["file_center"])
    assert _search(client, _login(client, u, p)).status_code == 200
    u2, p2 = make_user(username="fc_boss", role="superadmin", modules=[])
    assert _search(client, _login(client, u2, p2)).status_code == 200
    assert client.get("/api/filehub/search").status_code == 401


def test_a_missing_owner_module_is_reported_not_silent(client, world, monkeypatch):
    """**反向控制**：把 unavailable 吞掉 ⇒ 這題紅（缺席長得跟『沒有檔案』一樣）。"""
    H, _, _ = world
    real = registry.module_states
    monkeypatch.setattr(registry, "module_states", lambda: [s for s in real() if s["key"] != "supply"])
    body = _search(client, H["ct_admin"], quote_no=Q).json()
    assert any("採購・庫存・出貨" in u["reason"] and "不是 0 筆" in u["reason"] for u in body["unavailable"]), body["unavailable"]


class _Boom:
    CATEGORIES = {"zz_boom": {"label": "壞掉的一類", "doc": "壞單", "module": "測試"}}

    @staticmethod
    def open(conn, user, source_type, doc_no, file_id):
        return None

    @staticmethod
    def search(conn, user, crit):
        raise RuntimeError("提供者壞了")

    @staticmethod
    def count(conn, user, crit):
        return {}


class _OldProvider:                      # P2 時代的提供者：只有 CATEGORIES＋open，沒有 search／count
    CATEGORIES = {"zz_old": {"label": "舊提供者", "doc": "舊單", "module": "測試"}}

    @staticmethod
    def open(conn, user, source_type, doc_no, file_id):
        return None


def test_a_broken_or_old_provider_only_loses_its_own_category_and_says_so(client, world):
    H, note_no, f = world
    saved = dict(registry._LEGACY_PROVIDERS)
    registry._LEGACY_PROVIDERS[(up.ATTACHMENTS_CATALOG, "zz_boom")] = _Boom
    registry._LEGACY_PROVIDERS[(up.ATTACHMENTS_CATALOG, "zz_old")] = _OldProvider
    try:
        r = _search(client, H["ct_admin"], quote_no=Q)
        assert r.status_code == 200, r.text
        body = r.json()
        assert any(i["sourceType"] == "completion_note" for i in body["items"])       # 其他類照常
        reasons = " ".join(u["reason"] for u in body["unavailable"])
        assert "zz_boom" in reasons and "zz_old" in reasons and "不是 0 筆" in reasons
    finally:
        registry._LEGACY_PROVIDERS.clear()
        registry._LEGACY_PROVIDERS.update(saved)
