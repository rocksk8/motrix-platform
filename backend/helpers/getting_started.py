# -*- coding: utf-8 -*-
"""「開始使用」7 步清單（選單去工程師化 批次「開始使用清單面板」，2026-11-13）：只讀偵測＋伺服器端進度。

[單位] helper:getting_started    [層] L1    [穩定度] 實驗
[公開介面] STEPS, STEP_IDS, STATE_KEY, MANUAL_DONE_IDS, overview, set_step
[規格] docs/platform/plans/SYSTEM-MENU-UX-PROPOSAL.md 第六節：7 步（公司資料／報價單樣式／人員與簽核／寄信／備份／LINE／匯入資料）；
    每步固定三件事：約幾分鐘、要準備什麼、做完怎麼確認；可中途離開，進度存伺服器端（公司層），換電腦、換人都能接著做；每步可略過、可回來。
[不變式]
    ①**完成狀態盡量自動偵測**，偵測只讀（不寫庫、不寫檔、不寄信、不連外）：公司資料＝`company_setup.status`；人員與簽核＝`org_gaps.check` 全綠（且已有一般同仁）；
      寄信＝稽核紀錄有「寄測試信成功」（`settings.email_notify.test` 只在寄成功後才寫）；備份＝稽核紀錄有備份成功（本機快照或雲端每日）；
      LINE＝已啟用且至少一位同仁綁定；匯入＝已經有客戶資料。
    ②偵測不到的才讓人手動確認（`MANUAL_DONE_IDS`：報價單樣式要「預覽出一張報價單」、匯入要「資料備妥」，系統看不出來）。自動偵測為「完成」時一律以偵測為準（略過旗標不會把已完成的步驟藏起來）。
    ③單步偵測失敗不影響其他步、不丟 500：該步當「未完成」並寫白話說明（「暫時無法自動確認」），例外只進 log。
    ④存的只有人工旗標（略過／手動完成＋誰、何時），不存偵測結果——所以偵測條件之後調整，舊進度不會失真。存在 system_settings 的 `getting_started_v1`。
    ⑤文字全是白話（不含程式字眼）；`href` 指向現有頁面，不新增設定頁；備份一步只連過去（「備份與監控」專頁由別人做）。
"""
import logging
from datetime import datetime

logger = logging.getLogger("motrix.getting_started")

STATE_KEY = "getting_started_v1"

#: 備份那一步的「連過去」位置：「備份與監控」專頁（4a）上線後只要改這一行。
BACKUP_HREF = "storage-settings.html"
#: 「寄測試信成功」「備份成功」的稽核動作（成功才會寫入）
EMAIL_TEST_ACTION = "settings.email_notify.test"
BACKUP_OK_ACTIONS = ("backup.sqlite_snapshot", "backup.daily_ok", "backup.daily_partial")

#: 每步：id／標題／為什麼要做／約幾分鐘／要準備什麼／做完怎麼確認／連去哪／可以人工確認完成嗎／可略過的提示
STEPS = (
    {"id": "company", "title": "公司資料",
     "why": "報價單、請款單與信件上都會印公司名稱、統一編號與聯絡方式；沒確認過的話，輸出文件會被擋下。",
     "minutes": "約 5 分鐘", "prepare": ["公司登記資料（名稱、統一編號、地址、電話）", "公司 Logo 圖檔"],
     "confirm": "必填欄位都填好，並按下「儲存並確認本公司資料」。",
     "href": "company-profile-settings.html", "link": "到公司資料設定"},
    {"id": "quote_style", "title": "報價單樣式",
     "why": "報價單是客戶第一眼看到的東西：抬頭、條款與收款帳戶要先備妥，並實際預覽一張。",
     "minutes": "約 10 分鐘", "prepare": ["報價條款文字", "收款銀行帳戶（銀行、戶名、帳號）"],
     "confirm": "預覽出一張報價單，確認抬頭、條款與收款帳戶都正確，回來按「我已預覽確認」。",
     "href": "company-profile-settings.html", "link": "到公司資料設定"},
    {"id": "people", "title": "人員與簽核",
     "why": "單據要送給誰簽、誰負責財務，都取決於部門、主管與職務；缺了任何一項，送審就會被擋下。",
     "minutes": "約 15 分鐘", "prepare": ["員工名單（姓名、Email、所屬部門）", "每個部門的主管是誰"],
     "confirm": "「組織設定檢查」全部通過（每位同仁有部門、每個部門有主管、有人擔任財務）。",
     "href": "users.html", "link": "到使用者管理"},
    {"id": "email", "title": "寄信",
     "why": "簽核通知、逾期提醒與報表都靠信件送達；先寄一封測試信，確認同仁真的收得到。",
     "minutes": "約 10 分鐘", "prepare": ["公司用的寄件信箱", "該信箱的應用程式密碼（通行碼）"],
     "confirm": "在通知設定頁按「寄測試信」並且成功寄出。",
     "href": "notification-settings.html", "link": "到通知設定"},
    {"id": "backup", "title": "備份",
     "why": "資料都在這台電腦上，硬碟壞了就沒了；要先確認備份放在別的地方，而且真的做成功過一次。",
     "minutes": "約 5 分鐘", "prepare": ["備份用的雲端硬碟或另一個資料夾"],
     "confirm": "系統記錄到第一次備份成功。",
     "href": BACKUP_HREF, "link": "到儲存位置與備份"},
    {"id": "line", "title": "LINE（可略過）",
     "why": "有了 LINE，簽核通知會直接傳到同仁手機。不用也沒關係，之後想用再回來設定。",
     "minutes": "約 20 分鐘，另外每位同仁各 1 分鐘", "prepare": ["LINE 官方帳號", "對外網址（讓 LINE 連得回來）"],
     "confirm": "官方帳號連線成功，並且至少一位同仁完成綁定；請同仁各自到「我的帳號 → 通知」按「綁定 LINE」。",
     "href": "notification-settings.html", "link": "到通知設定", "optional": True},
    {"id": "import", "title": "匯入資料",
     "why": "把既有的客戶、料號、員工與歷史報價放進來，之後就不用重打。",
     "minutes": "依資料量而定", "prepare": ["整理好的 Excel 檔（客戶、料號、員工、歷史報價）"],
     "confirm": "系統裡已經有客戶資料；全部匯入完畢後也可以按「資料已備妥」。",
     "href": "customers.html", "link": "到客戶資料"},
)
STEP_IDS = tuple(s["id"] for s in STEPS)
#: 系統看不出來、要人確認「做完了」的步驟
MANUAL_DONE_IDS = ("quote_style", "import")


