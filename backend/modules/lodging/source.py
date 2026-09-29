# -*- coding: utf-8 -*-
"""旅宿資料來源：交通部觀光署「旅館民宿 - 觀光資訊資料庫」（data.gov.tw 7780）。

條款與欄位查證：docs/platform/LODGING-NEARBY.md §1.1（政府資料開放授權條款第 1 版：可商用、可保存、**必須顯名**）。

## 這是本模組**唯一**的對外連線（§3.5）

- 開關：`MOTRIX_LODGING_FETCH=1` 才准下載（預設關；關著時連 `fetch_raw` 都不呼叫）。
- 觸發：①最高管理者按「更新旅宿資料」（`refresh()`）②每日自動更新（`schedule_daily_refresh()`；2026-09-29 使用者：
  「旅宿檔案更新改到系統內，並且每天自動更新」，取代原「不排程」裁示）：每小時檢查一次，當天 `DAILY_REFRESH_HOUR` 點後
  還沒成功更新過才下載；同樣受開關、展示模式、速率與更新鎖限制。開頁與查詢都不連線。
- 速率：兩次成功間隔 ≥ `MIN_SUCCESS_INTERVAL`（24 小時，來源每日更新一次）；失敗後冷卻 `FAILURE_COOLDOWN`（1 小時）；
  同時只跑一個（`_REFRESH_LOCK`，非阻塞；拿不到 ⇒ 回「更新中」）。狀態記在設定 `lodging_fetch_state`（計數有落點）。
- 失敗 ⇒ 舊快照不動，狀態記原因；**不可以**讓查詢看起來像「附近 0 間」（查詢端看 `catalog_state()`）。

## zip 防護（LG-S3）

檔名白名單、拒絕絕對路徑／`..`／磁碟代號（zip slip）、解壓總量上限、宣告大小與實際讀出一致；
只在記憶體裡解開白名單內的檔，不寫磁碟。任一不過 ⇒ 整包拒絕、舊快照不動。
"""
import io
import json
import logging
import os
import re
import threading
import time
import urllib.request
import zipfile
from datetime import datetime, timedelta

from db import get_db, is_demo_mode
from helpers.settings import _get_setting, _set_setting

logger = logging.getLogger(__name__)

SOURCE_KEY = "mot"   # 觀光署
DATASET_URL = "https://media.taiwan.net.tw/XMLReleaseAll_public/v2.0/Zh_tw/Hotel-json.zip"
DATASET_NAME = "旅館民宿 - 觀光資訊資料庫"
DATASET_STANDARD = "觀光資料標準 V2.1"
DATASET_PROVIDER = "交通部觀光署"
USER_AGENT = "MOTRIX-ERP/1.0 (lodging nearby; contact your MOTRIX administrator)"

FETCH_ENV = "MOTRIX_LODGING_FETCH"
#: 字面值留著給「出貨預設關」的守門；環境變數在讀的那一端（同標案雷達 radar_on 的理由）
LODGING_FETCH_ENABLED = False

MIN_SUCCESS_INTERVAL = timedelta(hours=24)
FAILURE_COOLDOWN = timedelta(hours=1)
#: 每日自動更新：這個鐘點之後、當天還沒成功過才下載（來源每日更新一次；避開上班時段）
DAILY_REFRESH_HOUR = 3
#: 自動更新的最短成功間隔：比手動的 24 小時短，否則固定鐘點的檢查會被前一天的成功時間卡住而每天往後漂
SCHEDULED_MIN_INTERVAL = timedelta(hours=20)
_DAILY_FIRST_DELAY_SECONDS = 120
_DAILY_CHECK_SECONDS = 3600
FETCH_TIMEOUT_SECONDS = 60
#: 整次下載的總時限（D 稽核 E2-S1：逾時只管單次讀取，對方慢慢送會一直握著更新鎖）
FETCH_TOTAL_SECONDS = 180
MAX_DOWNLOAD_BYTES = 50 << 20
MAX_UNZIP_TOTAL_BYTES = 200 << 20
#: zip 內只准這幾個檔名（2026-09-28 實測內容：HotelList.json＋manifest.csv＋兩個 schema csv）
ZIP_ALLOWED_NAMES = frozenset({"HotelList.json", "manifest.csv", "schema-HotelList.csv", "schema-HotelList-s.csv"})
ZIP_REQUIRED_NAME = "HotelList.json"
#: 快照超過這個天數 ⇒ 頁面提示「資料可能過舊」（不自動去抓）
STALE_DAYS = 30

STATE_SETTING = "lodging_fetch_state"

