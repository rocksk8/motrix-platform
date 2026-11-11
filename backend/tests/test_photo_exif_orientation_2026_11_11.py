# -*- coding: utf-8 -*-
"""手機直拍的照片經浮水印處理後不可以橫躺（2026-11-11）。

hichan-9 研究手機外勤時重現：Orientation=6、顯示 300x400 的原圖，經 `photos._process_project_photo` 後變成 400x300。
根因：處理流程 `convert()`＋重存 JPEG，EXIF 沒帶過去（Orientation 標記消失），像素卻沒被轉正 ⇒ 直書照片存起來橫躺。
這條路徑是**所有**上傳流程共用的（案件更新、work-log、CRM、`helpers/uploads.py`、`routers/system.py`）。
修法：讀完 GPS 之後 `ImageOps.exif_transpose` 把方向烘進像素，再貼浮水印（浮水印貼在轉正後的畫面底部）。

觀測點：**像素位置**，不是只看尺寸。尺寸對但內容被鏡射／轉錯方向也是壞的（Orientation 2／4／5／7 是鏡射）。
期望值取自 EXIF 規格表（TIFF/EXIF 6.0「Orientation」：第 0 列／第 0 欄在顯示畫面的哪一側），不是從 Pillow 的對照表推出來（否則等於拿被測對象自己驗自己）：
  存下來的像素 (0,0)（左上角）在**顯示**畫面的位置：
    1 左上　2 右上　3 右下　4 左下　5 左上　6 右上　7 右下　8 左下
  顯示畫面的寬高：1～4 與存的相同；5～8 對調。
"""
import io

import pytest

pytest.importorskip("PIL")
from PIL import Image

from photos import _process_project_photo

W, H = 1200, 1600          # 存下來的像素尺寸（夠大：浮水印條只佔底部約 3.5%，標記塊離底邊 12% 以上不會被蓋到）

# orientation -> 存的 (0,0) 角落在顯示畫面的哪個角（EXIF 規格表）
TOP_LEFT_LANDS = {1: "TL", 2: "TR", 3: "BR", 4: "BL", 5: "TL", 6: "TR", 7: "BR", 8: "BL"}


def _stored_jpeg(orientation, w=W, h=H):
    """存下來的像素：左上角（0,0）一塊紅色，其餘白；EXIF 帶 Orientation。"""
    img = Image.new("RGB", (w, h), (255, 255, 255))
    for x in range(int(w * 0.25)):
        for y in range(int(h * 0.25)):
            img.putpixel((x, y), (230, 0, 0))
    exif = Image.Exif()
    exif[0x0112] = orientation
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95, exif=exif)
    return buf.getvalue()


def _corner_is_red(img, corner):
    w, h = img.size
    cx = int(w * 0.125) if corner[1] == "L" else int(w * 0.875)
    cy = int(h * 0.125) if corner[0] == "T" else int(h * 0.875)
    r, g, b = img.convert("RGB").getpixel((cx, cy))
    return r > 180 and g < 90 and b < 90


@pytest.mark.parametrize("orientation", [1, 2, 3, 4, 5, 6, 7, 8])
def test_every_exif_orientation_is_baked_into_the_pixels(orientation):
    out, _gps, _wm = _process_project_photo(_stored_jpeg(orientation), "測試人")
    img = Image.open(io.BytesIO(out))
    assert img.format == "JPEG"
    swapped = orientation >= 5
    assert img.size == ((H, W) if swapped else (W, H)), (orientation, img.size)
    land = TOP_LEFT_LANDS[orientation]
    assert _corner_is_red(img, land), "Orientation=%d：存的左上角紅塊應在顯示畫面的 %s" % (orientation, land)
    for other in ("TL", "TR", "BL", "BR"):
        if other != land:
            assert not _corner_is_red(img, other), "Orientation=%d：%s 不該有紅塊（鏡射或轉錯方向）" % (orientation, other)


def test_the_reported_case_portrait_phone_photo_stays_portrait():
    """hichan-9 的重現：Orientation=6，存 400x300（顯示 300x400）→ 處理後不可以變成橫的。"""
    out, _g, _w = _process_project_photo(_stored_jpeg(6, 400, 300), "測試人")
    assert Image.open(io.BytesIO(out)).size == (300, 400)


def test_landscape_photo_without_orientation_is_unchanged_in_size_and_orientation():
    img = Image.new("RGB", (400, 300), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")                                   # 沒有 EXIF
    out, _g, _w = _process_project_photo(buf.getvalue(), "測試人")
    assert Image.open(io.BytesIO(out)).size == (400, 300)


def test_gps_is_still_extracted_from_a_rotated_photo_and_watermark_is_on_the_upright_bottom():
    img = Image.new("RGB", (1200, 900), (255, 255, 255))           # 存成橫的、Orientation=6 → 顯示 900x1200
    exif = Image.Exif()
    exif[0x0112] = 6
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (25.0, 3.0, 0.0)
    gps[3], gps[4] = "E", (121.0, 30.0, 0.0)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95, exif=exif)
    out, gps_str, wm = _process_project_photo(buf.getvalue(), "測試人")
    assert gps_str == "25.05000,121.50000", gps_str                # GPS 在轉正之前就讀完了，不受影響
    assert "GPS 25.05000,121.50000" in wm
    up = Image.open(io.BytesIO(out)).convert("RGB")
    assert up.size == (900, 1200)
    # 浮水印底色是白圖上的黑底（avg_lum>128 → 白底黑字）：浮水印框在轉正後畫面的**底部**，頂部維持全白
    top = [up.getpixel((x, 5)) for x in range(0, 900, 50)]
    assert all(min(p) > 240 for p in top), "頂部不該有浮水印"
    bottom_band = [up.getpixel((x, y)) for x in range(10, 400, 5) for y in range(1200 - 70, 1200 - 5, 5)]
    assert any(min(p) < 200 for p in bottom_band), "浮水印應貼在轉正後畫面的底部"


def test_png_with_orientation_keeps_alpha_and_is_rotated_too():
    img = Image.new("RGBA", (400, 300), (255, 255, 255, 0))
    exif = Image.Exif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    img.save(buf, format="PNG", exif=exif)
    out, _g, _w = _process_project_photo(buf.getvalue(), "測試人")
    res = Image.open(io.BytesIO(out))
    assert res.format == "PNG" and res.mode == "RGBA" and res.size == (300, 400)
