# -*- coding: utf-8 -*-
"""M01 案件的每日到期檢查（2026-09-26 自 routers/daily_tasks.py 搬出，M12 搬遷前置）。

案件執行進度到期、案件專案期間超期、設備保固到期。原本寄生在 M12 每日任務的 08:00 排程裡 ⇒
停用每日任務會連帶停掉案件的提醒。現在以 `daily.check` 提供者登記給 L1 執行器（helpers/daily_checks.py）。
程式碼逐字搬移；測試 patch 的名字（notify_* 等）是本模組的屬性。
"""
import calendar
import hashlib
import json
import os
import threading
from datetime import date as _date, timedelta as _timedelta, datetime, timezone as _timezone
from typing import Optional, List

from db import get_db, spawn_bg_thread
from helpers import (
    _notify, _purge_notifications,
    notify_daily_task_assigned, notify_daily_task_completed, notify_daily_task_overdue,
    notify_daily_task_overdue_manager,
    notify_daily_task_edited, notify_warranty_expiry, notify_range_task_deadline, _warranty_expiry,
    notify_case_stage_deadline, notify_case_stage_deadline_manager,
    notify_case_project_overdue,
    notify_cert_expiry, notify_backup_stale, notify_disk_space_low,
    notify_module_activity,
    _get_setting, _set_setting, notify_approval_reminder, _workdays_elapsed,
)
from helpers import email_notify as _en                    # noqa: E402
from helpers.case_access import case_owner_username        # noqa: E402
from helpers.email_notify import (            # noqa: E402
    SEND_SENT as _SEND_SENT,
    SEND_PERMANENT_FAIL as _SEND_PERMANENT_FAIL,
    SEND_UNKNOWN as _SEND_UNKNOWN,
)

import logging as _log
_logger = _log.getLogger(__name__)

# 頂層 import：提醒信的兩個信件類型（payable_due_soon／today）在 import 時登記；原本等到第一次每日檢查才 import，
# 在那之前通知矩陣（與收件設定頁）看不到這兩列、也配不到行事曆「付款待辦」。
from modules.case import payable_reminders  # noqa: E402
from modules.case.quotations import is_historical_json as _is_hist, sql_hist_hint as _hist_hint  # noqa: E402  T70 補登單靜音


# ── 案件階段到期（T84：補三個既有的洞）──────────────────────────────────────────────────────────
# 去重鍵 `casestage_notif.{案號}.{階段id}.{帳號}.{3d|deadline}`（格式不變，舊鍵照樣有效 ⇒ 上線當下不會重發）。鍵的值：
#   "<日期>"          ＝已處理（舊版寫的就是這種；最終狀態）
#   "p:<旗標>:<日期>"  ＝站內通知已送（與鍵同一筆交易寫入），外部通道（信件／LINE）還沒確定送出；旗標 a＝負責人那一封已送、m＝主管那一封已送
# 洞 1（只寫不修）：每次掃描結尾修剪——只留「還沒完成、到期日 ≥ 今天－1 天」的階段的鍵（與 `caseproj_notif` 同一個「只留還活著的」慣例）。
# 洞 2（逐階段發）：同一個人同一天的階段彙整成一則站內通知＋一封信（主管同理一人一封）；只有一個階段時內容與舊版相同。
# 洞 3（先寫鍵再發送、發送在 daemon thread）：站內通知與鍵同交易；信件改成同步等結果，寄出（或結果不明／永久失敗／沒有收件人）才把鍵寫成最終；
#   暫時失敗（連續 3 封才停止本輪；單一收件人壞掉不擋後面的人）或這台機器略過信件（不停——LINE 與信件結果無關）⇒ 鍵停在 p: ⇒ 到期日之前每次每日檢查只重試外部通道，**不會重發站內通知**；最多重發一次，不會永遠漏發（重試窗口＝到期前 3 天～到期當天）。
# 不補發：只看「今天～今天＋3 天」到期的階段，過去已逾期的永遠不會被選到；首次嘗試仍只在到期前 3 天與當天兩個日子（與舊版相同），
#   「到期前 1～2 天」只用來重試已經有 p: 鍵的項目，沒有鍵的不會憑空新發。
def _send_stage_digest(items, **kw):
    """階段到期通知一人一封（彙整）、同步等結果（T84）；用模組屬性呼叫（`_en._x`），不 from-import L1 的底線名稱。測試 patch 這個名字。"""
    return _en._send_case_stage_digest(items, **kw)


