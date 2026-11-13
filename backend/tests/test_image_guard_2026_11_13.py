# -*- coding: utf-8 -*-
"""圖片「解壓縮炸彈」守門（2026-11-13，hichan-9 稽核 H1 類延伸）。

事實：調色盤 PNG 檔案只有幾 KB（單檔大小上限擋不住）；Pillow 預設 4000 萬～1.79 億像素之間（如 13000x13000，「mid」）
完全不擋（<8900 萬連警告都沒有），`_process_project_photo` 解碼＋convert('RGBA')＋alpha_composite 會吃掉數 GB 記憶體；
> 1.79 億（如 20000x20000，「huge」）Pillow 在 open() 丟 DecompressionBombError，舊程式 `except Exception` 吞掉後**原檔照存**。
兩段都要擋、都要變成 400。
例外（PM 2026-11-13 裁示）：JPEG 放寬到 1.1 億像素（手機 108MP 原圖），但超過 4000 萬的 JPEG 一律先 `Image.draft()` 縮小解碼
（長邊 ≤ 約 4000），所以 12000x9000 的 JPEG 要能過、尖峰記憶體 < 300MB；PNG／GIF／WebP 是 2000 萬（PM 同日第二次裁示，原 4000 萬）；MPO 視同 JPEG。

**記憶體的量法**：tracemalloc 看不到 Pillow 的 C 層配置，所以在子行程裡量 PeakWorkingSet（Windows）／ru_maxrss（其他），
取「呼叫前後的峰值差」。
守門＝只讀檔頭宣告的長寬（`img.size`，延遲載入，此時尚未配置像素），超過 `helpers.image_guard.MAX_PIXELS`（2000 萬；JPEG／MPO 1.1 億）就拒絕。解碼同時最多 2 件（decode_slot），其餘等待或 503。

觀測點：
- 單元：`check_pixels`／`open_checked` 在邊界上下的行為；**拒絕時沒有解碼**（tracemalloc 尖峰遠小於 400MB）
- 每個使用者輸入入口：`_process_project_photo`、`save_document_files`（附件）、工作日誌照片端點、承攬商身分證／存簿端點、
  廠商承攬商存簿端點 ⇒ 全部 400（不是 500、也不是「原檔照存」）
- 正對照：同一批入口收一般大小的圖仍然成功
"""
import asyncio
import base64
import io
import os
import struct
import subprocess
import sys
import textwrap
import zlib

import pytest

pytest.importorskip("PIL")
from PIL import Image

from helpers import image_guard as G
from photos import _process_project_photo


def _bomb_png(w=20000, h=20000):
    """8 位元調色盤 PNG，全部像素＝索引 0；以串流壓縮產生（不配置 w*h 記憶體）。"""
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    comp = zlib.compressobj(9)
    row = b"\x00" * (w + 1)                      # filter byte＋w 個索引
    parts = [comp.compress(row * 200) for _ in range(h // 200)]
    parts.append(comp.compress(row * (h % 200)))
    parts.append(comp.flush())
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0))
            + chunk(b"PLTE", b"\x00\x00\x00\xff\xff\xff")
            + chunk(b"IDAT", b"".join(parts))
            + chunk(b"IEND", b""))


def _real_png(w=120, h=80):
    b = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(b, format="PNG")
    return b.getvalue()


BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_CHILD = textwrap.dedent("""
    import os, sys
    sys.path.insert(0, %(backend)r)
    def peak():
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            class C(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("a", ctypes.c_size_t), ("b", ctypes.c_size_t), ("c", ctypes.c_size_t),
                            ("d", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            k = ctypes.WinDLL("kernel32"); p = ctypes.WinDLL("psapi")
            k.GetCurrentProcess.restype = wintypes.HANDLE
            p.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(C), wintypes.DWORD]
            c = C(); c.cb = ctypes.sizeof(C)
            p.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(c), c.cb)
            return c.PeakWorkingSetSize
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    import photos
    from helpers import image_guard
    data = open(%(path)r, "rb").read()
    base = peak()
    try:
        if %(action)r == "photo":
            out, _g, _w = photos._process_project_photo(data, "x")
            from PIL import Image
            import io
            im = Image.open(io.BytesIO(out))
            res = "OK %%dx%%d %%s" %% (im.size[0], im.size[1], im.format)
        else:
            image_guard.open_checked(data)
            res = "OPENED"
    except image_guard.ImageTooLarge:
        res = "TOO_LARGE"
    print("RESULT", res, "%%.0f" %% ((peak() - base) / 1e6))
""")


def _measure(tmp_path, data, action):
    """子行程跑一次 action（photo＝_process_project_photo，open＝open_checked），回 (結果字串, 峰值記憶體增量 MB)。"""
    f = tmp_path / "img.bin"
    f.write_bytes(data)
    code = _CHILD % {"backend": BACKEND, "path": str(f), "action": action}
    r = subprocess.run([sys.executable, "-X", "utf8", "-c", code], capture_output=True, text=True, timeout=240, cwd=BACKEND)
    line = [x for x in r.stdout.splitlines() if x.startswith("RESULT")]
    assert line, "子行程沒有結果：\n%s\n%s" % (r.stdout[-500:], r.stderr[-1500:])
    parts = line[-1].split()
    return " ".join(parts[1:-1]), float(parts[-1])


def _jpeg_with_declared_size(w, h):
    """把小 JPEG 的 SOF 標頭長寬改成 w×h：Image.open 只讀標頭，所以便宜地得到「宣告很大」的 JPEG（解碼會失敗，只用來測拒絕／縮放決策）。"""
    b = io.BytesIO()
    Image.new("RGB", (120, 90), (10, 120, 200)).save(b, format="JPEG")
    d = bytearray(b.getvalue())
    i = d.index(b"\xff\xc0")                               # SOF0（Pillow 預設存基準 JPEG）
    d[i + 5:i + 9] = struct.pack(">HH", h, w)
    return bytes(d)


@pytest.fixture(scope="module")
def phone_jpeg_108mp():
    """12000x9000＝1.08 億像素的真 JPEG（手機 108MP 原圖）；左上一塊紅，其餘藍灰。"""
    img = Image.new("RGB", (12000, 9000), (60, 70, 90))
    img.paste((230, 0, 0), (0, 0, 3000, 2250))
    b = io.BytesIO()
    img.save(b, format="JPEG", quality=80)
    del img
    return b.getvalue()


@pytest.fixture(scope="module", params=[20000, 13000], ids=["huge_20000sq", "mid_13000sq"])
def bomb(request):
    """huge＝Pillow 自己會在 open() 擋（舊程式吞掉後原檔照存）；mid＝Pillow 放行、會真的被解碼（真正的記憶體風險）。"""
    side = request.param
    data = _bomb_png(side, side)
    assert len(data) < 2 * 1024 * 1024, "測試前提：炸彈檔本身很小（%d bytes）" % len(data)
    return data