# ── 偵測（只讀）：回 {"done": bool, "auto": bool, "detail": str, ...}；auto＝完成與否是系統自己判斷的 ──────────

def _fmt_at(iso) -> str:
    try:
        return datetime.fromisoformat(str(iso)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return ""


def _latest_audit_at(conn, actions):
    best = None
    for a in actions:
        row = conn.execute("SELECT at FROM audit_log WHERE action=? ORDER BY id DESC LIMIT 1", (a,)).fetchone()
        if row and row["at"] and (best is None or row["at"] > best):
            best = row["at"]
    return best


def _d_company(conn):
    from helpers import company_setup as cs
    st = cs.status(conn)
    if st.get("configured"):
        return {"done": True, "auto": True, "detail": "公司資料已確認。"}
    missing = st.get("missing") or []
    return {"done": False, "auto": True,
            "detail": ("還有 %d 個必填欄位沒填好。" % len(missing)) if missing else "公司資料還沒有按「確認」。"}


def _d_quote_style(conn):
    from helpers import company_setup as cs
    from helpers import _get_setting
    miss = cs.payment_bank_missing(_get_setting("company_profile", {}) or {})
    hint = ("收款帳戶還缺：" + "、".join(miss) + "。") if miss else "收款帳戶已填。"
    return {"done": False, "auto": False, "detail": hint + "預覽報價單這件事系統看不出來，請你確認後按「我已預覽確認」。"}


def _d_people(conn):
    from helpers import org_gaps as og
    if not og._has_regular_staff(conn):
        return {"done": False, "auto": True, "detail": "還沒有建立同仁帳號。", "fix": {"label": "到使用者管理", "href": "users.html"}}
    res = og.check(conn)
    if res["ok"]:
        return {"done": True, "auto": True, "detail": "組織設定檢查全部通過。"}
    first = res["gaps"][0]
    return {"done": False, "auto": True, "detail": "還有 %d 項要補齊：" % res["count"] + "；".join(g["title"] for g in res["gaps"]) + "。",
            "fix": dict(first.get("fix") or {})}


def _d_email(conn):
    at = _latest_audit_at(conn, (EMAIL_TEST_ACTION,))
    if at:
        return {"done": True, "auto": True, "detail": "最近一次測試信寄出成功：%s。" % _fmt_at(at)}
    return {"done": False, "auto": True, "detail": "還沒有寄過測試信（或寄出失敗）。"}


def _d_backup(conn):
    at = _latest_audit_at(conn, BACKUP_OK_ACTIONS)
    if at:
        return {"done": True, "auto": True, "detail": "最近一次備份成功：%s。" % _fmt_at(at)}
    return {"done": False, "auto": True, "detail": "系統還沒有記錄到備份成功。"}


def _d_line(conn):
    from helpers import line_notify as ln
    from helpers import _get_setting
    if not ln.enabled():
        return {"done": False, "auto": True, "detail": "LINE 還沒有串接。（這一步可以略過。）"}
    links = _get_setting(ln.LINKS_KEY, {}) or {}
    names = [r["username"] for r in conn.execute("SELECT username FROM users WHERE active=1").fetchall()]
    # 一次讀整份綁定表再逐人對照（`is_linked` 逐人各查一次資料庫；綁定時 `link_user` 已驗過 userId 格式，這裡只認「有 userId」）
    bound = sum(1 for n in names if isinstance(links.get(n), dict) and links[n].get("userId"))
    if bound >= 1:
        return {"done": True, "auto": True, "detail": "已有 %d／%d 位同仁綁定 LINE。" % (bound, len(names))}
    return {"done": False, "auto": True, "detail": "官方帳號已連線，但還沒有同仁綁定（請同仁到「我的帳號 → 通知」綁定）。"}


def _d_import(conn):
    try:
        c = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]       # 只數筆數、不回任何一筆資料
    except Exception:  # noqa: BLE001 — 表不存在（模組未裝）算 0
        c = 0
    if c > 0:
        return {"done": True, "auto": True, "detail": "已經有 %d 位客戶資料。" % c}
    return {"done": False, "auto": False, "detail": "還沒有客戶資料。匯入完畢後也可以按「資料已備妥」。"}