#: 觀光資料標準 §20 旅宿類型代碼
CLASS_LABELS = {1: "國際觀光旅館", 2: "一般觀光旅館", 3: "一般旅館", 4: "民宿", 9: "其他"}
HOTEL_CLASSES = (1, 2, 3)
HOMESTAY_CLASSES = (4,)

#: 台灣（含離島）座標的合理範圍：超出 ⇒ 該筆不收（資料錯，不猜）
_LAT_RANGE = (21.0, 27.0)
_LNG_RANGE = (116.0, 123.5)
#: 認得的筆數低於這個比例 ⇒ 整包當成「對方改版、認不得」拒絕（不讓半套資料取代完整快照）
MIN_RECOGNISED_RATIO = 0.9

_REFRESH_LOCK = threading.Lock()


class SourceError(Exception):
    """下載、解壓或解析失敗；訊息給人看（會寫進狀態與畫面）。"""


def fetch_on() -> bool:
    """出貨預設關；只有 `MOTRIX_LODGING_FETCH=1` 才開。判準是 `== "1"`，不是真假值（`"0"` 也是非空字串）。"""
    return LODGING_FETCH_ENABLED or os.getenv(FETCH_ENV) == "1"


def _now() -> datetime:
    return datetime.now()


# ── 狀態 ─────────────────────────────────────────────────────────────────────

def fetch_state() -> dict:
    s = _get_setting(STATE_SETTING, None)
    return s if isinstance(s, dict) else {}


def _parse_ts(v):
    try:
        return datetime.fromisoformat(v) if v else None
    except (TypeError, ValueError):
        return None


def next_allowed_at(state: dict, now: datetime, min_interval: timedelta = MIN_SUCCESS_INTERVAL):
    """下一次可以下載的時間；None＝現在就可以。"""
    cands = []
    ok = _parse_ts(state.get("last_success_at"))
    if ok:
        cands.append(ok + min_interval)
    bad = _parse_ts(state.get("last_failure_at"))
    if bad and (not ok or bad > ok):
        cands.append(bad + FAILURE_COOLDOWN)
    t = max(cands) if cands else None
    return t if (t and t > now) else None


def catalog_state(conn) -> dict:
    """本機快照：筆數與資料日期。沒有快照 ⇒ count=0、dataset_updated_at=''（查詢端據此回 unavailable，不回 0 筆）。"""
    row = conn.execute("SELECT COUNT(*) AS n, MAX(dataset_updated_at) AS d FROM lodging_catalog").fetchone()
    n = int(row["n"] or 0)
    d = row["d"] or ""
    stale = False
    dt = _parse_ts(d[:19]) if d else None
    if dt:
        stale = (_now() - dt) > timedelta(days=STALE_DAYS)
    return {"count": n, "dataset_updated_at": d, "stale": stale}


# ── 下載與解壓 ────────────────────────────────────────────────────────────────

def fetch_raw(url: str = DATASET_URL) -> bytes:
    """下載 zip（有大小上限與逾時）。測試換掉這一支；它是唯一會對外連線的地方。"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    deadline = time.monotonic() + FETCH_TOTAL_SECONDS
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:  # noqa: S310（固定網址）
        buf = io.BytesIO()
        while True:
            if time.monotonic() > deadline:
                raise SourceError("下載超過 %d 秒總時限，已中止" % FETCH_TOTAL_SECONDS)
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            buf.write(chunk)
            if buf.tell() > MAX_DOWNLOAD_BYTES:
                raise SourceError("下載超過 %d MB 上限，已中止" % (MAX_DOWNLOAD_BYTES >> 20))
        return buf.getvalue()


_BAD_NAME = re.compile(r"(^[/\\])|(^[A-Za-z]:)|(\.\.)|\\")


def safe_unzip(blob: bytes, allow=ZIP_ALLOWED_NAMES, max_total=MAX_UNZIP_TOTAL_BYTES) -> dict:
    """zip → {檔名: bytes}，只在記憶體裡。任一項不合 ⇒ SourceError（整包拒絕）。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as e:
        raise SourceError("下載的檔案不是有效的 zip：%s" % e)
    infos = zf.infolist()
    total = 0
    for info in infos:
        name = info.filename
        if _BAD_NAME.search(name):
            raise SourceError("zip 內含不安全的路徑：%r" % name)
        if name not in allow:
            raise SourceError("zip 內有未預期的檔案：%r" % name)
        total += info.file_size
        if total > max_total:
            raise SourceError("zip 解壓後超過 %d MB 上限" % (max_total >> 20))
    out = {}
    read_total = 0
    for info in infos:
        with zf.open(info) as f:
            data = f.read(info.file_size + 1)
        if len(data) != info.file_size:
            raise SourceError("zip 內 %s 的實際大小與宣告不符" % info.filename)
        read_total += len(data)
        if read_total > max_total:
            raise SourceError("zip 解壓後超過 %d MB 上限" % (max_total >> 20))
        out[info.filename] = data
    if ZIP_REQUIRED_NAME not in out:
        raise SourceError("zip 內沒有 %s" % ZIP_REQUIRED_NAME)
    return out


