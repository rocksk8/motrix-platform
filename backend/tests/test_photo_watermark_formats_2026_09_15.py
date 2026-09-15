"""浮水印處理不可以把使用者的圖毀掉（2026-09-15）。

使用者回報「圖檔上傳後變成這樣」——傳上去的是 `logo-white.png`（白色字＋透明底），
存回來只剩一顆彩色圓環，中間的字整個不見。

根因在 `photos.py::_process_project_photo()`：它一律 `convert('RGB')`（＝把 alpha
直接丟掉、露出底下的 RGB 值）再一律存成 JPEG。透明處底下的值是白的，白字落在白底
上就消失了。順帶還產生「副檔名 .png、內容是 JPEG」的檔案——存檔端
（`helpers/uploads.py`、`routers/system.py`）沿用的是上傳時的副檔名。

現在的規則是**輸出跟著來源格式走**：PNG 進 PNG 出（alpha 保留），其餘不變。

觀測點刻意放在**像素本身**（不透明且接近白的取樣數），不是檔案格式字串——
格式對了但內容被壓平，一樣是把使用者的圖毀掉。
"""
import io

import pytest

pytest.importorskip("PIL")
from PIL import Image, ImageDraw

from photos import _process_project_photo


def _white_on_transparent_png(w=600, h=200) -> bytes:
    """模擬去背 logo：透明底 ＋ 不透明白色圖形。

    刻意讓透明處底下的 RGB 也是白的——這正是真實去背 PNG 的常見樣子，也是
    「丟掉 alpha 就整個消失」的必要條件。用純透明黑底的圖測不出這個 bug。
    """
    img = Image.new('RGBA', (w, h), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([w // 3, h // 4, w * 2 // 3, h * 3 // 4], fill=(255, 255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _opaque_near_white(img: Image.Image, box) -> int:
    px = img.convert('RGBA').load()
    x0, y0, x1, y1 = box
    return sum(1 for y in range(y0, y1, 2) for x in range(x0, x1, 2)
               if px[x, y][3] > 128 and all(c > 200 for c in px[x, y][:3]))


def test_transparent_png_keeps_its_content():
    raw = _white_on_transparent_png()
    before = Image.open(io.BytesIO(raw))
    box = (200, 50, 400, 150)
    n_before = _opaque_near_white(before, box)
    assert n_before > 0, "測試素材本身就沒有白色圖形，這題測不到東西"

    out, _, watermark = _process_project_photo(raw, "測試人員")
    after = Image.open(io.BytesIO(out))

    assert after.format == "PNG", f"PNG 進來卻吐出 {after.format}，副檔名會對不上內容"
    assert after.mode == "RGBA", "透明度被壓平了"
    assert _opaque_near_white(after, box) == n_before, "白色圖形在處理後消失或被改掉"
    assert watermark, "浮水印還是要壓上去——保留透明度不代表放棄浮水印"


def test_jpeg_source_is_untouched_by_the_png_change():
    """手機拍的照片這條路行為必須逐字不變（JPEG 進 JPEG 出）。

    這題是回歸基準：少了它，「PNG 保留 alpha」可以靠「全部都存成 PNG」矇混過關，
    而那會讓每張現場照片體積暴增。
    """
    buf = io.BytesIO()
    Image.new('RGB', (400, 300), (120, 130, 140)).save(buf, format='JPEG')
    out, _, watermark = _process_project_photo(buf.getvalue(), "測試人員")
    result = Image.open(io.BytesIO(out))
    assert result.format == "JPEG"
    assert result.mode == "RGB"
    assert watermark


def test_stored_attachment_extension_matches_its_real_content(client, make_user):
    """存下來的檔案，副檔名要跟真實內容一致。

    修復前：上傳 a.png → 磁碟上是 `<uuid>.png`、內容卻是 JPEG。使用者把檔案下載
    回去用別的工具開會踩到，備份與郵件附件也一樣。
    """
    import json
    import os

    import db
    import helpers.uploads as uploads_helper

    u, p = make_user(username="fmt_a", role="superadmin")
    token = client.post("/api/auth/login",
                        json={"username": u, "password": p}).json()["token"]
    H = {"Authorization": "Bearer " + token}
    conn = db.get_db()
    uid = conn.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()["id"]
    conn.close()

    case_id = client.post("/api/dev-cases", headers=H,
                          json={"case_name": "格式一致性"}).json()["id"]
    r = client.post(f"/api/dev-cases/{case_id}/logs", headers=H,
                    data={"log_date": "2026-09-15", "log_by": uid, "content": "logo"},
                    files=[("files", ("logo.png", _white_on_transparent_png(), "image/png"))])
    assert r.status_code == 201, r.text

    meta = r.json()["files"][0]
    assert meta["path"].endswith(".png")
    on_disk = os.path.join(uploads_helper.UPLOADS_ROOT, meta["path"])
    assert Image.open(on_disk).format == "PNG", "副檔名 .png，內容卻不是 PNG"