_DETECT = {"company": _d_company, "quote_style": _d_quote_style, "people": _d_people, "email": _d_email,
           "backup": _d_backup, "line": _d_line, "import": _d_import}


# ── 進度（人工旗標） ─────────────────────────────────────────────────────────────

def _load_state() -> dict:
    from helpers import _get_setting
    raw = _get_setting(STATE_KEY, {}) or {}
    steps = raw.get("steps") if isinstance(raw, dict) else None
    return {k: v for k, v in (steps or {}).items() if k in STEP_IDS and isinstance(v, dict)}


def _status_of(step_id: str, det: dict, flag: dict) -> str:
    if det.get("done"):
        return "done"
    if step_id in MANUAL_DONE_IDS and flag.get("manualDone"):
        return "done"
    if flag.get("skipped"):
        return "skipped"
    return "todo"


def overview(conn=None) -> dict:
    """{steps:[…], progress:{done,skipped,total}, next:{id,title,href,link}|None, allDone}。只讀；單步偵測失敗不影響其他步。"""
    own = conn is None
    if own:
        from db import get_db
        conn = get_db()
    state = _load_state()
    out = []
    try:
        for i, s in enumerate(STEPS, 1):
            try:
                det = _DETECT[s["id"]](conn)
            except Exception:  # noqa: BLE001
                logger.warning("getting_started 偵測 %s 失敗，當作未完成", s["id"], exc_info=True)
                det = {"done": False, "auto": False, "detail": "暫時無法自動確認，請稍後按「重新檢查」。"}
            flag = state.get(s["id"]) or {}
            row = {k: s[k] for k in ("id", "title", "why", "minutes", "prepare", "confirm", "href", "link")}
            fix = det.get("fix")
            if fix and fix.get("href"):
                row["href"], row["link"] = fix["href"], fix.get("label") or row["link"]
            row.update(n=i, optional=bool(s.get("optional")), status=_status_of(s["id"], det, flag), detail=det.get("detail", ""),
                       auto=bool(det.get("auto")), canMarkDone=s["id"] in MANUAL_DONE_IDS,
                       manualDone=bool(flag.get("manualDone")) and not det.get("done"), by=flag.get("by") or "", at=flag.get("at") or "")
            out.append(row)
    finally:
        if own:
            conn.close()
    done = sum(1 for r in out if r["status"] == "done")
    skipped = sum(1 for r in out if r["status"] == "skipped")
    nxt = next((r for r in out if r["status"] == "todo"), None)
    return {"steps": out, "progress": {"done": done, "skipped": skipped, "total": len(out)},
            "next": ({k: nxt[k] for k in ("id", "title", "href", "link", "minutes")} if nxt else None),
            "allDone": done + skipped == len(out) and done > 0}


def set_step(step_id: str, action: str, username: str) -> dict:
    """人工旗標：action＝skip（略過）／unskip（回來做）／done（手動確認完成，限 MANUAL_DONE_IDS）／undone（取消手動完成）。
    不合法 ⇒ ValueError（給人看的白話）。回新的旗標。"""
    if step_id not in STEP_IDS:
        raise ValueError("找不到這一步")
    if action not in ("skip", "unskip", "done", "undone"):
        raise ValueError("不認得這個動作")
    if action in ("done", "undone") and step_id not in MANUAL_DONE_IDS:
        raise ValueError("這一步由系統自動判斷是否完成，不能手動標記")
    from helpers import _get_setting, _set_setting
    raw = _get_setting(STATE_KEY, {}) or {}
    steps = dict((raw.get("steps") or {}) if isinstance(raw, dict) else {})
    flag = dict(steps.get(step_id) or {})
    if action == "skip":
        flag["skipped"] = True
    elif action == "unskip":
        flag["skipped"] = False
    elif action == "done":
        flag["manualDone"] = True
    else:
        flag["manualDone"] = False
    flag["by"], flag["at"] = username or "", datetime.now().isoformat(timespec="seconds")
    steps[step_id] = flag
    _set_setting(STATE_KEY, {"steps": steps})
    return flag