_STAGE_GUARD_PREFIX = "casestage_notif."
_STAGE_MAIL_MAX_TRANSIENT = 3     # 連續幾封暫時失敗就停止本輪外部通道（每封最多等 SEND_WAIT_TIMEOUT_SECONDS）
_STAGE_GUARD_KEEP_DAYS = 1       # 到期日之後再留幾天才修剪（同一天重跑、時鐘誤差的緩衝）


def _stage_state(val):
    """鍵的值 ⇒ (kind, flags)：kind＝none／done／pending。"""
    if not val:
        return "none", ""
    sv = str(val)
    if sv.startswith("p:"):
        parts = sv.split(":", 2)
        return "pending", (parts[1] if len(parts) > 2 else "")
    return "done", ""


def _stage_put_states(conn, states: dict) -> None:
    now = datetime.now().isoformat()
    conn.executemany(
        "INSERT INTO system_settings (key, value_json, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
        [(k, json.dumps(v, ensure_ascii=False), now) for k, v in states.items()])


def _when_text(days_ahead: int) -> str:
    return "今日到期" if days_ahead <= 0 else f"{days_ahead} 天後到期"


def _prune_case_stage_guard_keys(live: set) -> None:
    """清掉不再需要的 `casestage_notif.*` 鍵（T84 洞 1）。`live`＝{(案號, 階段 id 字串)}：還沒完成、到期日 ≥ 今天－KEEP 的階段（由掃描本體
    查好傳進來——不在這裡另讀 case_stages）；不在裡面的（階段已刪除、已完成、早已過期）一律刪，過期的階段永遠不會再被掃到，留著沒有作用。
    看不懂格式的鍵不動（不刪自己不認得的東西）。"""
    conn = get_db()
    try:
        existing = [r["key"] for r in conn.execute(
            "SELECT key FROM system_settings WHERE key LIKE ?", (_STAGE_GUARD_PREFIX + "%",)).fetchall()]
        # 案號與帳號都可能含 "."，不能靠切字串還原；改成「還活著的階段的前綴 `案號.階段id.`」去比（寧可多留，不誤刪：前綴撞到別的階段只會讓鍵多留一天）
        prefixes = tuple(f"{_STAGE_GUARD_PREFIX}{q}.{i}." for q, i in live)
        stale = [k for k in existing
                 if (k.endswith(".3d") or k.endswith(".deadline")) and not k.startswith(prefixes)]    # 看不懂格式（不是 3d／deadline 結尾）的鍵不動
        if stale:
            conn.executemany("DELETE FROM system_settings WHERE key=?", [(k,) for k in stale])
            conn.commit()
            _logger.info("Pruned %d stale casestage_notif guard keys", len(stale))
    except Exception as exc:
        _logger.warning("_prune_case_stage_guard_keys failed: %s", exc)       # 收斂失敗不該讓每日檢查掛掉
    finally:
        conn.close()


