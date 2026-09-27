# -*- coding: utf-8 -*-
"""品牌圖檔（主 LOGO／深色底 LOGO／favicon）：上傳驗證、存放、讀取時回預設。

[單位] helper:branding        [層] L1        [穩定度] 契約（改介面照 §C-7 升版）
[公開介面] KINDS, ALLOWED_FORMATS, MAX_UPLOAD_BYTES, MAX_SIDE, MAX_PIXELS, SETTING_KEY, UPLOADS_ROOT, AUDIT_ACTION,
  BrandingRejected,
  detect_format, encode_upload, asset_file, asset_version, asset_urls, save_asset, reset_asset
[不變式] 只收 PNG／JPEG／WebP，格式由檔頭判斷（副檔名與 Content-Type 一律不看）；SVG 一律拒收；
  存檔前重新編碼成 PNG、去掉 metadata；存放位置固定為 uploads/branding/<kind>.png，不用使用者給的檔名；
  沒有上傳（或已恢復預設）⇒ 讀取回 frontend/static 的預設檔
[契約題] tests/test_branding_2026_09_27.py
[注意] 版本號＝重新編碼後內容的 sha256 前 12 碼，存在設定 `branding_assets`；帶版本的網址可以長效快取
"""
import hashlib
import io
import os
from datetime import datetime

from core import paths as _paths
from helpers.settings import _get_setting, _set_setting

#: 種類 ⇒ 預設靜態檔（frontend/static 下）、名稱、重新編碼後的尺寸規則。
#: `fit`：等比縮到這個方框內（不放大）；`square`：再置中補透明邊成正方形（favicon）。
KINDS = {
    "logo": {"label": "主 LOGO", "default": "logo.png", "fit": 1024, "square": False},
    "logo-dark": {"label": "深色底 LOGO", "default": "logo-white.png", "fit": 1024, "square": False},
    "favicon": {"label": "網站圖示（favicon）", "default": "favicon.png", "fit": 256, "square": True},
}

#: 只收這三種（Pillow 的 format 名稱）。SVG 可以內嵌指令碼，不收。
ALLOWED_FORMATS = ("PNG", "JPEG", "WEBP")
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
#: 單邊上限與總像素上限（解碼前就用檔頭的尺寸判斷，避免解壓縮炸彈）。
MAX_SIDE = 4096
MAX_PIXELS = MAX_SIDE * MAX_SIDE

SETTING_KEY = "branding_assets"
#: 存放位置的根目錄（模組層級名字，測試 monkeypatch 它；conftest 已導到暫存目錄）
UPLOADS_ROOT = _paths.UPLOADS_ROOT
AUDIT_ACTION = "settings.branding.update"


class BrandingRejected(ValueError):
    """上傳的檔案不收；訊息給使用者看。"""


def detect_format(data: bytes):
    """依檔頭判斷真實格式 ⇒ 'PNG'／'JPEG'／'WEBP'／'GIF'／'BMP'／'TIFF'／'ICO'／'SVG'；認不得 ⇒ None。

    認得的比收的多：判斷（這是什麼）與決定（收不收，`ALLOWED_FORMATS`）分開，
    決定只有 `encode_upload` 裡那一行——拿掉它，GIF／BMP 就會被當成自己的格式解碼並收下（突變題的觀測點）。
    """
    head = bytes(data[:16])
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if head.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "WEBP"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "GIF"
    if head[:2] == b"BM":
        return "BMP"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "TIFF"
    if head[:4] == b"\x00\x00\x01\x00":
        return "ICO"
    if bytes(data[:512]).lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"<"):
        return "SVG"                              # XML／SVG／HTML：可以內嵌指令碼
    return None


def _check_kind(kind: str) -> dict:
    spec = KINDS.get(kind)
    if spec is None:
        raise BrandingRejected("不支援的圖檔種類：%s" % kind)
    return spec


