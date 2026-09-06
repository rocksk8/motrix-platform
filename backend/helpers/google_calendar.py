"""Google 行事曆整合 — Phase 1（系統 → 行事曆，push only，2026-08-21）。

刻意不裝 google-api-python-client / google-auth 那一整包套件（正式機目前依賴
極簡，requirements.txt 只有 fastapi/uvicorn/pydantic/aiofiles），改用內建
urllib.request 直接打 OAuth2 token endpoint + Calendar API v3 REST 介面，
足夠支撐「換 access token、建立整天事件」這兩個動作，不需要完整 SDK。

授權模式：Desktop app 類型 OAuth Client + 一次性 loopback 授權（見
scripts/setup_google_calendar_oauth.py），換到的 refresh_token 存在
system_settings.google_calendar.refresh_token，之後這裡的 _get_access_token()
用它自動換短效 access_token（記憶體快取，過期前重新換發，不需要人工介入）。

三個 push_event_for_*() 都是 fire-and-forget：任何失敗只記 log，不拋出，
一律搭配 spawn_bg_thread() 呼叫，絕不能因為行事曆推送失敗而擋住核准/成案
這個主要動作（比照 email_notify.py 的既有慣例）。
"""
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

from .settings import _get_setting

logger = logging.getLogger(__name__)

_TOKEN_URL    = "https://oauth2.googleapis.com/token"
_EVENTS_BASE  = "https://www.googleapis.com/calendar/v3/calendars"
_TOKEN_MARGIN = 60  # 秒，快取的 access token 在真正過期前這麼多秒就視為失效，提早換新

_token_cache = {"access_token": None, "expires_at": 0}


def _cfg() -> dict:
    return _get_setting("google_calendar", {}) or {}


def _calendar_id() -> str:
    return _cfg().get("calendar_id") or "primary"


def _post_form(url: str, data: dict) -> dict:
    """application/x-www-form-urlencoded POST（只給 OAuth token endpoint 用）。"""
    payload = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=payload, method="POST",
                                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google OAuth 錯誤 {e.code}：{err_body}") from e


def _json_request(url: str, method: str, token: str, body: dict = None) -> dict:
    """application/json 的 Calendar API 請求。"""
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=payload, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json; charset=utf-8",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google API 錯誤 {e.code}：{err_body}") from e


def _get_access_token() -> str:
    """用 refresh_token 換短效 access_token，記憶體快取到快過期前才重新換。"""
    now = time.time()
    if _token_cache["access_token"] and now < _token_cache["expires_at"] - _TOKEN_MARGIN:
        return _token_cache["access_token"]

    cfg = _cfg()
    client_id     = cfg.get("client_id") or ""
    client_secret = cfg.get("client_secret") or ""
    refresh_token = cfg.get("refresh_token") or ""
    if not (client_id and client_secret and refresh_token):
        raise RuntimeError("Google 行事曆尚未完成授權（缺少 client_id/client_secret/refresh_token）")

    resp = _post_form(_TOKEN_URL, {
        "client_id":     client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type":    "refresh_token",
    })
    access_token = resp.get("access_token")
    expires_in   = resp.get("expires_in", 3600)
    if not access_token:
        raise RuntimeError(f"換發 access_token 失敗：{resp}")
    _token_cache["access_token"] = access_token
    _token_cache["expires_at"]   = now + int(expires_in)
    return access_token


def _events_call(method: str, path: str = "", body: dict = None) -> dict:
    """打 Calendar API v3 的 events 相關端點。path 例如 '' (list/insert) 或 '/{event_id}' (get/patch/delete)。"""
    cfg = _cfg()
    if not cfg.get("enabled"):
        raise RuntimeError("Google 行事曆整合未啟用")
    token = _get_access_token()
    url = f"{_EVENTS_BASE}/{urllib.parse.quote(_calendar_id(), safe='')}/events{path}"
    return _json_request(url, method, token, body)


