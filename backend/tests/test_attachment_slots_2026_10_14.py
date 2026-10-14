# -*- coding: utf-8 -*-
"""BP-4 S2：附件插槽定義（kind `attachment_slot`）、寬嚴分級、唯讀模擬上傳、旗標關閉＝不起作用。

1. 驗證器：只能縮小（副檔名 ⊂ 硬底線、上限、子夾規則、保留鍵、金額字眼、不認得的鍵）。
2. 旗標關閉：路由 404／只回內建；定義文件庫存得了草稿但完全不起作用。
3. 旗標開啟：發布後 `effective_slots`／`slot_policy` 認得；uploaders 只能收窄；停用的不給。
4. 寬嚴比較：加副檔名／加大上限／擴大上傳者／改子夾／重新啟用＝放寬；縮小＝收緊；其餘中性；經 def_pipeline 放寬進待核准。
5. 模擬上傳：收／不收的白話原因、顯示用路徑、逐角色人數；唯讀（不寫檔、不建資料夾、不寫稽核、不動定義表）。
6. 讀取提供者（case）的 SLOT_AWARE：三段路徑走同一條規則；兩段照舊；其他資料夾不受影響。
"""
import json
from pathlib import Path

import pytest

from helpers import attachment_slots as AS
from helpers import storage_slots as SS
from helpers import uploads as U

KEY = "doc:completion_note"
BASE = "/api/definitions/attachment_slot/" + KEY


def S(**kw):
    d = {"key": "site_photo", "label": "現場照片", "accept": [".jpg", ".png"], "maxFileMb": 10, "maxFiles": 5, "maxRequestMb": 20}
    d.update(kw)
    return d


def B(*slots):
    return {"slots": list(slots)}


@pytest.fixture()
def hdr(client, make_user):
    u, p = make_user(username="slot_sa", role="superadmin")
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


@pytest.fixture(autouse=True)
def _kind_clean():
    """旗標跟著測試開關：測試結束把 attachment_slot 種類登記撤掉，不污染別的測試的 /api/definition-kinds。"""
    yield
    AS._sync_kind(False)                                                      # noqa: SLF001


@pytest.fixture()
def on(monkeypatch):
    monkeypatch.setattr(SS, "enabled", lambda conn=None: True)
    monkeypatch.setattr(AS, "_provider_slot_aware", lambda code: True)
    AS.enabled()                                                              # 旗標開 ⇒ 種類登記（編輯器載入時先打 catalog 也是這個效果）


def _msgs(body, key=KEY):
    return " | ".join(p["message"] for p in AS.definition_problems(key, body))


# ── 1. 驗證器 ────────────────────────────────────────────────────────────────
def test_kind_is_registered_and_a_good_definition_passes(on):
    from core import definitions as D
    assert AS.KIND in D.kinds()
    assert AS.definition_problems(KEY, B(S())) == []
    assert AS.definition_problems(KEY, B()) == []


@pytest.mark.parametrize("slot,needle", [
    (S(accept=[".exe"]), "不在系統允許範圍"), (S(accept=[".html", ".pdf"]), "不在系統允許範圍"), (S(accept=[]), "至少一項"),
    (S(accept=[".pdf", ".pdf"]), "重複"), (S(key="signed"), "內建"), (S(key="Bad-Key"), "代號"),
    (S(label="成本照片"), "金額"), (S(label="<b>x</b>"), "不可含"), (S(label=" "), "空白"),
    (S(maxFiles=0), "maxFiles"), (S(maxFiles=99), "maxFiles"), (S(maxFileMb=10 ** 6), "maxFileMb"), (S(maxRequestMb=500), "maxRequestMb"),
    (S(maxFiles=True), "maxFiles"), (S(subfolder="a/b"), "單層"), (S(subfolder=".."), "單層"), (S(subfolder="CON"), "保留"),
    (S(subfolder="x."), "單層"), (S(uploaders={"roles": ["root"]}), "角色"), (S(uploaders={"x": 1}), "只能有"),
    (S(hack=1), "不認得的鍵"), (S(required="yes"), "true"),
])
def test_validator_rejects(on, slot, needle):
    assert needle in _msgs(B(slot)), _msgs(B(slot))


