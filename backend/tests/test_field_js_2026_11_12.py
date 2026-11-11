# -*- coding: utf-8 -*-
"""T80c S3：`frontend/static/field.js`（外勤手機上傳模組）的行為題。

`tests/field_js_harness.js` 用 node 載入 field.js，注入假 XHR／假計時器／假相機／假定位，把每個情境的結果印成一行 JSON；這裡逐情境斷言。
沒有 node 的機器會略過——⚠️ skip 不是驗過。

釘住的是「弱訊號手機」要靠的那幾條：
- 重試用**同一把** Idempotency-Key、同一份位元組（伺服端才認得是同一次請求）；退避 2／5／10 秒、最多重試 3 次；
- 4xx（401／402／428 之外）不重試；409 照 Retry-After（上限 15 秒）；
- 60 秒「沒有進度」才算逾時，有進度就續命；
- 401／402／428 各導到對的頁面、只導一次、不再重試；
- 縮圖：長邊 ≤1600、JPEG q0.8、EXIF 方向烤進像素、任何失敗退回原檔；
- 先送文字、再逐張補照片；失敗那張只重傳它自己（同 key、同位元組）；文字失敗就不送照片。
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
HARNESS = HERE / "field_js_harness.js"
FIELD_JS = HERE.parents[1] / "frontend" / "static" / "field.js"

_cache = {}


def _out():
    if "o" not in _cache:
        node = shutil.which("node")
        if not node:
            pytest.skip("這台機器沒有 node —— ⚠️ skip 不是驗過")
        p = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, encoding="utf-8", timeout=120)
        assert p.returncode == 0, (p.stdout[-800:], p.stderr[-800:])
        _cache["o"] = json.loads(p.stdout.strip().splitlines()[-1])
        assert "__error" not in _cache["o"], _cache["o"].get("__error")
    return _cache["o"]


def test_field_js_exists_and_is_small():
    assert FIELD_JS.is_file()
    assert FIELD_JS.stat().st_size <= 40 * 1024      # 預算（S5 另有整頁 ≤200 KB 的守門）；這支是手機要下載的


def test_retry_keeps_the_same_key_and_backs_off_2_then_5_seconds():
    r = _out()["retry_network"]
    assert r["ok"] is True and r["attempts"] == 3
    assert len(set(r["keys"])) == 1 and r["keys"][0] == "KEY-0000001"
    assert r["sleeps"] == [2000, 5000]
    assert r["auth"] == "Bearer TOK123"


def test_client_errors_are_not_retried():
    o = _out()
    assert o["no_retry_400"]["attempts"] == 1 and o["no_retry_400"]["calls"] == 1 and o["no_retry_400"]["ok"] is False
    assert o["no_retry_400"]["status"] == 400 and "格式不合" in o["no_retry_400"]["error"]       # 伺服端的 detail 帶給使用者
    assert o["no_retry_422"]["calls"] == 1                                                      # 同 key 不同內容：重試也不會好


def test_server_errors_retry_three_times_then_give_up_with_the_same_key():
    r = _out()["exhausted_503"]
    assert r["calls"] == 4 and r["attempts"] == 4 and r["exhausted"] is True and r["ok"] is False
    assert len(set(r["keys"])) == 1
    assert r["sleeps"] == [2000, 5000, 10000]


def test_409_in_progress_honors_retry_after_but_is_capped():
    o = _out()
    assert o["retry_409"]["ok"] is True and o["retry_409"]["replay"] is True and o["retry_409"]["sleeps"] == [7000]
    assert o["retry_409_cap"]["sleeps"] == [15000]            # 伺服端說 999 秒也不讓使用者乾等


def test_timeout_is_60_seconds_without_progress_and_progress_resets_it():
    o = _out()
    assert o["timeout_no_progress"]["ok"] is True and o["timeout_no_progress"]["attempts"] == 2
    assert o["timeout_no_progress"]["firstSleep"] == 60000
    assert len(set(o["timeout_no_progress"]["keys"])) == 1
    # 進度在 30s／55s／100s：每次都重新計時，100s 之後再 60s 沒動靜才逾時（再退避 2 秒才重送）
    assert o["timeout_progress_resets"]["firstAttemptEndedAt"] == 160000


def test_gates_redirect_once_and_stop_retrying():
    o = _out()
    assert o["gate_401"]["redirects"] == ["login.html"] and o["gate_401"]["calls"] == 1 and o["gate_401"]["session"] is None   # 清掉過期的登入
    assert o["gate_402"]["redirects"] == ["license-required.html"] and o["gate_402"]["gated"] is True
    assert o["gate_428_fix"]["redirects"] == ["company-profile-settings.html?setup=1"]
    assert o["gate_428_nofix"]["redirects"] == ["company-setup-required.html"]
    assert o["gate_428_other"]["redirects"] == [] and o["gate_428_other"]["gated"] is False       # 428 但不是公司資料未設定：當一般錯誤


def test_shrink_long_edge_1600_jpeg_q08_and_orientation_baked_in():
    o = _out()
    big = o["shrink_big"]
    assert big["res"]["shrunk"] is True and big["res"]["width"] == 1600 and big["res"]["height"] == 1200 and big["res"]["name"] == "IMG_0001.jpg"
    assert big["calls"]["bmp"] == [{"imageOrientation": "from-image"}]             # 方向烤進像素（EXIF 之後會被丟掉）
    assert big["calls"]["toBlob"] == [["image/jpeg", 0.8]]
    por = o["shrink_portrait"]["res"]
    assert (por["width"], por["height"]) == (1200, 1600) and por["name"] == "a.jpg"        # .heic 改 .jpg
    small = o["shrink_small"]["res"]
    assert (small["width"], small["height"]) == (800, 600)                                # 不放大；仍重編碼（為了烤進方向）


def test_shrink_falls_back_to_the_original_on_any_failure():
    o = _out()
    for k in ("shrink_fail", "shrink_noblob", "shrink_gif", "shrink_pdf", "shrink_noapi"):
        assert o[k]["res"]["shrunk"] is False if "res" in o[k] else o[k]["shrunk"] is False, k
    assert o["shrink_noapi"]["same"] is True                                              # 原檔，不是副本
    assert o["shrink_gif"]["calls"]["bmp"] == [] and o["shrink_pdf"]["calls"]["bmp"] == []    # 動圖／非圖片根本不碰


def test_geolocation_is_best_effort_and_never_blocks():
    o = _out()
    assert o["geo_ok"]["res"] == "25.033000,121.565400,12.3"
    assert o["geo_ok"]["opts"] == {"timeout": 5000, "maximumAge": 60000, "enableHighAccuracy": False}
    for k in ("geo_denied", "geo_never", "geo_throw", "geo_none"):
        assert o[k]["res"] == "", k                      # 拒絕／沒回應／丟例外／沒有定位 API：空字串，不擋上傳


def test_idempotency_keys_match_the_server_format():
    k = _out()["keys"]
    assert k["fallback"]["okFormat"] is True and k["real"]["okFormat"] is True and k["real"]["distinct"] is True


def test_drafts_survive_a_reload_per_case_and_storage_failure_is_harmless():
    o = _out()
    assert o["draft"] == {"got": "剛打的字", "other": "", "after": ""}
    assert o["draft_nostorage"]["load"] == ""


def test_text_first_then_each_photo_with_its_own_key_and_geo():
    f = _out()["flow_ok"]
    assert f["urls"] == ["/api/quotations/MQ-202611-001/updates"] + ["/api/quotations/MQ-202611-001/updates/77/files"] * 2
    assert len(set(f["keys"])) == 3                                           # 每個請求各一把 key
    assert f["textBody"][0] == ["content", "到場了", None]                      # 文字已 trim
    assert f["photoBody0"] == [["files", "[blob 1234]", "p0.jpg"], ["geo", "25.033000,121.565400,10", None]]
    assert f["textStatus"] == "done" and f["photos"] == ["done", "done"] and f["updateId"] == 77
    assert f["firstEvents"] == ["text-saving", "text-saved"] and f["lastEvent"] == "done" and f["progressSeen"] is True


def test_photo_only_post_uses_the_default_text():
    assert _out()["flow_empty_text"]["content"] == "（現場照片）"


def test_text_failure_sends_no_photos():
    f = _out()["flow_text_fail"]
    assert f["calls"] == 1 and f["text"] == "failed" and f["photos"] == ["queued", "queued"]


def test_one_bad_photo_does_not_block_the_rest_and_retry_resends_only_it_with_same_key_and_bytes():
    f = _out()["flow_partial_retry"]
    assert f["afterFirst"]["statuses"] == ["done", "failed", "done"] and f["afterFirst"]["calls"] == 4
    a = f["afterRetry"]
    assert a["statuses"] == ["done", "done", "done"] and a["calls"] == 5                  # 只多一次請求
    assert a["retryUrl"] == "/api/quotations/Q/updates/5/files"
    assert a["sameKey"] is True and a["sameBlob"] is True                                 # 同 key、同一份位元組
    assert a["retryKey"] == f["afterFirst"]["keysFirst"][2]


def test_text_retry_after_failure_reuses_the_text_key_then_sends_the_photo():
    f = _out()["flow_text_retry"]
    assert f["failedText"] == {"text": "failed", "calls": 4, "photoStatus": "queued"}
    assert f["after"]["text"] == "done" and f["after"]["photo"] == "done" and f["after"]["calls"] == 6
    assert len(set(f["after"]["textKeys"])) == 1                                          # 5 次文字請求全是同一把 key


def test_session_expiry_during_text_stops_everything():
    f = _out()["flow_401"]
    assert f["redirects"] == ["login.html"] and f["calls"] == 1 and f["gated"] is True


def test_shrunk_photo_is_what_gets_uploaded_with_a_jpg_name():
    f = _out()["flow_shrunk_upload"]
    assert f["filename"] == "IMG_9.jpg" and f["blob"] == "[blob 1234]" and f["canvas"] == [1600, 1200]


def test_case_number_is_url_encoded_in_the_path():
    assert _out()["flow_url_encoded"]["url"] == "/api/quotations/MQ%2F..%2Fx%20y/updates"