def _check_case_stage_deadline() -> None:
    """Notify assignees of case execution-progress stages (case_stages) due in 3 days or due today, if not yet marked done.
    同一個人同一天彙整成一則；站內通知與去重鍵同交易；信件寄出才把鍵寫成最終（見上面的 T84 說明）。"""
    today     = _date.today()
    today_str = today.isoformat()
    live_stages = None            # 修剪用：還活著的階段（查不到＝None ⇒ 不修剪，絕不在不確定時刪鍵）
    try:
        conn = get_db()
        users   = conn.execute("SELECT id, username, display_name FROM users").fetchall()
        dn_map  = {u["username"]: (u["display_name"] or u["username"]) for u in users}
        uid_map = {u["id"]: u["username"] for u in users}
        dept_map = {
            r["username"]: r["department_id"]
            for r in conn.execute("SELECT username, department_id FROM users WHERE department_id IS NOT NULL").fetchall()
        }
        dept_mgr_username = {
            r["id"]: r["mgr_username"]
            for r in conn.execute("""
                SELECT d.id, u.username AS mgr_username FROM departments d
                JOIN users u ON u.id = d.manager_user_id WHERE u.active=1
            """).fetchall()
        }
        floor = (today - _timedelta(days=_STAGE_GUARD_KEEP_DAYS)).isoformat()
        live_stages = {(r["quote_no"], str(r["id"])) for r in conn.execute(
            "SELECT quote_no, id FROM case_stages WHERE done=0 AND due_date >= ?", (floor,)).fetchall()}
        # Phase 5（2026-08-23）：直接 JOIN case_stages 表，SQL 層用 done=0 AND due_date 篩出要處理的列（正規化橋樑已保證這張表是權威）。
        # T84：範圍改成「今天～今天＋3 天」——首次嘗試仍只在 3 天前與當天（下面判斷），中間兩天只用來重試已有 p: 鍵的項目。
        check_date_3d = (today + _timedelta(days=3)).isoformat()
        rows = conn.execute("""
            SELECT q.quote_no, q.customer_name, q.project_name, q.sales_person_id,
                   cs.id AS stage_id, cs.label, cs.due_date, cs.assigned_to,
                   """ + _hist_hint("q.data_json") + """
            FROM case_stages cs
            JOIN quotations q ON q.quote_no = cs.quote_no
            WHERE COALESCE(NULLIF(q.deal_tag,''), json_extract(q.data_json,'$.dealTag'), '') = '已成案'
              AND cs.done = 0
              AND cs.due_date BETWEEN ? AND ?
        """, (today_str, check_date_3d)).fetchall()
        states = {}
        for r in conn.execute("SELECT key, value_json FROM system_settings WHERE key LIKE ?", (_STAGE_GUARD_PREFIX + "%",)).fetchall():
            try:
                states[r["key"]] = json.loads(r["value_json"])
            except (TypeError, ValueError):
                states[r["key"]] = r["value_json"]
        conn.close()

        items = []                       # 每個 (階段, 負責人, 類型) 一筆
        for row in rows:
            if _is_hist(row["hist_dj"]):          # T70：補登的歷史案件不發階段到期提醒
                continue
            try:
                days_left = (_date.fromisoformat(row["due_date"]) - today).days
            except (TypeError, ValueError):
                continue
            primary = "3d" if row["due_date"] == check_date_3d else "deadline" if row["due_date"] == today_str else None
            assignees = list(json.loads(row["assigned_to"] or "[]"))
            if not assignees:
                fallback = uid_map.get(row["sales_person_id"])
                if fallback:
                    assignees = [fallback]
            for username in assignees:
                if not username:
                    continue
                for ty in ("3d", "deadline"):
                    key = f"{_STAGE_GUARD_PREFIX}{row['quote_no']}.{row['stage_id']}.{username}.{ty}"
                    kind, flags = _stage_state(states.get(key))
                    if kind == "done" or (kind == "none" and ty != primary):
                        continue
                    dept_id = dept_map.get(username)
                    mgr = dept_mgr_username.get(dept_id) if dept_id else None
                    items.append({"key": key, "stage_id": row["stage_id"], "kind": kind, "flags": flags, "username": username, "display": dn_map.get(username, username),
                                  "quote_no": row["quote_no"], "label": row["label"] or "", "due": row["due_date"], "days_left": days_left,
                                  "customer": row["customer_name"] or "", "project": row["project_name"] or "",
                                  "mgr": mgr if (mgr and mgr != username) else None})

        # ── 階段 1：站內通知（一人一則）＋ 鍵寫成 p:——同一筆交易（回滾＝兩者一起沒有，下次當作全新的再發）──────────────
        fresh = [i for i in items if i["kind"] == "none"]
        if fresh:
            by_user, by_mgr = {}, {}
            for it in fresh:
                by_user.setdefault(it["username"], []).append(it)
                if it["mgr"]:
                    by_mgr.setdefault(it["mgr"], []).append(it)
            from helpers.audit import _notify_in_txn
            wconn = get_db()
            try:
                for username, its in sorted(by_user.items()):
                    f = its[0]
                    if len(its) == 1:
                        _notify_in_txn(wconn, username, "case_stage_deadline", f["quote_no"], f"{f['quote_no']} · {f['label']}",
                                       "案件執行進度「" + f["label"] + "」" + _when_text(f["days_left"]))
                    else:
                        _notify_in_txn(wconn, username, "case_stage_deadline", f["quote_no"], f"{len(its)} 個案件階段即將到期",
                                       "；".join(f"{i['quote_no']}「{i['label']}」{_when_text(i['days_left'])}" for i in its)[:400])
                for mgr, its in sorted(by_mgr.items()):
                    f = its[0]
                    if len(its) == 1:
                        _notify_in_txn(wconn, mgr, "case_stage_deadline_manager", f["quote_no"], f"{f['quote_no']} · {f['label']}",
                                       f"部門成員 {f['display']} 負責的案件執行進度「{f['label']}」" + _when_text(f["days_left"]))
                    else:
                        _notify_in_txn(wconn, mgr, "case_stage_deadline_manager", f["quote_no"], f"部門成員 {len(its)} 個案件階段即將到期",
                                       "；".join(f"{i['display']}：{i['quote_no']}「{i['label']}」{_when_text(i['days_left'])}" for i in its)[:400])
                _stage_put_states(wconn, {it["key"]: f"p::{today_str}" for it in fresh})
                wconn.commit()
            except BaseException:
                try:
                    wconn.rollback()
                except Exception:                # noqa: BLE001
                    pass
                raise
            finally:
                wconn.close()
            for it in fresh:
                it["kind"] = "pending"
                try:                                                         # BP-4 S4：額外通知的事件（站內通知同一刻只發一次；連匯入失敗也不能中斷這一輪掃描）
                    from helpers.notify_actions import emit as _emit_event
                    _emit_event("case.deadline_near", {"quoteNo": it["quote_no"], "stage": it["label"], "dueDate": it["due"],
                                                       "daysLeft": it["days_left"], "assignee": it["username"]})
                except Exception:                                            # noqa: BLE001
                    _logger.warning("案件階段到期事件發佈失敗", exc_info=True)

        # ── 階段 2：外部通道（信件／LINE），一人一封、同步等結果；寄出才寫進度旗標 ──────────────────────────────────
        halted = False
        transient_run = [0]        # 連續暫時失敗次數（成功歸零）

        def _is_final(it):
            return "a" in it["flags"] and (not it["mgr"] or "m" in it["flags"])

        def _persist(its):
            """把這批項目的鍵依旗標寫回：負責人那封與（有主管的）主管那封都送了 ⇒ 最終（只留日期）；否則 p:<旗標>:<日期>。"""
            c = get_db()
            try:
                _stage_put_states(c, {it["key"]: (today_str if _is_final(it) else f"p:{it['flags']}:{today_str}") for it in its})
                c.commit()
                for it in its:
                    it["persisted"] = True
            finally:
                c.close()

        def _dispatch(its, flag, **kw):
            nonlocal halted
            out = {}
            who = kw.get("assignee_username") or ("m:" + kw.get("manager_username", ""))
            # LINE 已推播記號：不含日期——同一組階段隔天重試信件時 LINE 不重推（組成變了才是新的一則）
            lk = "casestage-%s:%s" % (who, hashlib.md5("|".join(sorted(i["key"] for i in its)).encode("utf-8"), usedforsecurity=False).hexdigest()[:10])
            seen, digest = set(), []                          # 同一階段（同一負責人）只列一次：3d 那封暫時失敗、到期日又有新的 deadline 項目時，同一階段會有兩筆（鍵兩把都要寫回，內容只列一次）
            for i in sorted(its, key=lambda x: x["days_left"]):
                if (i["quote_no"], i["stage_id"], i["username"]) not in seen:      # 含負責人：主管那封同一階段有兩位負責人時，兩位的名字都要列
                    seen.add((i["quote_no"], i["stage_id"], i["username"]))
                    digest.append(i)
            try:
                ok = _send_stage_digest([{k: i[k] for k in ("quote_no", "label", "due", "days_left", "customer", "project", "display")} for i in digest],
                                        out=out, line_key=lk, **kw)
            except Exception as exc:                                         # noqa: BLE001
                _logger.warning("_check_case_stage_deadline: 寄送例外（%s）：%s", who, exc)
                ok, out = False, {"outcome": _en.SEND_TRANSIENT_FAIL}
            if ok:
                transient_run[0] = 0
                for i in its:
                    if flag not in i["flags"]:
                        i["flags"] += flag
                _persist(its)
            elif out.get("outcome") == _en.SEND_TRANSIENT_FAIL:
                # 單一收件人的暫時失敗（信箱滿、灰名單 4xx）不該擋住後面每個人：連續 N 次才判定是整台 SMTP 的問題而停止本輪
                transient_run[0] += 1
                _logger.warning("_check_case_stage_deadline: 寄送暫時失敗（%s；連續第 %d 次；鍵停在 p:，下次只重試外部通道）", who, transient_run[0])
                if transient_run[0] >= _STAGE_MAIL_MAX_TRANSIENT:
                    halted = True
            else:
                # SKIPPED＝這台機器沒開信件／沒設 SMTP／開發機封鎖：`send_registered` 在動網路之前就回來（重試零成本），而且 LINE 與信件結果無關——
                # 不能停（停了後面的人收不到 LINE）。鍵留在 p:，不寫最終；之後有設好 SMTP 才會補寄。
                _logger.info("_check_case_stage_deadline: 這台機器略過信件（%s；%s）", who, out.get("outcome"))

        by_user_ext = {}
        for it in items:
            if "a" not in it["flags"]:
                by_user_ext.setdefault(it["username"], []).append(it)
        for username, its in sorted(by_user_ext.items()):
            if halted:
                break
            _dispatch(its, "a", assignee_username=username)
        by_mgr_ext = {}
        for it in items:
            if it["mgr"] and "m" not in it["flags"]:
                by_mgr_ext.setdefault(it["mgr"], []).append(it)
        for mgr, its in sorted(by_mgr_ext.items()):
            if halted:
                break
            _dispatch(its, "m", manager_username=mgr)
        _done_unwritten = [it for it in items if _is_final(it) and not it.get("persisted")]      # 旗標早就齊了、鍵卻還掛 p:（上次寫回前中斷）⇒ 收斂成最終
        if _done_unwritten:
            _persist(_done_unwritten)
        _logger.info("Case stage deadline check complete for %s", today_str)
    except Exception as exc:
        _logger.warning("_check_case_stage_deadline failed: %s", exc)
    finally:
        if live_stages is not None:
            _prune_case_stage_guard_keys(live_stages)