def test_validator_rejects_bad_keys_duplicates_and_too_many(on):
    assert "doc:" in _msgs(B(), key="module:x")
    assert "doc:" in _msgs(B(), key="doc:no_such_doc")
    assert "重複" in _msgs(B(S(), S()))
    assert "最多" in _msgs(B(*[S(key="s%d" % i, subfolder="f%d" % i) for i in range(AS.MAX_SLOTS + 1)]))
    assert "重複" in _msgs(B(S(subfolder="Abc"), S(key="b", subfolder="abc")))        # 子夾不分大小寫
    assert "不認得的鍵" in _msgs({"slots": [], "extra": 1})


def test_subfolder_needs_a_slot_aware_provider(monkeypatch):
    monkeypatch.setattr(AS, "_provider_slot_aware", lambda code: False)
    assert "不支援子資料夾" in _msgs(B(S(subfolder="驗收單")))
    monkeypatch.setattr(AS, "_provider_slot_aware", lambda code: True)
    assert AS.definition_problems(KEY, B(S(subfolder="驗收單"))) == []
    assert "NFC" in _msgs({"slots": [S(subfolder="é")]})


# ── 2. 旗標關閉＝不起作用 ─────────────────────────────────────────────────────
def test_flag_off_routes_are_inert(client, hdr, monkeypatch):
    assert SS.enabled() is False
    assert client.get("/api/attachment-slots/catalog", headers=hdr).status_code == 404
    assert client.post("/api/attachment-slots/completion_note/simulate", headers=hdr, json={"definition": B(), "sample": {}}).status_code == 404
    assert client.get("/api/attachment-slots/completion_note", headers=hdr).status_code == 404       # 新路由 OFF ⇒ 404（不是回內建）
    assert client.get("/api/attachment-slots/no_such", headers=hdr).status_code == 404
    assert client.get("/api/attachment-slots/completion_note").status_code == 401


def test_flag_off_the_kind_does_not_exist_so_nothing_can_be_stored_or_read(client, hdr, monkeypatch):
    monkeypatch.setattr(AS, "_provider_slot_aware", lambda code: True)
    assert client.put(BASE + "/draft", headers=hdr, json={"body": B(S())}).status_code == 400            # 種類未登記 ⇒ 存不了草稿
    assert client.get(BASE, headers=hdr).status_code in (400, 404)
    from db import get_db
    conn = get_db()
    try:
        assert [s["key"] for s in AS.effective_slots(conn, "completion_note")] == ["signed"]
        with pytest.raises(LookupError):
            AS.slot_policy(conn, "completion_note", "site_photo", {"role": "superadmin"})
        with pytest.raises(LookupError):
            SS.policy("completion_note", "site_photo", conn)
        assert SS.policy("completion_note", "", conn) == SS.builtin_policy("completion_notes")
    finally:
        conn.close()


# ── 3. 旗標開啟 ──────────────────────────────────────────────────────────────
def _publish(client, hdr, body):
    assert client.put(BASE + "/draft", headers=hdr, json={"body": body}).status_code == 200
    r = client.post(BASE + "/publish", headers=hdr, json={"note": "n"})
    assert r.status_code == 200, r.text
    return r.json()


def test_published_slots_are_effective_and_uploaders_only_narrow(client, hdr, on):
    _publish(client, hdr, B(S(), S(key="boss_only", label="主管用", uploaders={"roles": ["admin"]}), S(key="off", label="停用中", disabled=True)))
    from db import get_db
    conn = get_db()
    try:
        keys = lambda u: [s["key"] for s in AS.effective_slots(conn, "completion_note", u)]          # noqa: E731
        assert keys(None) == ["signed", "site_photo", "boss_only"]                                    # 停用的不給
        assert keys({"role": "sales", "modules": "[]", "id": 0}) == ["signed", "site_photo"]
        assert keys({"role": "admin", "modules": "[]", "id": 0}) == ["signed", "site_photo", "boss_only"]
        assert keys({"role": "superadmin", "modules": "[]", "id": 0}) == ["signed", "site_photo", "boss_only"]
        p = AS.slot_policy(conn, "completion_note", "site_photo", {"role": "sales", "modules": "[]", "id": 0})
        assert p.code == "completion_notes" and set(p.accept) == {".jpg", ".png"} and p.slot == "site_photo" and not p.builtin
        assert (p.max_files, p.max_request_bytes, p.max_file_bytes) == (5, 20 * 1024 * 1024, 10 * 1024 * 1024)
        with pytest.raises(PermissionError):
            AS.slot_policy(conn, "completion_note", "boss_only", {"role": "sales", "modules": "[]", "id": 0})
        with pytest.raises(LookupError):
            AS.slot_policy(conn, "completion_note", "off", {"role": "superadmin"})
        assert AS.slot_policy(conn, "completion_note", "signed", {"role": "sales"}) == SS.builtin_policy("completion_notes")
        assert SS.policy("completion_note", "site_photo", conn).slot == "site_photo"
    finally:
        conn.close()
    r = client.get("/api/attachment-slots/completion_note", headers=hdr).json()
    assert r["enabled"] is True and "site_photo" in [s["key"] for s in r["slots"]]
    cat = client.get("/api/attachment-slots/catalog", headers=hdr).json()
    assert cat["docTypes"][0]["code"] == "completion_notes" and ".exe" not in cat["hardExts"] and cat["builtinSlot"] == "signed"