def _create_all_day_event(summary: str, description: str, event_date: date) -> str:
    """建立一個整天事件（Google 的整天事件 end.date 是不含當天的隔一天）。回傳 event id。"""
    body = {
        "summary":     summary,
        "description": description,
        "start": {"date": event_date.isoformat()},
        "end":   {"date": (event_date + timedelta(days=1)).isoformat()},
    }
    resp = _events_call("POST", "", body)
    event_id = resp.get("id")
    if not event_id:
        raise RuntimeError(f"建立行事曆事件失敗，回應無 id：{resp}")
    return event_id


def _notify_push_failure(context_label: str, error: str) -> None:
    """重試後仍失敗，通知全部 active superadmin——2026-08-22 補上，先前失敗完全
    只會記一行 log，沒有人會主動去翻，導致「這筆核准其實沒真的推上行事曆」
    沒有任何管道會被發現。"""
    try:
        from db import get_db
        from .audit import _notify
        conn = get_db()
        supers = [r["username"] for r in conn.execute(
            "SELECT username FROM users WHERE role='superadmin' AND active=1"
        ).fetchall()]
        conn.close()
        for username in supers:
            _notify(username, "google_calendar_push_failed", "", context_label,
                    f"Google 行事曆推送失敗（已自動重試一次仍失敗）：{context_label}。錯誤：{error}")
    except Exception as exc:
        logger.warning("_notify_push_failure failed: %s", exc)


def _create_event_with_retry(summary: str, description: str, event_date: date) -> str:
    """建立整天事件，失敗時等待數秒後重試一次；重試後仍失敗會另外通知全部
    active superadmin（不只是記 log）。一次性重試，不做無限重試，避免背景
    執行緒卡太久。"""
    try:
        return _create_all_day_event(summary, description, event_date)
    except Exception as first_exc:
        logger.warning("行事曆事件建立失敗，5 秒後重試一次：%s — %s", summary, first_exc)
        time.sleep(5)
        try:
            return _create_all_day_event(summary, description, event_date)
        except Exception as second_exc:
            _notify_push_failure(summary, str(second_exc))
            raise


def _update_all_day_event(event_id: str, summary: str, description: str, event_date: date) -> str:
    """PATCH 既有整天事件的內容/日期，回傳事件 id（正常情況下跟傳入的 event_id 相同）。"""
    body = {
        "summary":     summary,
        "description": description,
        "start": {"date": event_date.isoformat()},
        "end":   {"date": (event_date + timedelta(days=1)).isoformat()},
    }
    resp = _events_call("PATCH", f"/{urllib.parse.quote(event_id, safe='')}", body)
    new_id = resp.get("id")
    if not new_id:
        raise RuntimeError(f"更新行事曆事件失敗，回應無 id：{resp}")
    return new_id


def _delete_event(event_id: str) -> None:
    _events_call("DELETE", f"/{urllib.parse.quote(event_id, safe='')}")


def _update_event_with_retry(event_id: str, summary: str, description: str, event_date: date) -> str:
    """更新既有事件；若該事件已在 Google 端被刪除（404，例如使用者手動刪掉），
    改為新建一筆並回傳新 id，避免「行事曆上事件被手動刪除」變成之後永遠更新失敗。"""
    try:
        return _update_all_day_event(event_id, summary, description, event_date)
    except RuntimeError as e:
        if "404" in str(e):
            logger.info("行事曆事件 %s 已不存在，改為新建：%s", event_id, summary)
            return _create_event_with_retry(summary, description, event_date)
        logger.warning("行事曆事件更新失敗，5 秒後重試一次：%s — %s", summary, e)
        time.sleep(5)
        try:
            return _update_all_day_event(event_id, summary, description, event_date)
        except Exception as second_exc:
            _notify_push_failure(summary, str(second_exc))
            raise


def _delete_event_with_retry(event_id: str) -> None:
    """刪除既有事件；404/410（已經不存在）視為成功，不重試。"""
    try:
        _delete_event(event_id)
    except RuntimeError as e:
        if "404" in str(e) or "410" in str(e):
            return
        logger.warning("行事曆事件刪除失敗，5 秒後重試一次：event %s — %s", event_id, e)
        time.sleep(5)
        try:
            _delete_event(event_id)
        except Exception as second_exc:
            logger.warning("行事曆事件刪除重試仍失敗，忽略（不影響任何業務流程）：%s", second_exc)


