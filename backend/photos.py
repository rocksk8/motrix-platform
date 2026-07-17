"""Photo upload processing: EXIF GPS extraction and watermarking."""
import io
import os
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_PHOTO_UPLOAD_BASE = os.path.join(os.path.dirname(__file__), "..", "uploads", "projects")


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

        if img.mode not in ('RGB',):
            img = img.convert('RGB')

        w, h = img.size
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
        parts = [uploader_name, now_str]
        if gps_str:
            parts.append(f'GPS {gps_str}')
        watermark_str = '  ·  '.join(parts)

        strip_h = max(50, h // 12)
        strip   = img.crop((0, h - strip_h, w, h))
        pixels  = list(strip.getdata())
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

        result = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
        buf = io.BytesIO()
        result.save(buf, format='JPEG', quality=88)
        return buf.getvalue(), gps_str, watermark_str

    except ImportError:
        logger.warning("Pillow not installed — photo saved without watermark")
        return image_bytes, gps_str, watermark_str
    except Exception:
        logger.exception("_process_project_photo failed")
        return image_bytes, gps_str, watermark_str