def test_uploaders_by_module(client, hdr, on):
    _publish(client, hdr, B(S(uploaders={"modules": ["accounting"]})))
    from db import get_db
    conn = get_db()
    try:
        assert [s["key"] for s in AS.effective_slots(conn, "completion_note", {"role": "sales", "modules": "[]", "id": 0})] == ["signed"]
        assert "site_photo" in [s["key"] for s in AS.effective_slots(conn, "completion_note", {"role": "sales", "modules": '["accounting"]', "id": 0})]
    finally:
        conn.close()


# ── 4. 寬嚴比較 ──────────────────────────────────────────────────────────────
def cmp_(old, new):
    return AS.compare(B(*old), B(*new))[0]


def test_compare_table():
    base = [S(uploaders={"roles": ["admin"]})]
    assert cmp_(base, base) == "neutral"
    assert cmp_(base, [S(label="改名", required=True, uploaders={"roles": ["admin"]})]) == "neutral"
    for widened in (S(accept=[".jpg", ".png", ".pdf"], uploaders={"roles": ["admin"]}), S(maxFileMb=11, uploaders={"roles": ["admin"]}),
                    S(maxFiles=6, uploaders={"roles": ["admin"]}), S(maxRequestMb=21, uploaders={"roles": ["admin"]}),
                    S(subfolder="新夾", uploaders={"roles": ["admin"]}), S(uploaders={"roles": ["admin", "sales"]}), S(uploaders={"modules": ["x"], "roles": ["admin"]}),
                    S(), S(uploaders={"roles": ["admin"]}, hack_unknown=1)):
        assert cmp_(base, [widened]) == "loosen", widened
    for narrowed in (S(accept=[".jpg"], uploaders={"roles": ["admin"]}), S(maxFiles=4, uploaders={"roles": ["admin"]}),
                     S(uploaders={"roles": []}), S(disabled=True, uploaders={"roles": ["admin"]})):
        assert cmp_(base, [narrowed]) in ("tighten", "loosen"), narrowed
    assert cmp_(base, [S(accept=[".jpg"], uploaders={"roles": ["admin"]})]) == "tighten"
    assert cmp_(base, []) == "tighten"                                                 # 移除
    assert cmp_([S(disabled=True)], [S(disabled=False)]) == "loosen"                  # 重新啟用
    # 新增插槽：不比今天寬（副檔名 ⊂ 內建、沒有新子夾）＝中性；收今天不收的類型或用新子夾＝放寬
    assert cmp_([], [S(accept=[".pdf"])]) == "neutral"
    assert cmp_([], [S(accept=[".docx"])]) == "loosen"
    assert cmp_([], [S(subfolder="新夾")]) == "loosen"
    assert cmp_([], [S(accept=[".docx"], disabled=True)]) == "neutral"                # 新增但停用
    assert AS.compare(None, "not-a-dict")[0] == "loosen"                               # 無法解析 ⇒ 放寬


def test_pipeline_routes_loosening_to_pending_and_narrowing_immediately(client, hdr, on, monkeypatch):
    from routers import def_pipeline as P
    monkeypatch.setattr(P, "enabled", lambda conn=None: True)
    assert "attachment_slot" in P.ACTIVE_KINDS
    assert P.classify("attachment_slot", B(S()), B(S(accept=[".jpg", ".png", ".pdf"])))[0] == "loosen"
    first = _publish(client, hdr, B(S()))                                              # 新增中性/收緊的第一版：立即生效
    assert not first.get("pending")
    assert client.put(BASE + "/draft", headers=hdr, json={"body": B(S(accept=[".jpg", ".png", ".docx"]))}).status_code == 200
    r = client.post(BASE + "/publish", headers=hdr, json={"note": "加 docx"})
    assert r.status_code == 200 and r.json().get("pending") is True and r.json()["reasons"]
    assert client.put(BASE + "/draft", headers=hdr, json={"body": B(S(accept=[".jpg"]))}).status_code in (200, 409)