def create_test_event() -> str:
    """設定頁「測試連線」按鈕用：建立一個當天的測試事件，驗證整套授權/API 串接正常。"""
    today = date.today()
    return _create_all_day_event(
        "MOTRIX 測試事件",
        "此事件由 MOTRIX 專案管理系統的 Google 行事曆設定頁「測試連線」按鈕建立，"
        "確認無誤後可自行刪除。",
        today,
    )


# ── 三個觸發點（2026-08-21 這輪範圍）──────────────────────────────────────────
# 各自查一次最新資料、組整天事件內容、建立事件、把 event id 寫回 data_json——
# 這輪只做「新建」，不做「更新既有事件」，event id 先存起來供之後擴充用。
# 全部包在最外層 try/except：任何失敗只記 log，不能讓背景執行緒的例外影響任何東西。

def push_event_for_invoice_voucher(voucher_no: str) -> None:
    try:
        from db import get_db
        conn = get_db()
        row = conn.execute(
            "SELECT data_json, snapshot_json, amount FROM invoice_vouchers WHERE voucher_no=?", (voucher_no,)
        ).fetchone()
        if not row:
            conn.close()
            return
        snap = json.loads(row["snapshot_json"] or "{}")
        cname = snap.get("customerName") or ""
        amount = row["amount"] or 0
        event_id = _create_event_with_retry(
            f"開票申請憑據已核准 — {voucher_no}（{cname}）",
            f"開票申請憑據 {voucher_no} 已完成簽核核准。\n客戶：{cname}\n金額（含稅）：NT$ {amount:,.0f}",
            date.today(),
        )
        d = json.loads(row["data_json"] or "{}")
        d["googleCalendarEventId"] = event_id
        conn.execute("UPDATE invoice_vouchers SET data_json=? WHERE voucher_no=?",
                     (json.dumps(d, ensure_ascii=False), voucher_no))
        conn.commit()
        conn.close()
        logger.info("push_event_for_invoice_voucher: %s -> event %s", voucher_no, event_id)
    except Exception as exc:
        logger.warning("push_event_for_invoice_voucher(%r) failed: %s", voucher_no, exc)


def push_event_for_payment_request(request_no: str) -> None:
    try:
        from db import get_db
        conn = get_db()
        row = conn.execute(
            "SELECT data_json, snapshot_json, amount FROM payment_requests WHERE request_no=?", (request_no,)
        ).fetchone()
        if not row:
            conn.close()
            return
        snap = json.loads(row["snapshot_json"] or "{}")
        cname = snap.get("customerName") or ""
        amount = row["amount"] or 0
        event_id = _create_event_with_retry(
            f"請款單已核准 — {request_no}（{cname}）",
            f"請款單 {request_no} 已完成簽核核准。\n客戶：{cname}\n金額（含稅）：NT$ {amount:,.0f}",
            date.today(),
        )
        d = json.loads(row["data_json"] or "{}")
        d["googleCalendarEventId"] = event_id
        conn.execute("UPDATE payment_requests SET data_json=? WHERE request_no=?",
                     (json.dumps(d, ensure_ascii=False), request_no))
        conn.commit()
        conn.close()
        logger.info("push_event_for_payment_request: %s -> event %s", request_no, event_id)
    except Exception as exc:
        logger.warning("push_event_for_payment_request(%r) failed: %s", request_no, exc)