def encode_upload(kind: str, data: bytes) -> bytes:
    """驗證並重新編碼 ⇒ PNG bytes（不含任何 metadata）。不收 ⇒ `BrandingRejected`。"""
    from PIL import Image, ImageOps

    spec = _check_kind(kind)
    if not data:
        raise BrandingRejected("檔案是空的。")
    if len(data) > MAX_UPLOAD_BYTES:
        raise BrandingRejected("檔案超過 %d MB。" % (MAX_UPLOAD_BYTES // (1024 * 1024)))
    fmt = detect_format(data)
    if fmt not in ALLOWED_FORMATS:
        raise BrandingRejected("只接受 PNG、JPG、WebP 圖檔（不接受 SVG；以檔案內容判斷，不看副檔名）。")
    if fmt is None:
        raise BrandingRejected("無法辨識的檔案格式。")
    try:
        # formats=[fmt]：只讓 Pillow 用檔頭判斷出的那一種解碼器，不讓它自己改猜別的格式
        img = Image.open(io.BytesIO(data), formats=[fmt])
        w, h = img.size
        if w < 1 or h < 1 or w > MAX_SIDE or h > MAX_SIDE or w * h > MAX_PIXELS:
            raise BrandingRejected("圖片尺寸超過上限（單邊最多 %d 像素）。" % MAX_SIDE)
        img.load()
    except BrandingRejected:
        raise
    except Exception:
        raise BrandingRejected("圖檔無法讀取（檔案損毀或格式不符）。")

    try:
        img = ImageOps.exif_transpose(img)          # 先套用拍攝方向，再丟掉 EXIF
        has_alpha = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
        img = img.convert("RGBA" if has_alpha or spec["square"] else "RGB")
        img.thumbnail((spec["fit"], spec["fit"]), Image.LANCZOS)
        if spec["square"]:
            canvas = Image.new("RGBA", (spec["fit"], spec["fit"]), (0, 0, 0, 0))
            canvas.paste(img, ((spec["fit"] - img.width) // 2, (spec["fit"] - img.height) // 2))
            img = canvas
        # 新建一張只含像素的圖再存：info／exif／icc／文字區塊一律不帶過去
        clean = Image.frombytes(img.mode, img.size, img.tobytes())
        buf = io.BytesIO()
        clean.save(buf, format="PNG", optimize=True)
    except Exception:
        raise BrandingRejected("圖檔無法處理（色彩模式不支援或檔案損毀）。")
    return buf.getvalue()


def _branding_dir() -> str:
    return os.path.join(UPLOADS_ROOT, "branding")


def _uploaded_path(kind: str) -> str:
    _check_kind(kind)
    return os.path.join(_branding_dir(), kind + ".png")


def _state() -> dict:
    value = _get_setting(SETTING_KEY, {}) or {}
    return value if isinstance(value, dict) else {}


def asset_version(kind: str):
    """已上傳 ⇒ 版本字串；沒有上傳（或設定與檔案不一致）⇒ None。"""
    entry = _state().get(kind)
    if not isinstance(entry, dict) or not entry.get("v"):
        return None
    return str(entry["v"]) if os.path.isfile(_uploaded_path(kind)) else None


def asset_file(kind: str):
    """⇒ (檔案路徑, 版本)。沒有上傳 ⇒ (預設靜態檔, "default")。"""
    spec = _check_kind(kind)
    v = asset_version(kind)
    if v:
        return _uploaded_path(kind), v
    return os.path.join(_paths.FRONTEND_DIR, "static", spec["default"]), "default"


def asset_urls() -> dict:
    """⇒ {kind: "/api/system/branding/<kind>?v=<版本>"}（前端直接放進 src／href）。"""
    out = {}
    for kind in KINDS:
        v = asset_version(kind) or "default"
        out[kind] = "/api/system/branding/%s?v=%s" % (kind, v)
    return out


def save_asset(kind: str, data: bytes, by: str = "") -> dict:
    """驗證＋重新編碼＋寫入固定路徑＋記版本 ⇒ {"kind", "v", "bytes"}。不收 ⇒ `BrandingRejected`。"""
    png = encode_upload(kind, data)
    version = hashlib.sha256(png).hexdigest()[:12]
    os.makedirs(_branding_dir(), exist_ok=True)
    target = _uploaded_path(kind)
    tmp = target + ".tmp"
    with open(tmp, "wb") as f:
        f.write(png)
    os.replace(tmp, target)
    state = _state()
    state[kind] = {"v": version, "updatedAt": datetime.now().isoformat(timespec="seconds"), "by": by or ""}
    _set_setting(SETTING_KEY, state)
    return {"kind": kind, "v": version, "bytes": len(png)}


def reset_asset(kind: str) -> bool:
    """恢復預設：先拿掉版本記錄（讀取端立即回預設），再刪檔。⇒ 原本是否有上傳。"""
    _check_kind(kind)
    state = _state()
    had = state.pop(kind, None) is not None
    _set_setting(SETTING_KEY, state)
    try:
        os.remove(_uploaded_path(kind))
        had = True
    except FileNotFoundError:
        pass
    return had