# ── 5. 模擬上傳 ──────────────────────────────────────────────────────────────
def _sim(client, hdr, definition, slot="site_photo", **sample):
    s = {"filename": "a.jpg", "size": 1000, "existing": 0}
    s.update(sample)
    return client.post("/api/attachment-slots/completion_note/simulate", headers=hdr, json={"definition": definition, "slot": slot, "sample": s})


@pytest.mark.upload_magic        # 驗檔頭本身：用真的判定（conftest 預設把 _magic_matches 換成一律符合）
def test_simulate_verdicts(client, hdr, on):
    d = B(S(subfolder="驗收單"))
    ok = _sim(client, hdr, d).json()
    assert ok["ok"] is True and ok["displayPath"] == "uploads/completion_notes/驗收單/〈單號〉/〈系統產生〉.jpg" and ok["provider"] == "case"
    assert "C:" not in ok["displayPath"] and "\\" not in ok["displayPath"]                                    # 不洩漏磁碟路徑
    assert ok["limits"]["maxFiles"] == 5 and "已存的檔案不搬移" in ok["note"]
    for kw, needle in ((dict(filename="a.pdf"), "不收"), (dict(size=0), "空的"), (dict(size=11 * 1024 * 1024), "過大"), (dict(existing=5), "件數已滿"),
                       (dict(filename="a.exe.jpg"), "雙重副檔名"), (dict(filename="noext"), "沒有副檔名"),
                       (dict(headerHex="25504446"), "檔頭與副檔名不符"), (dict(headerHex="zz"), "十六進位")):
        r = _sim(client, hdr, d, **kw).json()
        assert r["ok"] is False and any(needle in x for x in r["reasons"]), (kw, r["reasons"])
    assert _sim(client, hdr, d, headerHex="ffd8ffe0").json()["ok"] is True
    assert _sim(client, hdr, d, slot="signed", filename="a.pdf").json()["ok"] is True                         # 內建簽回單＝今天的行為
    assert _sim(client, hdr, d, slot="signed", filename="a.docx").json()["ok"] is False


def test_simulate_errors_and_permissions(client, hdr, on, make_user):
    assert _sim(client, hdr, B(S(accept=[".exe"]))).status_code == 422
    assert _sim(client, hdr, B(S()), slot="nope").status_code == 404
    assert client.post("/api/attachment-slots/completion_note/simulate", headers=hdr, json={"slot": "x"}).status_code == 422
    u, p = make_user(username="slot_sales", role="sales")
    h2 = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    assert client.post("/api/attachment-slots/completion_note/simulate", headers=h2, json={"definition": B(), "sample": {}}).status_code == 403
    assert client.get("/api/attachment-slots/catalog", headers=h2).status_code == 403


def test_simulate_readers_matrix_counts_per_role_without_names(client, hdr, on, monkeypatch, make_user):
    make_user(username="slot_e1", role="engineer")
    monkeypatch.setattr(U, "upload_readable", lambda conn, rel, user: user.get("role") in ("engineer", "superadmin") and rel.startswith("completion_notes/驗收單/N-1/"))
    r = client.post("/api/attachment-slots/completion_note/simulate", headers=hdr,
                    json={"definition": B(S(subfolder="驗收單")), "slot": "site_photo", "docNo": "N-1", "sample": {"filename": "a.jpg", "size": 5}}).json()
    assert r["readers"]["engineer"]["canRead"] >= 1 and r["readers"]["engineer"]["canRead"] == r["readers"]["engineer"]["accounts"]
    assert r["readers"]["sales"]["canRead"] == 0
    assert all(set(v) == {"canRead", "accounts"} for v in r["readers"].values())                               # 只有人數，沒有名單
    no_doc = _sim(client, hdr, B(S())).json()
    assert no_doc["readers"] is None                                                                           # 沒選樣本單據 ⇒ 不算