def push_event_for_shipping_note(note_no: str) -> None:
    try:
        from db import get_db
        conn = get_db()
        row = conn.execute(
            "SELECT data_json, customer_name, quote_no, ship_date FROM shipping_notes WHERE note_no=?", (note_no,)
        ).fetchone()
        if not row:
            conn.close()
            return
        cname = row["customer_name"] or ""
        # 事件日期用實際出貨日期，不是核准當下的日期——兩者常常不同天（可能先核准
        # 後出貨，也可能出貨日期早就填了才補送審），用出貨日期對照行事曆才有意義。
        ship_date_str = (row["ship_date"] or "").strip()
        try:
            event_date = date.fromisoformat(ship_date_str[:10]) if ship_date_str else date.today()
        except ValueError:
            event_date = date.today()
        event_id = _create_event_with_retry(
            f"出貨單已核准 — {note_no}（{cname}）",
            f"出貨單 {note_no} 已完成簽核核准。\n客戶：{cname}\n關聯案件：{row['quote_no'] or ''}\n出貨日期：{ship_date_str or '未填寫'}",
            event_date,
        )
        d = json.loads(row["data_json"] or "{}")
        d["googleCalendarEventId"] = event_id
        conn.execute("UPDATE shipping_notes SET data_json=? WHERE note_no=?",
                     (json.dumps(d, ensure_ascii=False), note_no))
        conn.commit()
        conn.close()
        logger.info("push_event_for_shipping_note: %s -> event %s", note_no, event_id)
    except Exception as exc:
        logger.warning("push_event_for_shipping_note(%r) failed: %s", note_no, exc)


def push_event_for_quotation_won(quote_no: str) -> None:
    try:
        from db import get_db
        conn = get_db()
        row = conn.execute(
            "SELECT data_json, customer_name, project_name, total FROM quotations WHERE quote_no=?", (quote_no,)
        ).fetchone()
        if not row:
            conn.close()
            return
        cname = row["customer_name"] or ""
        pname = row["project_name"] or ""
        total = row["total"] or 0
        event_id = _create_event_with_retry(
            f"報價單成案 — {quote_no}（{cname}）",
            f"報價單 {quote_no} 已標記為「已成案」。\n客戶：{cname}\n案件名稱：{pname}\n金額（含稅）：NT$ {total:,.0f}",
            date.today(),
        )
        d = json.loads(row["data_json"] or "{}")
        d["googleCalendarEventId"] = event_id
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?",
                     (json.dumps(d, ensure_ascii=False), quote_no))
        conn.commit()
        conn.close()
        logger.info("push_event_for_quotation_won: %s -> event %s", quote_no, event_id)
    except Exception as exc:
        logger.warning("push_event_for_quotation_won(%r) failed: %s", quote_no, exc)


# ── 2026-08-21g 擴充：業務開發轉建／案件停滯提醒／案件動態重要留言 ─────────────
# 這三類沒有既有的 data_json 可掛（dev_cases／case_updates 皆為輕量表），比照
# 「先建立、不做更新/刪除同步」的既有原則，不記錄 event id。

def push_event_for_dev_case_converted(case_id: int) -> None:
    try:
        from db import get_db
        conn = get_db()
        row = conn.execute(
            "SELECT case_name, customer_name, converted_quote_no FROM dev_cases WHERE id=?", (case_id,)
        ).fetchone()
        if not row or not row["converted_quote_no"]:
            conn.close()
            return
        cname = row["customer_name"] or ""
        event_id = _create_event_with_retry(
            f"業務開發案件轉建報價單 — {row['case_name']}（{cname}）",
            f"業務開發案件「{row['case_name']}」已轉建為報價單。\n客戶：{cname}\n報價單號：{row['converted_quote_no']}",
            date.today(),
        )
        conn.close()
        logger.info("push_event_for_dev_case_converted: %s -> event %s", case_id, event_id)
    except Exception as exc:
        logger.warning("push_event_for_dev_case_converted(%r) failed: %s", case_id, exc)


def push_event_for_dev_case_stale(case_id: int, case_name: str, customer_name: str, days: int) -> None:
    """呼叫端（_check_dev_case_stale()）已經用獨立於 email 的 guard key 判斷
    「這個停滯週期第一次跨過 30 天」才會呼叫這裡，這裡本身不重複判斷。"""
    try:
        event_id = _create_event_with_retry(
            f"業務開發案件停滯提醒 — {case_name}（{customer_name}）",
            f"業務開發案件「{case_name}」洽談中已 {days} 天未更新，請確認跟進進度。\n客戶：{customer_name}",
            date.today(),
        )
        logger.info("push_event_for_dev_case_stale: %s -> event %s", case_id, event_id)
    except Exception as exc:
        logger.warning("push_event_for_dev_case_stale(%r) failed: %s", case_id, exc)