def _check_project_deadline() -> None:
    """停用（2026-08-26 專案管理併入案件管理）：專案管理業務端點/頁面已下線，
    projects 表不會再有新的 endDate 被設定，案件本身的階段到期提醒已有對應
    機制（見同檔 _check_case_stage_deadline()，走 case_stages），不需要重複
    維護兩套。函式保留空殼是因為既有 3 處呼叫點不用跟著改。"""
    pass


def _prune_case_project_guard_keys(live_keys: set) -> None:
    """清掉不再需要的 `caseproj_notif.*` guard key（2026-09-10 新增）。

    這些 key 每個超期案件、每個 7 天區間各寫一列進 `system_settings`，原本
    寫進去就永遠不刪——案件結案、期限被改正、案件被刪除之後，舊 key 全部
    留著；一個超期兩年的案件光自己就會累積約 104 列。這個專案已經為同一種
    「只寫不刪、預期會自然停止但其實不會」的模式付過代價：`module_versions`
    曾長到 626,725 列、約佔 301MB 資料庫裡的 270MB（見 db.py `_m035` 的
    註解）。與其等它長大，不如在每次掃描結束時順手收斂。

    保留規則：只留「目前仍超期的案件、且是本次算出來的當前區間」那些 key。
    比當前更早的區間永遠不會再被查詢（判斷式只問「這個區間寄過沒」），留著
    沒有任何作用，所以一併刪掉——結果是每個超期案件最多只佔 1 列。
    """
    conn = get_db()
    try:
        existing = [r["key"] for r in conn.execute(
            "SELECT key FROM system_settings WHERE key LIKE 'caseproj_notif.%'"
        ).fetchall()]
        stale = [k for k in existing if k not in live_keys]
        if stale:
            conn.executemany("DELETE FROM system_settings WHERE key=?", [(k,) for k in stale])
            conn.commit()
            _logger.info("Pruned %d stale caseproj_notif guard keys", len(stale))
    except Exception as exc:
        # 收斂失敗不該讓整個每日檢查掛掉——通知本身已經寄出去了
        _logger.warning("_prune_case_project_guard_keys failed: %s", exc)
    finally:
        conn.close()