def test_simulate_is_read_only(client, hdr, on):
    from db import get_db
    from core import paths
    root = Path(paths.UPLOADS_ROOT)
    before_files = sorted(str(p) for p in root.rglob("*")) if root.exists() else []

    def counts():
        c = get_db()
        try:
            return tuple(c.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in ("ui_definitions", "audit_log", "notifications"))
        finally:
            c.close()
    c0 = counts()
    for _ in range(3):
        assert _sim(client, hdr, B(S(subfolder="驗收單"))).status_code == 200
    assert counts()[0] == c0[0]                                  # 定義表不動（稽核只可能多登入相關，不得有 simulate 寫入）
    assert counts()[2] == c0[2]
    after = sorted(str(p) for p in root.rglob("*")) if root.exists() else []
    assert after == before_files                                 # 沒有任何檔案／資料夾被建立


# ── 6. 讀取提供者 SLOT_AWARE ─────────────────────────────────────────────────
class _Conn:
    def execute(self, sql, params=()):
        class _R:
            def fetchone(_s):
                return {"quote_no": "Q-1"} if "completion_notes" in sql and params and params[0] == "N-1" else None
        return _R()


def test_case_provider_reads_three_segment_completion_paths_with_the_same_rule(monkeypatch):
    from modules.case import attachments as CA
    prov = CA._CasePathAccess                                                      # noqa: SLF001
    assert prov.SLOT_AWARE is True
    seen = []
    monkeypatch.setattr(CA, "case_documents_readable", lambda conn, q, user: seen.append(q) or user.get("ok") is True)
    c = _Conn()
    assert prov.readable(c, "completion_notes", ["N-1", "x.pdf"], {"ok": True}) is True                            # 兩段照舊
    assert prov.readable(c, "completion_notes", ["驗收單", "N-1", "x.pdf"], {"ok": True}) is True                  # 三段＝子夾/單號/檔
    assert prov.readable(c, "completion_notes", ["驗收單", "N-1", "x.pdf"], {"ok": False}) is False               # 同一條讀取規則
    assert prov.readable(c, "completion_notes", ["驗收單", "N-X", "x.pdf"], {"ok": True}) is False                 # 單據不存在
    assert prov.readable(c, "completion_notes", ["a", "b", "c", "d"], {"ok": True}) is False                       # 四段不收
    assert prov.readable(c, "quotations", ["sub", "Q-1", "x.pdf"], {"ok": True}) is False                          # 其他資料夾不因此放寬
    assert seen and set(seen) == {"Q-1"}


# ── 7. 上傳端的政策行為 ──────────────────────────────────────────────────────
def test_policy_upload_refuses_double_extensions_but_none_path_is_unchanged(tmp_path, monkeypatch):
    import asyncio
    import io
    from fastapi import HTTPException
    from starlette.datastructures import Headers, UploadFile
    pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF\n"
    monkeypatch.setattr(U, "UPLOADS_ROOT", str(tmp_path))

    def up(n):
        return UploadFile(io.BytesIO(pdf), filename=n, headers=Headers({"content-type": "application/pdf"}))
    pol = SS.builtin_policy("completion_notes")
    with pytest.raises(HTTPException) as e:
        asyncio.run(U.save_document_files("completion_notes", "N-1", [up("a.exe.pdf")], "t", policy=pol))
    assert e.value.status_code == 400 and "雙重副檔名" in e.value.detail
    assert asyncio.run(U.save_document_files("completion_notes", "N-2", [up("a.exe.pdf")], "t"))                  # 舊路徑（policy=None）行為不變
    tiny = SS.SlotPolicy(code="completion_notes", folder="completion_notes", accept=frozenset({".pdf"}), max_file_bytes=10, builtin=False)
    with pytest.raises(HTTPException) as e:
        asyncio.run(U.save_document_files("completion_notes", "N-3", [up("a.pdf")], "t", policy=tiny))
    assert e.value.status_code == 400 and "單檔上限" in e.value.detail


# ── 04 靜態審查後補強 ────────────────────────────────────────────────────────
def test_flag_needs_governance_too_and_unreadable_means_off(monkeypatch):
    from helpers import settings_registry as R
    vals = {("builder_slots", "enabled"): 1, ("builder_governance", "enabled"): 1}
    monkeypatch.setattr(R, "get", lambda g, f, conn=None: vals[(g, f)])
    assert SS.enabled() is True
    vals[("builder_governance", "enabled")] = 0
    assert SS.enabled() is False                                              # 沒有治理層＝放寬沒有核准、發布沒有預覽把關 ⇒ 不開
    vals[("builder_governance", "enabled")], vals[("builder_slots", "enabled")] = 1, 0
    assert SS.enabled() is False
    monkeypatch.setattr(R, "get", lambda g, f, conn=None: (_ for _ in ()).throw(RuntimeError("boom")))
    assert SS.enabled() is False                                              # 讀不到 ⇒ 關


