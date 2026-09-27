# -*- coding: utf-8 -*-
"""品牌圖檔與公司名稱設定（2026-09-27 H10；使用者：「公司名稱、公司LOGO這些都要能在設定中上傳跟修改」）。

契約（helpers/branding.py 單位卡）：
- 上傳 ⇒ 立即生效（讀取端點與 /api/system/branding 的網址都換成新版本）；恢復預設 ⇒ 回靜態預設檔。
- 只收 PNG／JPEG／WebP，以檔頭判斷；SVG 與偽裝副檔名（GIF／BMP／文字檔改名成 .png）一律拒收，拒收時什麼都不寫。
- 限 2 MB、單邊 4096 像素；存檔前重新編碼成 PNG、去掉 metadata。
- 只有 superadmin；展示帳號也不行；寫 audit（settings.branding.update）。
觀測點：讀取端點回的位元組、存放目錄的實際檔案、audit_log 列、company_identity 解析結果——不是回應裡的旗標。
突變（送測時手動做，結果寫進 commit）：`encode_upload` 拿掉 `fmt not in ALLOWED_FORMATS` 那一段 ⇒
`test_disguised_formats_are_rejected[gif]`／`[bmp]` 要紅（Pillow 本身解得開 GIF／BMP，拒收只靠那一段）。
"""
import io
import json
import os

import pytest
from PIL import Image, PngImagePlugin

from core import paths as _paths


def _png(w=300, h=100, color=(200, 30, 30, 255), text=None):
    img = Image.new("RGBA", (w, h), color)
    buf = io.BytesIO()
    info = None
    if text:
        info = PngImagePlugin.PngInfo()
        info.add_text("Description", text)
    img.save(buf, format="PNG", pnginfo=info)
    return buf.getvalue()


def _img(fmt, w=40, h=20, **kw):
    img = Image.new("RGB", (w, h), (10, 120, 200))
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kw)
    return buf.getvalue()


SVG = (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
       b'<script>alert(1)</script><rect width="10" height="10"/></svg>')