def _check_case_project_timeline_deadline() -> None:
    """Scan active cases; notify admin if case project endDate is overdue. Re-send every 7 days."""
    today = _date.today()
    today_str = today.isoformat()
    live_guard_keys = set()
    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT quote_no, customer_name, project_name,
                   json_extract(data_json, '$.caseRecord.projectTimeline.endDate') AS end_date_json,
                   """ + _hist_hint() + """
            FROM quotations
            WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') != '已結案'
              AND json_extract(data_json, '$.caseRecord.projectTimeline.endDate') IS NOT NULL
        """).fetchall()
        conn.close()

        for row in rows:
            if _is_hist(row["hist_dj"]):          # T70：補登的歷史案件不發專案逾期提醒
                continue
            try:
                end_date_str = (row["end_date_json"] or "").strip('"')
                if not end_date_str:
                    continue
                end_date = _date.fromisoformat(end_date_str)
            except Exception:
                continue

            if end_date >= today:
                continue  # not yet overdue

            days_overdue = (today - end_date).days
            bucket = days_overdue // 7  # day 0-6 → bucket 0, day 7-13 → bucket 1, etc.
            guard_key = f"caseproj_notif.{row['quote_no']}.{bucket}"
            live_guard_keys.add(guard_key)
            if _get_setting(guard_key):
                continue  # already sent for this 7-day bucket

            _set_setting(guard_key, today_str)
            # 這裡刻意用 threading.Thread 而非 db.spawn_bg_thread()：本函式是
            # 排程觸發、不掛在任何 request 上，contextvar 本來就該是預設值，
            # 屬於 MOTRIX-ERP-QUICK.md §3.5 明列的例外 (a)。不要「順手改成
            # spawn_bg_thread」——那會讓它去複製一個根本不存在的 request context。
            threading.Thread(
                target=notify_case_project_overdue,
                args=(row["quote_no"], row["customer_name"] or "", row["project_name"] or "",
                      end_date_str, days_overdue),
                daemon=True,
            ).start()

        _prune_case_project_guard_keys(live_guard_keys)
        _logger.info("Case project timeline deadline check complete for %s", today_str)
    except Exception as exc:
        _logger.warning("_check_case_project_timeline_deadline failed: %s", exc)


_WARR_THRESHOLDS = (7, 30)  # days — must be in ascending order


def _check_warranty_expiry() -> None:
    """Scan active-case devices; send email once per device × threshold crossing."""
    today     = _date.today()
    today_str = today.isoformat()
    from helpers.alert_settings import warranty_mail_days
    _urgent, _early = warranty_mail_days()      # census #7：設定中心『保固郵件天數』（預設 7／30＝今天）
    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT quote_no, customer_name,
                   json_extract(data_json, '$.caseRecord') AS cr_json
            FROM quotations
            WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') = '已成案'
              AND json_extract(data_json, '$.caseRecord') IS NOT NULL
        """).fetchall()

        owner_cache = {}      # quote_no → 業務帳號（走 sales_person_id 外鍵；沒有／已停用 ⇒ ""，只寄群組收件人）

        def _owner(qn):
            if qn not in owner_cache:
                try:
                    owner_cache[qn] = case_owner_username(conn, qn) or ""
                except Exception as exc:
                    _logger.warning("_check_warranty_expiry: 查案件業務帳號失敗（%s）：%s", qn, exc)
                    owner_cache[qn] = ""
            return owner_cache[qn]

        halted = False        # 寄送暫時失敗／機器略過 ⇒ 本輪不再往下寄（逐台各等一次會把後面的每日檢查拖很久；記號沒寫，明天補）
        for row in rows:
            if halted:
                break
            try:
                cr = json.loads(row["cr_json"] or "{}")
            except Exception:
                continue
            devices = cr.get("devices") or []
            for dev in devices:
                ws = dev.get("warrantyStart") or ""
                wm = dev.get("warrantyMonths")
                if not ws or not wm:
                    continue
                expiry, days_left = _warranty_expiry(ws, wm)
                if expiry is None or days_left > _early:
                    continue

                threshold = _urgent if days_left <= _urgent else _early
                sn = (dev.get("sn") or dev.get("mac") or dev.get("name") or "")[:32]
                guard_key = f"warranty_notif.{row['quote_no']}_{sn}_{threshold}"
                if _get_setting(guard_key):
                    continue  # already sent for this threshold

                # 先寄成功才寫已通知記號：SMTP 暫時失敗（或這台機器沒設 SMTP）⇒ 不寫，明天的每日檢查會補寄。
                # 收件人＝案件業務（sales_person_id 外鍵解出的帳號；舊作法拿顯示名當帳號比對，名字≠帳號就收不到）＋群組收件人。
                out = {}
                try:
                    sent = _en._send_warranty_expiry(
                        dev.get("name") or sn or "未知設備", row["customer_name"] or "", row["quote_no"],
                        days_left, expiry.isoformat(), owner_username=_owner(row["quote_no"]), out=out, sn=sn)
                except Exception as exc:
                    _logger.warning("_check_warranty_expiry: 寄送失敗（%s／%s）：%s", row["quote_no"], sn, exc)
                    sent, out = False, {"outcome": _en.SEND_TRANSIENT_FAIL}
                if sent:
                    _set_setting(guard_key, today_str)
                elif out.get("outcome") in (_en.SEND_TRANSIENT_FAIL, _en.SEND_SKIPPED):
                    _logger.warning("_check_warranty_expiry: 寄送%s，本輪停止後續保固信（%s／%s 起；記號未寫，下次每日檢查重試）",
                                    out.get("outcome"), row["quote_no"], sn)
                    halted = True
                    break
        _logger.info("Warranty expiry check complete for %s", today_str)
    except Exception as exc:
        _logger.warning("_check_warranty_expiry failed: %s", exc)
    finally:
        try:
            conn.close()
        except Exception:
            pass