def test_kind_is_registered_only_while_the_flag_is_on(client, hdr, monkeypatch):
    kinds = lambda: [k["kind"] for k in client.get("/api/definition-kinds", headers=hdr).json()["kinds"]]      # noqa: E731
    before = kinds()
    assert "attachment_slot" not in before                                    # OFF：種類清單與先前相同
    monkeypatch.setattr(SS, "enabled", lambda conn=None: True)
    assert AS.enabled() is True and "attachment_slot" in kinds()              # ON：登記
    monkeypatch.setattr(SS, "enabled", lambda conn=None: False)
    assert AS.enabled() is False and kinds() == before                        # 關回去：撤掉


def test_slots_cannot_pick_ole_or_heic_but_builtin_policies_keep_them(on):
    for ext in (".doc", ".xls", ".heic", ".heif"):
        assert "不在系統允許範圍" in _msgs(B(S(accept=[ext]))), ext
    assert ".doc" not in SS.SLOT_EXTS and {".docx", ".xlsx"} <= SS.SLOT_EXTS and SS.SLOT_EXTS < SS.HARD_EXTS
    assert {".doc", ".xls"} <= set(SS.builtin_policy("voucher_attachments").accept)                      # 傳票附件內建不變
    assert {".heic", ".heif"} <= set(SS.builtin_policy("case_extra_expense").accept)
    pol = AS._policy_of("completion_note", S(accept=[".pdf"]))                                        # noqa: SLF001
    assert set(pol.accept) == {".pdf"}
    assert ".doc" not in set(AS._policy_of("completion_note", dict(S(), accept=[".pdf", ".doc"])).accept)  # noqa: SLF001  即使硬塞也被扣掉


def test_labels_reject_bidi_and_zero_width_characters(on):
    for bad in ("現場‮照片", "現場​照片", "現場﻿照片", "現場⁦照片"):
        assert "不可含" in _msgs(B(S(label=bad))), repr(bad)


def test_dangerous_extension_list_covers_macro_and_script_types():
    assert {".docm", ".xlsm", ".jar", ".msi", ".hta", ".wsf", ".sh", ".reg", ".exe", ".ps1"} <= SS.DANGEROUS_EXTS


@pytest.mark.upload_magic
def test_simulate_treats_a_leading_dot_name_as_having_no_extension(client, hdr, on):
    r = _sim(client, hdr, B(S(accept=[".pdf"])), filename=".pdf").json()
    assert r["ok"] is False and any("沒有副檔名" in x for x in r["reasons"])


def test_completion_note_slot_paths_are_reachable_through_the_attachment_catalog():
    """附件目錄的『路徑必須屬於這張單據』檢查（W3）要認得 BP-4 的 <子夾>/<單號>/<檔名>；其他形狀仍 fail closed。"""
    from helpers.uploads import upload_path_key
    from modules.case import attachments as CA
    e = lambda p: {"path": p}                                                                          # noqa: E731
    assert upload_path_key(e("completion_notes/N-1/a.pdf"), "completion_notes") == "N-1"                   # 既有形狀不變
    assert upload_path_key(e("completion_notes/驗收單/N-1/a.pdf"), "completion_notes") is None            # 預設深度仍是 2
    assert upload_path_key(e("completion_notes/驗收單/N-1/a.pdf"), "completion_notes", depth=3, key_index=1) == "N-1"
    bound = lambda p, doc: CA._path_bound_to_doc(None, "completion_note", doc, e(p))                    # noqa: E731,SLF001
    assert bound("completion_notes/N-1/a.pdf", "N-1") is True
    assert bound("completion_notes/驗收單/N-1/a.pdf", "N-1") is True
    assert bound("completion_notes/驗收單/N-2/a.pdf", "N-1") is False                                    # 別張單據
    assert bound("completion_notes/a/b/N-1/c.pdf", "N-1") is False                                       # 四段不收
    assert bound("quotations/驗收單/N-1/a.pdf", "N-1") is False                                          # 別的資料夾
    assert bound("completion_notes/../N-1/a.pdf", "N-1") is False                                        # 穿越
    # 其他來源類型沒有因此放寬：報價單回簽的三段路徑仍不屬於單據
    assert CA._path_bound_to_doc(None, "quotation_signed", "N-1", e("quotations/驗收單/N-1/a.pdf")) is False  # noqa: SLF001