# ── 2026-08-24：案件執行進度階段到期日（唯一需要真正 upsert 的事件類型）─────────
# 到期日常常會被使用者事後調整（延期），跟其他 6 種「只建立一次」的一次性事件
# 不同，這裡用 case_stages.google_calendar_event_id（DB v55）記住上一次建立的
# 事件 id，設定/變更到期日時改 PATCH 既有事件，清空到期日時改 DELETE，避免
# 行事曆上留一堆過期重複事件。

def push_event_for_case_stage_due(stage_id: int) -> None:
    try:
        from db import get_db
        conn = get_db()
        row = conn.execute("""
            SELECT cs.id, cs.label, cs.due_date, cs.quote_no, cs.google_calendar_event_id,
                   q.customer_name, q.project_name
            FROM case_stages cs JOIN quotations q ON q.quote_no = cs.quote_no
            WHERE cs.id=?
        """, (stage_id,)).fetchone()
        if not row:
            conn.close()
            return

        due_date_str  = (row["due_date"] or "").strip()
        existing_id   = row["google_calendar_event_id"] or ""
        cname, pname  = row["customer_name"] or "", row["project_name"] or ""
        case_label    = f"{row['quote_no']}（{cname}{'／' if cname and pname else ''}{pname}）"
        stage_label   = row["label"] or "執行階段"

        if not due_date_str:
            if existing_id:
                _delete_event_with_retry(existing_id)
                conn.execute("UPDATE case_stages SET google_calendar_event_id='' WHERE id=?", (stage_id,))
                conn.commit()
            conn.close()
            return

        try:
            event_date = date.fromisoformat(due_date_str[:10])
        except ValueError:
            conn.close()
            return

        summary     = f"案件執行進度到期 — {stage_label}（{case_label}）"
        description = f"案件 {case_label} 的執行進度階段「{stage_label}」到期日：{due_date_str}"

        if existing_id:
            event_id = _update_event_with_retry(existing_id, summary, description, event_date)
        else:
            event_id = _create_event_with_retry(summary, description, event_date)

        conn.execute("UPDATE case_stages SET google_calendar_event_id=? WHERE id=?", (event_id, stage_id))
        conn.commit()
        conn.close()
        logger.info("push_event_for_case_stage_due: %s -> event %s", stage_id, event_id)
    except Exception as exc:
        logger.warning("push_event_for_case_stage_due(%r) failed: %s", stage_id, exc)


def push_event_delete_for_case_stage(event_id: str) -> None:
    """階段本身被刪除時呼叫（呼叫端已從即將刪除的 row 取出 event_id）。"""
    try:
        _delete_event_with_retry(event_id)
        logger.info("push_event_delete_for_case_stage: deleted event %s", event_id)
    except Exception as exc:
        logger.warning("push_event_delete_for_case_stage(%r) failed: %s", event_id, exc)


def push_event_for_important_comment(update_id, quote_no: str, content: str, author_display: str) -> None:
    try:
        from db import get_db
        conn = get_db()
        row = conn.execute(
            "SELECT customer_name, project_name FROM quotations WHERE quote_no=?", (quote_no,)
        ).fetchone()
        conn.close()
        cname = (row["customer_name"] or "") if row else ""
        pname = (row["project_name"] or "") if row else ""
        label = f"{quote_no}（{cname}{'／' if cname and pname else ''}{pname}）"
        event_id = _create_event_with_retry(
            f"案件重要留言 — {label}",
            f"案件 {label} 有一則被標記為重要的留言。\n留言人：{author_display}\n內容：{content}",
            date.today(),
        )
        logger.info("push_event_for_important_comment: %s -> event %s", update_id, event_id)
    except Exception as exc:
        logger.warning("push_event_for_important_comment(%r) failed: %s", update_id, exc)