# ── 階段 2（MAIL-CAL）：日期型行事曆事件的每日對帳；預設關，關著＝不讀資料庫、零 Google 流量 ──────
# 事件內容不含金額；日期已過不建（helpers/calendar_sync.py 的 Q9 規則）。與上面寄信的 guard 完全獨立。
def _deal_tag(row, data) -> str:
    """與寄信端 SQL 同義：欄位 deal_tag 優先，空才看 data_json.dealTag。（對帳掃描改在 Python 判斷——json_extract 棘輪只准減少。）"""
    return row["deal_tag"] or (data.get("dealTag") if isinstance(data, dict) else "") or ""


def _sync_warranty_calendar() -> None:
    from helpers.calendar_sync import is_active, sync_dated_events
    if not is_active("warranty_expiry"):          # 事件種類或行事曆總開關關著 ⇒ 連來源查詢都不做
        return
    current = {}
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT quote_no, customer_name, deal_tag, data_json FROM quotations
        """).fetchall()
    finally:
        conn.close()
    for row in rows:
        try:
            data = json.loads(row["data_json"] or "{}")
        except Exception:
            continue
        if _deal_tag(row, data) != "已成案":
            continue
        devices = (data.get("caseRecord") or {}).get("devices") or []
        seen = set()
        for i, dev in enumerate(devices):
            ws, wm = dev.get("warrantyStart") or "", dev.get("warrantyMonths")
            if not ws or not wm:
                continue
            expiry, _left = _warranty_expiry(ws, wm)
            if expiry is None:
                continue
            sn = (dev.get("sn") or dev.get("mac") or dev.get("name") or "")[:32]
            name = dev.get("name") or sn or "未知設備"
            customer = row["customer_name"] or ""
            dkey = f"{row['quote_no']}#{dev.get('id') if dev.get('id') not in (None, '') else 'i%d' % i}"   # 設備自己的 id（序號可能重複或空白）；舊資料沒有 id ⇒ 列序
            if dkey in seen:
                dkey += "~%d" % i
            seen.add(dkey)
            current[dkey] = (
                expiry,
                f"保固到期：{name}（{customer}）" if customer else f"保固到期：{name}",
                f"案號：{row['quote_no']}\n客戶：{customer}\n設備：{name}\n保固到期日：{expiry.isoformat()}")
    sync_dated_events("warranty_expiry", current)


def _sync_project_end_calendar() -> None:
    from helpers.calendar_sync import is_active, sync_dated_events
    if not is_active("project_end"):          # 事件種類或行事曆總開關關著 ⇒ 連來源查詢都不做
        return
    current = {}
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT quote_no, customer_name, project_name, deal_tag, data_json FROM quotations
        """).fetchall()
    finally:
        conn.close()
    for row in rows:
        try:
            data = json.loads(row["data_json"] or "{}")
            end_date = _date.fromisoformat(str(((data.get("caseRecord") or {}).get("projectTimeline") or {}).get("endDate") or ""))
        except Exception:
            continue
        if _deal_tag(row, data) == "已結案" or (data.get("approval") or {}).get("historical") is True:      # T70：補登的歷史案件不進「專案預計完成」行事曆
            continue
        label = row["project_name"] or row["quote_no"]
        current[row["quote_no"]] = (
            end_date, f"專案預計完成：{label}",
            f"案號：{row['quote_no']}\n客戶：{row['customer_name'] or ''}\n專案：{row['project_name'] or ''}\n預計完成日：{end_date.isoformat()}")
    sync_dated_events("project_end", current)


# ── `daily.check` 提供者（INTEGRATION-POINTS IP-11）─────────────────────────────
def run_daily_checks(mode: str = "daily") -> None:
    """mode：daily（08:00）／startup（啟動補跑）。案件類檢查都看未來，兩種模式做一樣的事。"""
    try:                                                 # 補登歷史案件開關的自動關閉（T71）：放最前面——後面的檢查出例外也不影響它
        from modules.case.api.quotations import expire_backfill_if_due
        expire_backfill_if_due()
    except Exception as exc:                             # noqa: BLE001
        _logger.warning("expire_backfill_if_due failed: %s", exc)
    _check_warranty_expiry()
    _check_case_stage_deadline()
    _check_case_project_timeline_deadline()
    _check_project_deadline()
    payable_reminders.run()                              # 預定付款日提醒信（3 天前＋當天；2026-10-05）
    for fn in (_sync_warranty_calendar, _sync_project_end_calendar):      # 階段 2；各自吞例外，互不影響
        try:
            fn()
        except Exception as exc:
            _logger.warning("%s failed: %s", fn.__name__, exc)


from core import registry as _registry  # noqa: E402