# ── 解析 ─────────────────────────────────────────────────────────────────────

def _int_or_none(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _row(h: dict, dataset_updated_at: str):
    """一筆官方資料 → catalog 列；認不得 ⇒ None。**不取電話、經營者、統編**（D 審 Q2）。"""
    if not isinstance(h, dict):
        return None
    sid, name = h.get("HotelID"), h.get("HotelName")
    lat, lng = _num(h.get("PositionLat")), _num(h.get("PositionLon"))
    classes = h.get("HotelClasses")
    if not (isinstance(sid, str) and sid.strip() and isinstance(name, str) and name.strip()):
        return None
    if lat is None or lng is None or not (_LAT_RANGE[0] <= lat <= _LAT_RANGE[1]) \
            or not (_LNG_RANGE[0] <= lng <= _LNG_RANGE[1]):
        return None
    if not (isinstance(classes, list) and classes and _int_or_none(classes[0]) in CLASS_LABELS):
        return None
    addr = h.get("PostalAddress") if isinstance(h.get("PostalAddress"), dict) else {}
    city = addr.get("City") if isinstance(addr.get("City"), str) else ""
    town = addr.get("Town") if isinstance(addr.get("Town"), str) else ""
    street = addr.get("StreetAddress") if isinstance(addr.get("StreetAddress"), str) else ""
    lic = h.get("HotelLicenseNumber")
    room = h.get("RoomInfo")
    upd = h.get("UpdateTime")
    lo, hi = _int_or_none(h.get("LowestPrice")), _int_or_none(h.get("CeilingPrice"))
    return {
        "source": SOURCE_KEY, "source_id": sid.strip(),
        "license_no": lic.strip() if isinstance(lic, str) else "",
        "name": name.strip(), "class": _int_or_none(classes[0]),
        "city": city, "town": town, "address": city + town + street,
        "lat": lat, "lng": lng,
        "price_low": lo if (lo is not None and lo > 0) else None,
        "price_high": hi if (hi is not None and hi > 0) else None,
        "room_info": room.strip() if isinstance(room, str) else "",
        "record_updated_at": upd if isinstance(upd, str) else "",
        "dataset_updated_at": dataset_updated_at,
    }


def parse_dataset(raw: bytes) -> dict:
    """HotelList.json → {dataset_updated_at, rows, skipped}。形狀不對或認得的太少 ⇒ SourceError。"""
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise SourceError("HotelList.json 不是有效的 JSON：%s" % e)
    if not isinstance(doc, dict) or not isinstance(doc.get("Hotels"), list):
        raise SourceError("HotelList.json 結構不符（缺 Hotels 清單），可能是來源改版")
    upd = doc.get("UpdateTime")
    if not (isinstance(upd, str) and _parse_ts(upd[:19])):
        raise SourceError("HotelList.json 缺有效的 UpdateTime，可能是來源改版")
    hotels = doc["Hotels"]
    rows, seen = [], set()
    for h in hotels:
        r = _row(h, upd)
        if r is None or r["source_id"] in seen:
            continue
        seen.add(r["source_id"])
        rows.append(r)
    if not rows or len(rows) < len(hotels) * MIN_RECOGNISED_RATIO:
        raise SourceError("可辨識的旅宿只有 %d／%d 筆，低於 %d%%，整批不採用（可能是來源改版）"
                          % (len(rows), len(hotels), int(MIN_RECOGNISED_RATIO * 100)))
    return {"dataset_updated_at": upd, "rows": rows, "skipped": len(hotels) - len(rows)}


_COLS = ("source", "source_id", "license_no", "name", "class", "city", "town", "address", "lat", "lng",
         "price_low", "price_high", "room_info", "record_updated_at", "dataset_updated_at")


def replace_catalog(conn, rows) -> None:
    """整批替換（同一筆交易；例外 ⇒ write_txn 撤回並關連線，舊快照不動）。"""
    from core.txn import write_txn
    with write_txn(conn):
        conn.execute("DELETE FROM lodging_catalog")
        conn.executemany(
            "INSERT INTO lodging_catalog (%s) VALUES (%s)" % (",".join(_COLS), ",".join("?" * len(_COLS))),
            [tuple(r[c] for c in _COLS) for r in rows])
        conn.commit()


# ── 對外：更新 ────────────────────────────────────────────────────────────────

def refresh(min_interval: timedelta = MIN_SUCCESS_INTERVAL) -> dict:
    """最高管理者按「更新旅宿資料」或每日自動更新。回 {ok, reason?, message, ...}；不丟例外給端點。"""
    now = _now()
    if is_demo_mode():
        return {"ok": False, "reason": "demo", "message": "展示模式不對外連線，無法更新旅宿資料"}
    if not fetch_on():
        return {"ok": False, "reason": "switch_off",
                "message": "旅宿資料下載未開啟（需要 %s=1，重啟服務後生效）" % FETCH_ENV}
    state = fetch_state()
    nxt = next_allowed_at(state, now, min_interval)
    if nxt:
        return {"ok": False, "reason": "rate_limited", "next_allowed_at": nxt.isoformat(timespec="seconds"),
                "message": "距離上次下載未滿間隔，下次可更新時間：%s" % nxt.strftime("%Y-%m-%d %H:%M")}
    if not _REFRESH_LOCK.acquire(blocking=False):
        return {"ok": False, "reason": "busy", "message": "旅宿資料正在更新中"}
    try:
        try:
            blob = fetch_raw(DATASET_URL)
            files = safe_unzip(blob)
            parsed = parse_dataset(files[ZIP_REQUIRED_NAME])
            conn = get_db()
            try:
                replace_catalog(conn, parsed["rows"])
            finally:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
        except Exception as e:  # noqa: BLE001  ── 任何失敗：舊快照不動、記原因
            msg = e.args[0] if (isinstance(e, SourceError) and e.args) else "%s: %s" % (type(e).__name__, e)
            logger.error("lodging refresh failed: %s", msg)
            state = dict(fetch_state(), last_failure_at=now.isoformat(timespec="seconds"), last_error=msg)
            _set_setting(STATE_SETTING, state)
            return {"ok": False, "reason": "fetch_failed", "message": "更新失敗：%s（舊資料照常可查）" % msg}
        state = dict(fetch_state(), last_success_at=now.isoformat(timespec="seconds"), last_error="",
                     dataset_updated_at=parsed["dataset_updated_at"], count=len(parsed["rows"]),
                     skipped=parsed["skipped"])
        _set_setting(STATE_SETTING, state)
        return {"ok": True, "count": len(parsed["rows"]), "skipped": parsed["skipped"],
                "dataset_updated_at": parsed["dataset_updated_at"],
                "message": "已更新 %d 筆旅宿資料" % len(parsed["rows"])}
    finally:
        _REFRESH_LOCK.release()


# ── 每日自動更新 ──────────────────────────────────────────────────────────────

def daily_due(state: dict, now: datetime) -> bool:
    """今天該不該自動更新：過了 `DAILY_REFRESH_HOUR` 點、而且今天還沒成功更新過。"""
    if now.hour < DAILY_REFRESH_HOUR:
        return False
    ok = _parse_ts(state.get("last_success_at"))
    return not ok or ok.date() < now.date()


def run_daily_refresh():
    """排程的一輪。回 None＝這輪不用做（開關關、展示模式、今天已更新過）；否則回 `refresh()` 的結果。"""
    if not fetch_on() or is_demo_mode():
        return None
    if not daily_due(fetch_state(), _now()):
        return None
    result = refresh(min_interval=SCHEDULED_MIN_INTERVAL)
    if result.get("ok"):
        logger.info("lodging daily refresh: %s", result.get("message"))
    elif result.get("reason") not in ("rate_limited", "busy"):
        logger.warning("lodging daily refresh: %s", result.get("message"))
    return result


def schedule_daily_refresh():
    """啟動時呼叫一次：**立即返回**；第一輪在背景 daemon Timer（短延遲）跑，之後每小時檢查一次。

    形狀照標案雷達 `schedule_tender_scan`（B54：不可在啟動路徑同步下載，會拖垮套用後的健康檢查）。
    ⚠️ `threading.Timer` 走模組屬性，monkeypatch 才打得到。
    """
    t = threading.Timer(_DAILY_FIRST_DELAY_SECONDS, _daily_tick)
    t.daemon = True
    t.start()


def _daily_tick():
    """跑一輪再排下一輪；重排放在 `finally`：丟一次例外也不會讓排程靜默死亡。"""
    try:
        run_daily_refresh()
    except Exception:  # noqa: BLE001
        logger.exception("lodging daily refresh failed")
    finally:
        t = threading.Timer(_DAILY_CHECK_SECONDS, _daily_tick)
        t.daemon = True
        t.start()
