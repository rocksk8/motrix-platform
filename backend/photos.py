"""Photo upload processing: EXIF GPS extraction and watermarking."""

#: G1（MODULE-GUIDE §2）：底線開頭但屬於 L1 公開介面的名稱——改簽章或刪除照介面變更升版。
#: L1 以外只可以用這裡列出的底線名稱（守門：test_l1_interface_snapshot::test_l2_uses_only_declared_l1_underscore_names）。
__l1_public__ = (
    "_photo_root",
    "_process_project_photo",
)

import io
import os
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

from core import paths as _paths

_PHOTO_UPLOAD_BASE = _paths.PROJECT_PHOTOS_DIR


def _photo_root():
    """(abs_base_dir, url_prefix) — swapped to the isolated, demo-reset folder
    (db.DEMO_PROJECT_PHOTOS_DIR) for the 'demo' showcase account, so uploaded
    photos never land in the real uploads/projects/ tree."""
    from db import is_demo_mode, DEMO_PROJECT_PHOTOS_DIR
    if is_demo_mode():
        return DEMO_PROJECT_PHOTOS_DIR, "_demo_projects"
    return _PHOTO_UPLOAD_BASE, "projects"


def _gps_to_decimal(dms) -> Optional[float]:
    try:
        d, m, s = float(dms[0]), float(dms[1]), float(dms[2])
        return d + m / 60.0 + s / 3600.0
    except Exception:
        return None


def _process_project_photo(image_bytes: bytes, uploader_name: str):
    """Add date/time/GPS watermark with auto contrast text. Returns (bytes, gps_str, watermark_str)."""
    gps_str, watermark_str = '', ''
    try:
        from PIL import Image, ImageDraw, ImageFont
        from PIL.ExifTags import TAGS, GPSTAGS

        img = Image.open(io.BytesIO(image_bytes))
        # 來源格式一定要在任何 convert() 之前抓——convert 出來的新影像 .format 是 None
        src_format = (img.format or '').upper()

        try:
            exif_raw = img._getexif() or {}
            for tag_id, val in exif_raw.items():
                if TAGS.get(tag_id) == 'GPSInfo':
                    gd = {GPSTAGS.get(k, k): v for k, v in val.items()}
                    lat = _gps_to_decimal(gd.get('GPSLatitude'))
                    lon = _gps_to_decimal(gd.get('GPSLongitude'))
                    if lat is not None and lon is not None:
                        if gd.get('GPSLatitudeRef') == 'S': lat = -lat
                        if gd.get('GPSLongitudeRef') == 'W': lon = -lon
                        gps_str = f'{lat:.5f},{lon:.5f}'
                    break
        except Exception:
            pass

        # 透明度與輸出格式（2026-09-15 修）。
        #
        # 在此之前這裡一律 `convert('RGB')`、最後一律存成 JPEG，造成兩個問題：
        #
        # ① **把透明 PNG 毀掉**。RGBA→RGB 是直接把 alpha 丟掉、露出底下的 RGB 值。
        #    使用者傳 `logo-white.png`（白色字＋透明底）上來，透明處底下的值是白的，
        #    白字落在白底上＝整個字不見了，畫面上只剩那顆彩色圓環。實測原圖中段有
        #    5902 個「不透明且接近白」的取樣像素，處理完剩 52 個。
        # ② 存檔端（helpers/uploads.py、routers/system.py）沿用**上傳時的副檔名**，
        #    所以會產生「副檔名 .png、內容是 JPEG」的檔案。
        #
        # 改成**輸出跟著來源格式走**：PNG 進 PNG 出（alpha 保留），其餘（手機拍的
        # JPEG）行為與改動前逐字相同。副檔名與內容從此一致，②順帶消失。
        keep_alpha = src_format == 'PNG'
        img = img.convert('RGBA' if keep_alpha else 'RGB')

        w, h = img.size
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
        parts = [uploader_name, now_str]
        if gps_str:
            parts.append(f'GPS {gps_str}')
        watermark_str = '  ·  '.join(parts)

        strip_h = max(50, h // 12)
        strip   = img.crop((0, h - strip_h, w, h))
        if keep_alpha:
            # 透明處先疊到白底再取樣。直接讀 RGBA 會拿到「被 alpha 遮住、根本看不見」
            # 的顏色，挑出來的浮水印對比色是對著一張不存在的圖算的；襯白是因為畫面上
            # 附件縮圖本來就是放在白底頁面上。
            strip = Image.alpha_composite(Image.new('RGBA', strip.size, (255, 255, 255, 255)), strip)
        pixels  = list(strip.convert('RGB').getdata())
        avg_lum = sum(0.299*r + 0.587*g + 0.114*b for r, g, b in pixels) / max(len(pixels), 1)

        if avg_lum > 128:
            text_color = (10, 10, 10)
            bg_rgba    = (255, 255, 255, 195)
        else:
            text_color = (245, 245, 245)
            bg_rgba    = (0, 0, 0, 195)

        font_size = max(16, w // 52)
        font = None
        for fp in ['C:/Windows/Fonts/msjh.ttc', 'C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/arial.ttf']:
            try:
                font = ImageFont.truetype(fp, font_size)
                break
            except Exception:
                pass
        if font is None:
            font = ImageFont.load_default()

        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw    = ImageDraw.Draw(overlay)
        try:
            bbox = draw.textbbox((0, 0), watermark_str, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except AttributeError:
            tw, th = draw.textsize(watermark_str, font=font)

        pad, margin = 10, 14
        x = margin
        y = h - th - pad * 2 - margin
        draw.rectangle([x - pad, y - pad, x + tw + pad, y + th + pad], fill=bg_rgba)
        draw.text((x, y), watermark_str, fill=text_color + (255,), font=font)

        result = Image.alpha_composite(img.convert('RGBA'), overlay)
        buf = io.BytesIO()
        if keep_alpha:
            result.save(buf, format='PNG', optimize=True)
        else:
            result.convert('RGB').save(buf, format='JPEG', quality=88)
        return buf.getvalue(), gps_str, watermark_str

    except ImportError:
        logger.warning("Pillow not installed — photo saved without watermark")
        return image_bytes, gps_str, watermark_str
    except Exception:
        logger.exception("_process_project_photo failed")
        return image_bytes, gps_str, watermark_str