def _auth(client, make_user, username, role="superadmin"):
    u, p = make_user(username=username, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


# ───────────── 單元 ─────────────

def test_caps():
    assert G.MAX_PIXELS == 20_000_000          # PNG／GIF／WebP…（PM 2026-11-13：截圖與掃描檔遠低於此）
    assert G.MAX_PIXELS_JPEG == 110_000_000    # JPEG／MPO（draft 縮小解碼）
    assert G.JPEG_FULL_DECODE_MAX == 40_000_000
    assert G.DRAFT_LONG_SIDE == 4000
    assert G.MAX_CONCURRENT_DECODES == 2
    assert G.ALLOWED_FORMATS == ("JPEG", "MPO", "PNG", "GIF", "WEBP")


def test_bomb_is_rejected_without_decoding(bomb, tmp_path):
    """拒絕時沒有解碼：子行程峰值記憶體增量小。（mid 若被解碼，RGBA 化要 600MB 以上。）"""
    res, mb = _measure(tmp_path, bomb, "open")
    assert res == "TOO_LARGE", res
    assert mb < 100, "拒絕時不該解碼（峰值增量 %.0fMB）" % mb


@pytest.mark.parametrize("w,h,ok", [
    (4472, 4472, True),        # 19.99M
    (5000, 4000, True),        # 剛好 20M：含上限
    (5001, 4000, False),       # 超過一個像素列
    (20000, 1000, True),       # 長條但像素少：只看乘積，不另設單邊上限
    (20001, 1001, False),
])
def test_boundary(w, h, ok):
    img = Image.new("1", (w, h))             # 1 位元影像：配置便宜，只為了拿 .size
    if ok:
        assert G.check_pixels(img) is img
    else:
        with pytest.raises(G.ImageTooLarge):
            G.check_pixels(img)


def test_normal_image_passes_and_is_still_lazy():
    img = G.open_checked(_real_png())
    assert img.size == (120, 80)
    img.load()                                # 呼叫端接著才解碼，仍可正常載入


def test_image_too_large_is_a_value_error():
    assert issubclass(G.ImageTooLarge, ValueError)


# ───────────── 各入口 ─────────────

def test_process_project_photo_raises_instead_of_swallowing(bomb):
    """`_process_project_photo` 原本 `except Exception` 吞掉一切、回原檔；炸彈必須往外丟，不能回「原檔照存」。"""
    with pytest.raises(G.ImageTooLarge):
        _process_project_photo(bomb, "測試人")


def test_process_project_photo_normal_still_works():
    out, _gps, wm = _process_project_photo(_real_png(1200, 800), "測試人")
    assert Image.open(io.BytesIO(out)).size == (1200, 800) and wm


@pytest.fixture()
def uploads_tmp(tmp_path, monkeypatch):
    """沒有 `client` 夾具的測試直接呼叫 save_document_files：UPLOADS_ROOT 必須自己導到 tmp，否則寫進真實的 uploads/。"""
    from helpers import uploads
    root = str(tmp_path / "uploads")
    monkeypatch.setattr(uploads, "UPLOADS_ROOT", root)
    return root


def _upload(name, data):
    from starlette.datastructures import UploadFile
    return UploadFile(file=io.BytesIO(data), filename=name)


def test_save_document_files_rejects_bomb_and_writes_nothing(bomb, uploads_tmp):
    """附件共用存檔（案件動態、CRM 等）：整批擋下、前面的好檔也不寫（維持「全驗完才寫」）。"""
    from fastapi import HTTPException
    from helpers import uploads
    with pytest.raises(HTTPException) as ei:
        asyncio.run(uploads.save_document_files(
            "dev_logs", "IMGBOMB-1", [_upload("ok.png", _real_png()), _upload("bomb.png", bomb)],
            "tester", watermark_by="tester"))
    assert ei.value.status_code == 400 and "圖片解析度過大" in ei.value.detail and "bomb.png" in ei.value.detail
    assert not os.path.exists(os.path.join(uploads_tmp, "dev_logs", "IMGBOMB-1")), "整批擋下，磁碟上不留任何東西"


def test_save_document_files_rejects_bomb_even_without_watermark(bomb, uploads_tmp):
    """不加浮水印的呼叫端也一樣擋（炸彈存進磁碟後，之後任何人開啟／縮圖都會中）。"""
    from fastapi import HTTPException
    from helpers import uploads
    with pytest.raises(HTTPException) as ei:
        asyncio.run(uploads.save_document_files("dev_logs", "IMGBOMB-2", [_upload("bomb.jpg", bomb)], "tester"))
    assert ei.value.status_code == 400
    assert not os.path.exists(os.path.join(uploads_tmp, "dev_logs", "IMGBOMB-2"))


def test_save_document_files_normal_image_ok(uploads_tmp):
    from helpers import uploads
    saved = asyncio.run(uploads.save_document_files("dev_logs", "IMGBOMB-3", [_upload("ok.png", _real_png())],
                                                    "tester", watermark_by="tester"))
    assert len(saved) == 1


def test_work_log_photo_endpoint_400(client, make_user, bomb):
    h = _auth(client, make_user, "ib_wl")
    import db
    conn = db.get_db()
    uid = conn.execute("SELECT id FROM users WHERE username=?", ("ib_wl",)).fetchone()["id"]
    conn.close()
    r = client.post("/api/work-logs", headers=h, json={"log_date": "2026-11-13", "user_id": uid, "content": "現場"})
    assert r.status_code in (200, 201), r.text
    wid = r.json()["id"]
    r = client.post(f"/api/work-logs/{wid}/photos", headers=h, files=[("files", ("bomb.png", bomb, "image/png"))])
    assert r.status_code == 400, (r.status_code, r.text[:200])
    assert "圖片解析度過大" in r.text
    ok = client.post(f"/api/work-logs/{wid}/photos", headers=h,
                     files=[("files", ("ok.png", _real_png(), "image/png"))])
    assert ok.status_code == 201, ok.text           # 正對照：同一個端點收一般圖仍成功
    assert ok.json()["added"] == 1


def _data_uri(raw):
    return "data:image/png;base64," + base64.b64encode(raw).decode()


@pytest.mark.parametrize("field", ["image_front", "image_back", "bank_passbook"])
def test_contractor_id_card_endpoint_400(client, make_user, bomb, field):
    """身分證／存簿：原本 stamp 失敗就 `except Exception: pass`、把炸彈的 data URI 原樣寫進 DB。"""
    h = _auth(client, make_user, "ib_ct")
    r = client.put("/api/contractors/1/id-card", headers=h, json={field: _data_uri(bomb)})
    assert r.status_code == 400, (field, r.status_code, r.text[:200])
    assert "圖片解析度過大" in r.text, (field, r.text[:200])


def test_vendor_contractor_passbook_endpoint_400(client, make_user, bomb):
    h = _auth(client, make_user, "ib_vc")
    r = client.put("/api/vendor-contractors/1/passbook", headers=h, json={"bank_passbook": _data_uri(bomb)})
    assert r.status_code == 400, (r.status_code, r.text[:200])
    assert "圖片解析度過大" in r.text


def test_stamp_functions_normal_image_still_work():
    from modules.subcontract.api import contractors as C
    uri = _data_uri(_real_png(600, 400))
    assert C._stamp_id_card(uri).startswith("data:image/")
    assert C._stamp_passbook(uri).startswith("data:image/")


def test_stamp_functions_raise_on_bomb(bomb):
    from modules.subcontract.api import contractors as C
    uri = _data_uri(bomb)
    with pytest.raises(G.ImageTooLarge):
        C._stamp_id_card(uri)
    with pytest.raises(G.ImageTooLarge):
        C._stamp_passbook(uri)


# ───────────── JPEG：放寬到 1.1 億像素，但縮小解碼 ─────────────

@pytest.mark.parametrize("w,h,ok", [
    (12000, 9000, True),       # 1.08 億：108MP 手機原圖
    (12000, 9166, True),       # 1.0999 億
    (12000, 9167, False),      # 剛超過 1.1 億
    (16000, 12000, False),     # 192MP：Pillow 自己會在 open() 丟 DecompressionBombError（超過 1.79 億）⇒ 也是 ImageTooLarge
])
def test_jpeg_cap_is_110_million(w, h, ok):
    data = _jpeg_with_declared_size(w, h)
    if ok:
        assert G.open_checked(data).format == "JPEG"
    else:
        with pytest.raises(G.ImageTooLarge):
            G.open_checked(data)


@pytest.mark.parametrize("w,h,expect", [
    (4032, 3024, (4032, 3024)),        # 一般 12MP 手機照：不縮（維持原行為）
    (8000, 5000, (8000, 5000)),        # 剛好 4000 萬：不縮
    (8000, 6000, (4000, 3000)),        # 48MP：1/2，長邊 4000
    (12000, 9000, (3000, 2250)),       # 108MP：1/4
    (12000, 9166, (3000, 2292)),
])
def test_jpeg_draft_scale(w, h, expect):
    assert G.open_checked(_jpeg_with_declared_size(w, h)).size == expect


def test_png_over_20m_is_not_relaxed():
    """正對照：只有 JPEG 放寬；同樣 1 億像素的 PNG 仍然拒絕（PNG 無法縮小解碼）。"""
    img = Image.new("1", (10000, 10000))        # 宣告 1 億像素的 PNG：1 位元影像，配置只有 12MB
    b = io.BytesIO()
    img.save(b, format="PNG")
    with pytest.raises(G.ImageTooLarge):
        G.open_checked(b.getvalue())


def test_108mp_jpeg_passes_with_low_peak_memory(phone_jpeg_108mp, tmp_path):
    """PM 指定：12000x9000 JPEG 要能過、尖峰記憶體 < 300MB；存下來的是縮小後的影像（長邊 ≤ 4000）。"""
    res, mb = _measure(tmp_path, phone_jpeg_108mp, "photo")
    assert res.startswith("OK"), res
    w, h = [int(x) for x in res.split()[1].split("x")]
    assert max(w, h) <= 4000 and (w, h) == (3000, 2250), res
    assert res.endswith("JPEG")
    assert mb < 300, "108MP JPEG 經 _process_project_photo 的峰值增量 %.0fMB（要 < 300）" % mb


def test_108mp_jpeg_keeps_content(phone_jpeg_108mp):
    """縮小解碼後內容仍對：左上角那塊紅色（原圖 25%×25%）在縮小後的左上角。"""
    out, _g, _w = _process_project_photo(phone_jpeg_108mp, "測試人")
    img = Image.open(io.BytesIO(out))
    assert img.size == (3000, 2250)
    r, g, b = img.convert("RGB").getpixel((int(3000 * 0.125), int(2250 * 0.125)))
    assert r > 180 and g < 90 and b < 90, (r, g, b)


def test_save_document_files_accepts_108mp_jpeg_and_rejects_over(phone_jpeg_108mp, uploads_tmp):
    from fastapi import HTTPException
    from helpers import uploads
    saved = asyncio.run(uploads.save_document_files("dev_logs", "IMGBOMB-JPG", [_upload("phone.jpg", phone_jpeg_108mp)],
                                                    "tester", watermark_by="tester"))
    assert len(saved) == 1
    with pytest.raises(HTTPException) as ei:
        asyncio.run(uploads.save_document_files("dev_logs", "IMGBOMB-JPG2",
                                                [_upload("big.jpg", _jpeg_with_declared_size(12000, 10000))], "tester"))
    assert ei.value.status_code == 400


# ───────────── 第二輪（PM 裁示，hichan-12 抽查）：MPO、白名單、HEIF、解碼名額、警告靜音、漸進式 JPEG ─────────────

def _mpo_with_declared_size(w, h):
    """真的 MPO（兩張 JPEG＋MPF 索引；Pillow 回報格式 'MPO'），把第一張的 SOF 長寬改成 w×h。"""
    a = Image.new("RGB", (120, 90), (10, 120, 200))
    b = io.BytesIO()
    a.save(b, format="MPO", save_all=True, append_images=[Image.new("RGB", (120, 90), (200, 30, 30))])
    d = bytearray(b.getvalue())
    i = d.index(b"\xff\xc0")
    d[i + 5:i + 9] = struct.pack(">HH", h, w)
    return bytes(d)


def test_mpo_is_really_mpo_and_treated_as_jpeg():
    """hichan-12 M1：多圖 JPEG 的 format 是 'MPO'，不能落到 2000 萬的非 JPEG 上限、也要走 draft。"""
    img = G.open_checked(_mpo_with_declared_size(12000, 9000))
    assert img.format == "MPO"
    assert img.size == (3000, 2250)                  # 1.08 億：放行＋draft 1/4
    with pytest.raises(G.ImageTooLarge):
        G.open_checked(_mpo_with_declared_size(12000, 10000))       # 1.2 億：超過 JPEG 上限
    assert G.open_checked(_mpo_with_declared_size(4032, 3024)).size == (4032, 3024)    # 12MP 不縮


def test_formats_allow_list_blocks_other_formats_by_content(tmp_path):
    """TIFF／BMP 等依內容也不開（白名單）；_process_project_photo 對打不開的檔維持舊行為：回原檔。"""
    from PIL import UnidentifiedImageError
    for fmt in ("TIFF", "BMP"):
        b = io.BytesIO()
        Image.new("RGB", (50, 40), (1, 2, 3)).save(b, format=fmt)
        with pytest.raises(UnidentifiedImageError):
            G.open_checked(b.getvalue())
        out, _g, _w = _process_project_photo(b.getvalue(), "測試人")
        assert out == b.getvalue()


_HEIF = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 64


def test_heif_is_not_decoded_and_still_stored_as_is():
    """HEIC／HEIF 沒有解碼器：open_checked 丟 ImageUnsupported（從不解碼），但它不是 ImageRejected——
    上傳端點一直接受 .heic（原檔照存、不浮水印；tests/test_upload_magic_2026_09_30 也驗），所以處理函式回原檔、不是 400。"""
    with pytest.raises(G.ImageUnsupported):
        G.open_checked(_HEIF)
    assert not issubclass(G.ImageUnsupported, G.ImageRejected)
    out, _g, _w = _process_project_photo(_HEIF, "測試人")
    assert out == _HEIF


def test_decode_slot_limits_to_two_and_busy_is_503(monkeypatch):
    monkeypatch.setattr(G, "DECODE_THREAD_WAIT_SECONDS", 0.05)
    with G.decode_slot():
        with G.decode_slot():
            with pytest.raises(G.ImageBusy) as ei:
                with G.decode_slot():
                    pass
            assert ei.value.status == 503 and ei.value.user_message == "伺服器忙碌，請稍後再試"
    with G.decode_slot():                              # 釋放後可再取
        pass


def test_process_project_photo_signature_unchanged_and_slotted():
    import inspect
    assert list(inspect.signature(_process_project_photo).parameters) == ["image_bytes", "uploader_name"]
    assert hasattr(_process_project_photo, "__wrapped__")


def test_busy_gives_503_on_work_log_endpoint(client, make_user, monkeypatch):
    import threading
    h = _auth(client, make_user, "ib_busy")
    import db
    conn = db.get_db()
    uid = conn.execute("SELECT id FROM users WHERE username=?", ("ib_busy",)).fetchone()["id"]
    conn.close()
    wid = client.post("/api/work-logs", headers=h, json={"log_date": "2026-11-13", "user_id": uid, "content": "x"}).json()["id"]
    monkeypatch.setattr(G, "DECODE_THREAD_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(G, "_SEM", threading.BoundedSemaphore(1))
    assert G._SEM.acquire(timeout=1)                   # 名額被占滿
    try:
        r = client.post(f"/api/work-logs/{wid}/photos", headers=h, files=[("files", ("a.png", _real_png(), "image/png"))])
    finally:
        G._SEM.release()
    assert r.status_code == 503 and "伺服器忙碌" in r.text, (r.status_code, r.text[:200])


def test_concurrent_decodes_never_exceed_two(monkeypatch):
    """多執行緒同時進 _process_project_photo：同一時間解碼中的件數 ≤ 2（記憶體不會倍增）。"""
    import threading
    import time
    import photos
    inside = {"now": 0, "max": 0}
    lock = threading.Lock()
    orig = G.open_checked

    def slow_open(*a, **kw):
        with lock:
            inside["now"] += 1
            inside["max"] = max(inside["max"], inside["now"])
        time.sleep(0.15)
        try:
            return orig(*a, **kw)
        finally:
            with lock:
                inside["now"] -= 1
    monkeypatch.setattr(photos, "open_checked", slow_open)
    data = _real_png()
    ts = [threading.Thread(target=_process_project_photo, args=(data, "t")) for _ in range(5)]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert 1 <= inside["max"] <= 2, inside


def test_bomb_warning_is_silenced_even_under_warnings_as_errors(tmp_path):
    """hichan-12：89.5M～110M 的 JPEG 會觸發 DecompressionBombWarning；-W error 時它不能逃出 open_checked（否則被當一般失敗存原檔）。"""
    f = tmp_path / "j.jpg"
    f.write_bytes(_jpeg_with_declared_size(12000, 9000))
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from helpers import image_guard as G\n"
            "img = G.open_checked(open(%r,'rb').read()); print('RESULT', img.size)\n") % (BACKEND, str(f))
    env = dict(os.environ, PYTHONWARNINGS="error")
    r = subprocess.run([sys.executable, "-X", "utf8", "-c", code], capture_output=True, text=True, timeout=60, cwd=BACKEND, env=env)
    assert "RESULT (3000, 2250)" in r.stdout, r.stdout[-300:] + r.stderr[-800:]


def test_progressive_jpeg_over_40m_stays_bounded(tmp_path):
    """hichan-12：漸進式 JPEG 的 draft 仍要持有全尺寸係數緩衝（比基準式多約 90MB），要看得到上限。"""
    img = Image.new("RGB", (9000, 6000), (60, 70, 90))
    img.paste((230, 0, 0), (0, 0, 2250, 1500))
    b = io.BytesIO()
    img.save(b, format="JPEG", quality=80, progressive=True)
    del img
    res, mb = _measure(tmp_path, b.getvalue(), "photo")
    assert res.startswith("OK 2250x1500"), res
    assert mb < 300, "漸進式 54MP JPEG 峰值增量 %.0fMB（要 < 300）" % mb


# ───────────── 第三輪（hichan-12 round 2）：排隊不占共用執行緒池、排隊上限、formats 過濾後為空 ─────────────

def test_empty_formats_after_filtering_is_not_unrestricted():
    b = io.BytesIO()
    Image.new("RGB", (50, 40), (1, 2, 3)).save(b, format="TIFF")
    with pytest.raises(G.ImageUnsupported):
        G.open_checked(b.getvalue(), formats=["NOSUCHFORMAT"])


def test_thread_waiters_are_capped_and_fail_fast(monkeypatch):
    """兩個名額都被占住、排隊的執行緒已達上限 ⇒ 立刻 ImageBusy（不等待、不再占一條執行緒池的執行緒）。"""
    import time
    monkeypatch.setattr(G, "_waiting", G.MAX_WAITING_THREADS)
    with G.decode_slot():
        with G.decode_slot():
            t = time.time()
            with pytest.raises(G.ImageBusy):
                with G.decode_slot(wait=5):
                    pass
            assert time.time() - t < 0.5, "排隊已滿要立刻失敗，不是等 5 秒"


def test_run_decode_queue_does_not_starve_the_thread_pool(monkeypatch):
    """hichan-12 實測：一個人連發 60 張，40 條執行緒全卡在等名額 ⇒ 登入／列表（同步端點）等 16 秒。
    run_decode 在事件迴圈上排隊：解碼中的只有 2 條執行緒，其餘不占池；同時另一個同步呼叫要能很快完成。"""
    import time
    from starlette.concurrency import run_in_threadpool
    monkeypatch.setattr(G, "DECODE_WAIT_SECONDS", 0.6)
    monkeypatch.setattr(G, "MAX_WAITING_ASYNC", 40)

    def fake_decode():
        with G.decode_slot():
            time.sleep(0.3)
            return "done"

    async def scenario():
        calls = [asyncio.ensure_future(G.run_decode(fake_decode)) for _ in range(30)]
        await asyncio.sleep(0.1)
        t = time.time()
        await run_in_threadpool(lambda: 1)                 # 同步端點代表：不能被解碼排隊卡住
        probe = time.time() - t
        res = await asyncio.gather(*calls, return_exceptions=True)
        return probe, res

    probe, res = asyncio.run(scenario())
    assert probe < 0.25, "排隊把共用執行緒池占住了（同步呼叫等了 %.2fs）" % probe
    ok = [r for r in res if r == "done"]
    busy = [r for r in res if isinstance(r, G.ImageBusy)]
    assert len(ok) + len(busy) == 30 and ok and busy, (len(ok), len(busy))      # 一部分做完、其餘 503，沒有人卡死


def test_run_decode_async_queue_is_capped(monkeypatch):
    monkeypatch.setattr(G, "MAX_WAITING_ASYNC", 3)
    monkeypatch.setattr(G, "DECODE_WAIT_SECONDS", 2.0)
    import time

    def slow():
        time.sleep(0.4)
        return 1

    async def scenario():
        calls = [asyncio.ensure_future(G.run_decode(slow)) for _ in range(8)]
        return await asyncio.gather(*calls, return_exceptions=True)

    res = asyncio.run(scenario())
    assert sum(isinstance(r, G.ImageBusy) for r in res) >= 3, res          # 2 在跑、3 排隊，其餘立刻 503


# ───────────── 第四輪（hichan-12 Low）：整批失敗不留孤兒檔 ─────────────

def _files_under(path):
    out = []
    for root, _d, names in os.walk(path):
        out += [os.path.join(root, n) for n in names]
    return out


def test_work_log_batch_failure_leaves_no_orphan_files(client, make_user, bomb):
    """一批 [好圖, 炸彈]：第二張 400 ⇒ 第一張已寫的檔要刪掉（否則孤兒＋客戶端重試又多一份）。"""
    h = _auth(client, make_user, "ib_orphan")
    import db
    from routers import system
    conn = db.get_db()
    uid = conn.execute("SELECT id FROM users WHERE username=?", ("ib_orphan",)).fetchone()["id"]
    conn.close()
    wid = client.post("/api/work-logs", headers=h, json={"log_date": "2026-11-13", "user_id": uid, "content": "x"}).json()["id"]
    r = client.post(f"/api/work-logs/{wid}/photos", headers=h,
                    files=[("files", ("ok.png", _real_png(), "image/png")), ("files", ("bomb.png", bomb, "image/png"))])
    assert r.status_code == 400, (r.status_code, r.text[:200])
    base_dir, _prefix = system._photo_root()
    assert _files_under(os.path.join(base_dir, "worklog_%s" % wid)) == []
    got = client.get(f"/api/work-logs/{wid}", headers=h)
    if got.status_code == 200:
        assert not (got.json().get("photos") or [])


def test_save_document_files_busy_mid_batch_leaves_no_orphans(uploads_tmp, monkeypatch):
    """第二階段第二張因 503 被擋 ⇒ 第一張已寫的檔要刪掉。"""
    import asyncio
    from helpers import uploads
    calls = {"n": 0}
    real = uploads.run_decode

    async def flaky(fn, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise G.ImageBusy("test")
        return await real(fn, *a, **kw)
    monkeypatch.setattr(uploads, "run_decode", flaky)
    files = [_upload("a.png", _real_png()), _upload("b.png", _real_png())]
    with pytest.raises(Exception) as ei:
        asyncio.run(uploads.save_document_files("dev_logs", "IMGBOMB-ORPHAN", files, "tester", watermark_by="tester"))
    assert getattr(ei.value, "status_code", None) == 503, repr(ei.value)
    assert _files_under(uploads_tmp) == []