def _hdr(client, make_user, username, role="superadmin"):
    u = make_user(username=username, role=role)
    r = client.post("/api/auth/login", json={"username": u[0], "password": u[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _put(client, hdr, kind, data, name="logo.png", ctype="image/png"):
    return client.put("/api/settings/branding/" + kind, headers=hdr, files={"file": (name, data, ctype)})


def _stored(kind):
    import helpers.branding as b
    path = os.path.join(b.UPLOADS_ROOT, "branding", kind + ".png")
    return open(path, "rb").read() if os.path.isfile(path) else None


def _default_bytes(kind):
    import helpers.branding as b
    return open(os.path.join(_paths.FRONTEND_DIR, "static", b.KINDS[kind]["default"]), "rb").read()


# ── 上傳、生效、恢復預設 ────────────────────────────────────────────────────

def test_upload_takes_effect_then_reset_restores_the_default(client, make_user):
    hdr = _hdr(client, make_user, "br_sa")
    assert client.get("/api/system/branding/logo").content == _default_bytes("logo"), "沒上傳時要回預設靜態檔"

    r = _put(client, hdr, "logo", _png(300, 100))
    assert r.status_code == 200, r.text
    v = r.json()["v"]
    served = client.get("/api/system/branding/logo")
    assert served.status_code == 200 and served.headers["content-type"] == "image/png"
    assert served.content == _stored("logo"), "讀取端點回的要是存放目錄裡那一張"
    assert Image.open(io.BytesIO(served.content)).size == (300, 100)
    # 公開的品牌資訊（登入頁用）帶新版本
    assert client.get("/api/system/branding").json()["assets"]["logo"] == "/api/system/branding/logo?v=" + v

    r = client.delete("/api/settings/branding/logo", headers=hdr)
    assert r.status_code == 200, r.text
    assert _stored("logo") is None, "恢復預設要刪掉上傳的檔"
    assert client.get("/api/system/branding/logo").content == _default_bytes("logo")
    assert client.get("/api/system/branding").json()["assets"]["logo"].endswith("?v=default")


def test_cache_headers_and_etag(client, make_user):
    hdr = _hdr(client, make_user, "br_cache")
    v = _put(client, hdr, "logo-dark", _png(120, 40)).json()["v"]
    versioned = client.get("/api/system/branding/logo-dark?v=" + v)
    assert "immutable" in versioned.headers["cache-control"]
    plain = client.get("/api/system/branding/logo-dark")
    assert plain.headers["cache-control"] == "no-cache", "不帶版本的網址每次要重新驗證（換圖後下一次載入就是新的）"
    assert client.get("/api/system/branding/logo-dark?v=old").headers["cache-control"] == "no-cache"
    again = client.get("/api/system/branding/logo-dark", headers={"If-None-Match": plain.headers["etag"]})
    assert again.status_code == 304
    # 換圖後舊 ETag 不再相符
    _put(client, hdr, "logo-dark", _png(130, 40, color=(0, 0, 0, 255)))
    assert client.get("/api/system/branding/logo-dark",
                      headers={"If-None-Match": plain.headers["etag"]}).status_code == 200


def test_favicon_is_reencoded_to_256_square(client, make_user):
    hdr = _hdr(client, make_user, "br_fav")
    assert _put(client, hdr, "favicon", _png(600, 300)).status_code == 200
    out = Image.open(io.BytesIO(client.get("/api/system/branding/favicon").content))
    assert out.format == "PNG" and out.size == (256, 256)


def test_public_read_needs_no_login_and_unknown_kind_is_404(client):
    assert client.get("/api/system/branding/favicon").status_code == 200
    assert client.get("/api/system/branding/nope").status_code == 404


# ── 拒收 ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,ctype", [("logo.svg", "image/svg+xml"), ("logo.png", "image/png")])
def test_svg_is_rejected_whatever_the_name(client, make_user, name, ctype):
    hdr = _hdr(client, make_user, "br_svg")
    r = _put(client, hdr, "logo", SVG, name=name, ctype=ctype)
    assert r.status_code == 400, r.text
    assert _stored("logo") is None, "拒收時不可以留下任何檔"
    assert client.get("/api/system/branding/logo").content == _default_bytes("logo")


@pytest.mark.parametrize("fmt", ["gif", "bmp", "text"])
def test_disguised_formats_are_rejected(client, make_user, fmt):
    """副檔名與 Content-Type 都說是 PNG，內容是別的 ⇒ 拒收。GIF／BMP 是 Pillow 解得開的格式（突變題的觀測點）。"""
    hdr = _hdr(client, make_user, "br_fake_" + fmt)
    data = {"gif": _img("GIF"), "bmp": _img("BMP"), "text": b"hello, not an image\n" * 10}[fmt]
    r = _put(client, hdr, "logo", data, name="logo.png", ctype="image/png")
    assert r.status_code == 400, r.text
    assert _stored("logo") is None


def test_real_format_decides_not_the_extension(client, make_user):
    """反向：內容是 JPEG、檔名寫 .svg ⇒ 照收（判斷看內容），存成 PNG。"""
    hdr = _hdr(client, make_user, "br_ext")
    r = _put(client, hdr, "logo", _img("JPEG", 50, 30), name="x.svg", ctype="image/svg+xml")
    assert r.status_code == 200, r.text
    assert Image.open(io.BytesIO(_stored("logo"))).format == "PNG"
    assert _put(client, hdr, "logo", _img("WEBP", 50, 30), name="x.gif", ctype="image/gif").status_code == 200


def test_size_and_pixel_limits(client, make_user):
    import helpers.branding as b
    hdr = _hdr(client, make_user, "br_big")
    too_big = _png(10, 10) + b"\0" * b.MAX_UPLOAD_BYTES
    assert _put(client, hdr, "logo", too_big).status_code == 400
    assert _put(client, hdr, "logo", _png(b.MAX_SIDE + 1, 2)).status_code == 400
    assert _stored("logo") is None
    assert _put(client, hdr, "logo", _png(b.MAX_SIDE, 2)).status_code == 200, "上限本身要收"


def test_metadata_is_stripped(client, make_user):
    hdr = _hdr(client, make_user, "br_meta")
    assert _put(client, hdr, "logo", _png(60, 20, text="SECRET-PNG-TEXT")).status_code == 200
    out = _stored("logo")
    assert b"SECRET-PNG-TEXT" not in out
    exif = Image.Exif()
    exif[0x010E] = "SECRET-EXIF-DESC"            # ImageDescription
    jpg = _img("JPEG", 60, 20, exif=exif.tobytes())
    assert b"SECRET-EXIF-DESC" in jpg            # 正對照：輸入真的帶著 metadata
    assert _put(client, hdr, "logo-dark", jpg, name="a.jpg", ctype="image/jpeg").status_code == 200
    out = _stored("logo-dark")
    assert b"SECRET-EXIF-DESC" not in out and b"Exif" not in out
    assert not Image.open(io.BytesIO(out)).info.get("exif")


# ── 權限與稽核 ──────────────────────────────────────────────────────────────

def test_only_superadmin_can_change_branding(client, make_user):
    admin = _hdr(client, make_user, "br_admin", role="admin")
    assert _put(client, admin, "logo", _png()).status_code == 403
    assert client.delete("/api/settings/branding/logo", headers=admin).status_code == 403
    assert client.get("/api/settings/branding", headers=admin).status_code == 403
    assert client.put("/api/settings/branding/logo", files={"file": ("a.png", _png(), "image/png")}).status_code == 401
    assert _stored("logo") is None
    sa = _hdr(client, make_user, "br_sa2")
    assert client.get("/api/settings/branding", headers=sa).status_code == 200


def test_demo_session_cannot_change_branding(client, make_user, monkeypatch):
    import db
    hdr = _hdr(client, make_user, "br_demo")
    monkeypatch.setattr(db, "is_demo_mode", lambda: True)
    assert _put(client, hdr, "logo", _png()).status_code == 403
    assert _stored("logo") is None


def test_upload_and_reset_are_audited(client, make_user):
    hdr = _hdr(client, make_user, "br_audit")
    v = _put(client, hdr, "favicon", _png(64, 64)).json()["v"]
    size = len(_stored("favicon"))
    client.delete("/api/settings/branding/favicon", headers=hdr)
    import db
    conn = db.get_db()
    try:
        rows = conn.execute("SELECT username, detail FROM audit_log "
                            "WHERE action='settings.branding.update' ORDER BY id").fetchall()
    finally:
        conn.close()
    details = [(r["username"], json.loads(r["detail"])) for r in rows]
    assert details == [("br_audit", {"kind": "favicon", "op": "upload", "v": v, "bytes": size}),
                       ("br_audit", {"kind": "favicon", "op": "reset", "hadCustom": True})], details


# ── 公司名稱（中／英）、電話、email 在設定頁可以改，且真的生效 ────────────────────

def test_profile_name_en_phone_email_are_saved_and_resolved(client, make_user):
    from helpers.company_identity import location_identity
    hdr = _hdr(client, make_user, "br_prof")
    r = client.put("/api/settings/company-profile", headers=hdr, json={
        "name": "範例科技股份有限公司", "company_name_en": "Example Tech", "phone": "02-1234-5678",
        "email": "svc@example.com", "tax_id": "12345678"})
    assert r.status_code == 200, r.text
    ident = location_identity()
    assert (ident["company_name"], ident["company_name_en"], ident["phone"], ident["email"], ident["tax_id"]) == (
        "範例科技股份有限公司", "Example Tech", "02-1234-5678", "svc@example.com", "12345678")
    b = client.get("/api/system/branding").json()
    assert (b["companyName"], b["companyNameEn"]) == ("範例科技股份有限公司", "Example Tech")


def test_editing_name_also_updates_a_backfilled_alias(client, make_user):
    """升級回填過 `company_name`（解析順序在 `name` 前面）的安裝：設定頁改 `name` 要真的生效，不是被舊別名蓋住。"""
    from helpers.settings import _set_setting
    from helpers.company_identity import location_identity
    _set_setting("company_profile", {"name": "舊名", "company_name": "舊名", "companyNameEn": "Old En"})
    hdr = _hdr(client, make_user, "br_alias")
    assert client.put("/api/settings/company-profile", headers=hdr,
                      json={"name": "新名", "company_name_en": "New En"}).status_code == 200
    ident = location_identity()
    assert (ident["company_name"], ident["company_name_en"]) == ("新名", "New En")
    # 反向：沒有送 name 的更新不動別名
    assert client.put("/api/settings/company-profile", headers=hdr, json={"phone": "1"}).status_code == 200
    assert location_identity()["company_name"] == "新名"
