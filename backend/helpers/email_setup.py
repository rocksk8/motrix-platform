# -*- coding: utf-8 -*-
"""寄信帳號精靈的後端零件（選單去工程師化 批次 3，2026-11-13）：供應商預設、格式驗證、失敗分類、設定單。

[單位] helper:email_setup    [層] L1    [穩定度] 實驗
[公開介面] PROVIDERS, provider_list, provider_by_key, valid_email, validate_config, normalize_password, classify_error, build_ticket, config_fingerprint
[契約題] tests/test_email_setup_2026_11_13.py
[不變式]
  ①純函式、不連網、不讀寫資料庫（寄信與存設定在 routers/system.py）；任何輸出都**不含密碼**。
  ②供應商預設的主機與埠，來源是各家公開說明（2026-11-13 查證，未實際連線測試）：Gmail／Microsoft 365／Yahoo 奇摩都是 587＋STARTTLS；
     Zoho 依帳號所在資料中心有不同網域（.com／.eu／.in／.com.au）。預設值只是預填，使用者可在「其他信箱」自己填。
  ③失敗只分「帳號或密碼不對」「連不上信箱服務」「網路不通」「信箱服務拒收」四類（其餘歸「其他」），畫面不顯示錯誤碼；
     Microsoft 365 的驗證失敗無法從回應分辨「密碼錯」與「公司把 SMTP 驗證關了」，所以兩種可能都講，並附設定單。
  ④設定單是純文字，可印出或貼到信裡寄給資訊廠商；不含密碼，只含帳號、主機、埠與要請對方做的事。
"""
import errno
import hashlib
import re
import smtplib
import socket
import ssl

PROVIDERS = [
    {
        "key": "gmail", "label": "Gmail（Google 信箱）", "host": "smtp.gmail.com", "port": 587,
        "passwordLabel": "應用程式密碼（16 碼）",
        "passwordHelp": "不是您登入 Google 的密碼。要先開啟「兩步驟驗證」，再到 Google 的「應用程式密碼」頁面建立一組 16 碼（中間的空格可以一起貼上）。",
        "helpUrl": "https://myaccount.google.com/apppasswords", "helpLabel": "開啟 Google 的應用程式密碼頁面",
        "userHint": "例：your@gmail.com", "note": "",
    },
    {
        "key": "microsoft365", "label": "Microsoft 365／Outlook（公司信箱）", "host": "smtp.office365.com", "port": 587,
        "passwordLabel": "信箱密碼或應用程式密碼",
        "passwordHelp": "多數公司的 Microsoft 365 已關閉這種寄信方式。如果下一步失敗，系統會產生一張「設定單」，請交給您們的資訊廠商處理。",
        "helpUrl": "", "helpLabel": "",
        "userHint": "例：name@公司網域.com", "note": "Microsoft 365 預設常關閉「已驗證的 SMTP 寄信」，不是貼密碼就能解決。",
    },
    {
        "key": "yahoo", "label": "Yahoo 奇摩信箱", "host": "smtp.mail.yahoo.com", "port": 587,
        "passwordLabel": "應用程式密碼",
        "passwordHelp": "請到 Yahoo 的帳號安全頁面產生「應用程式密碼」，不要貼登入密碼。",
        "helpUrl": "https://login.yahoo.com/account/security", "helpLabel": "開啟 Yahoo 的帳號安全頁面",
        "userHint": "例：name@yahoo.com.tw（要填完整信箱）", "note": "",
    },
    {
        "key": "zoho", "label": "Zoho Mail", "host": "smtp.zoho.com", "port": 587,
        "passwordLabel": "應用程式密碼",
        "passwordHelp": "若有開兩步驟驗證，要用「應用程式密碼」。您的帳號在歐洲、印度或澳洲資料中心時，主機網址結尾不同（.eu／.in／.com.au），請改選「其他信箱」填寫。",
        "helpUrl": "https://accounts.zoho.com", "helpLabel": "開啟 Zoho 帳號頁面",
        "userHint": "例：name@公司網域.com", "note": "",
    },
    {
        "key": "other", "label": "其他信箱", "host": "", "port": 587,
        "passwordLabel": "信箱密碼（或該信箱要求的應用程式密碼）",
        "passwordHelp": "主機與連接埠這兩個值，請向您的信箱或網域代管廠商詢問（常見寫法：「SMTP 寄信伺服器」與「連接埠」）。",
        "helpUrl": "", "helpLabel": "", "userHint": "例：name@公司網域.com", "note": "",
    },
]

_EMAIL_RE = re.compile(r"^[^@\s,;<>()\[\]\\\"]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$")
_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*$")


def provider_list() -> list:
    return [dict(p) for p in PROVIDERS]


def provider_by_key(key: str):
    for p in PROVIDERS:
        if p["key"] == key:
            return p
    return None


def valid_email(v: str) -> bool:
    return bool(_EMAIL_RE.match((v or "").strip())) and len(v) <= 254


def normalize_password(provider_key: str, pw: str) -> str:
    """Gmail 的應用程式密碼畫面是 4 組 4 碼、中間有空格；貼上時常一併帶入 ⇒ Gmail 一律去掉所有空白。其他供應商只去頭尾空白。"""
    pw = pw or ""
    return re.sub(r"\s+", "", pw) if provider_key == "gmail" else pw.strip()


def validate_config(data: dict):
    """檢查要存的寄信設定（只檢查「有填」的欄位，空值＝尚未設定、不擋）。回傳白話錯誤訊息，沒問題回 None。"""
    user = str(data.get("smtp_user") or "").strip()
    if user and not valid_email(user):
        return "寄件人 Email 格式不對，請填完整的信箱（例：name@公司網域.com）。"
    host = str(data.get("smtp_host") or "").strip()
    if host and (not _HOST_RE.match(host) or len(host) > 253):
        return "寄信主機的寫法不對：只填主機名稱（例：smtp.gmail.com），不要包含 http:// 或空格。"
    port = data.get("smtp_port")
    if port not in (None, ""):
        try:
            p = int(port)
        except (TypeError, ValueError):
            return "連接埠要填數字（常見是 587 或 465）。"
        if not 1 <= p <= 65535:
            return "連接埠要在 1 到 65535 之間（常見是 587 或 465）。"
    base = str(data.get("base_url") or "").strip()
    if base and not re.match(r"^https?://[^\s/]+", base, re.I):
        return "系統網址要以 http:// 或 https:// 開頭（例：https://motrix.example.com）。"
    if len(str(data.get("from_name") or "")) > 80:
        return "寄件人顯示名稱太長（最多 80 字）。"
    return None


def config_fingerprint(host: str, port, user: str, password: str) -> str:
    """寄信設定的指紋（只存雜湊，不存密碼）：用來確認「按『我收到了』啟用」的設定，就是剛剛寄測試信成功的那一份。"""
    raw = "\x1f".join([str(host or "").strip().lower(), str(port or ""), str(user or "").strip().lower(), password or ""])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _is_m365(host: str) -> bool:
    h = (host or "").lower()
    return h.endswith("office365.com") or h.endswith("outlook.com") or h.endswith("outlook.office365.com")


def classify_error(exc: BaseException, host: str = "", provider_key: str = "") -> dict:
    """把寄信例外分成給人看的類別。回傳 {category, title, hint, ticketKind}；ticketKind 非空 ⇒ 前端提供「產生設定單」。"""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        raw = (str(exc) + " " + str(getattr(exc, "smtp_error", b""))).lower()
        if _is_m365(host) or provider_key == "microsoft365" or "5.7.139" in raw or "5.7.30" in raw or "smtpclientauthentication" in raw:
            return {"category": "auth", "ticketKind": "m365_auth",
                    "title": "帳號或密碼不對，或公司的 Microsoft 365 沒有開放這種寄信方式",
                    "hint": "請先確認信箱與密碼。如果確定沒錯，多半是公司把「已驗證的 SMTP 寄信」關閉了，這不是貼密碼能解決的。請按「產生設定單」，交給資訊廠商處理。"}
        if provider_key == "gmail" and ("534" in raw or "5.7.9" in raw or "5.7.8" in raw or "application-specific" in raw):
            return {"category": "auth", "ticketKind": "",
                    "title": "帳號或密碼不對：Gmail 需要「應用程式密碼」",
                    "hint": "請勿貼 Google 登入密碼。先開啟兩步驟驗證，再到「應用程式密碼」頁面建立 16 碼貼上。"}
        return {"category": "auth", "ticketKind": "",
                "title": "帳號或密碼不對",
                "hint": "請確認信箱帳號沒有打錯，密碼是否為該信箱要求的「應用程式密碼」（很多信箱不接受登入密碼）。"}
    if isinstance(exc, (smtplib.SMTPSenderRefused, smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError)):
        return {"category": "rejected", "ticketKind": "m365_auth" if _is_m365(host) else "",
                "title": "信箱服務拒絕了這封信",
                "hint": "帳號登入成功，但對方不接受以這個信箱寄出（或收件人有誤）。請確認寄件信箱有權限代表自己寄信，或換一個信箱再試。"}
    if isinstance(exc, socket.gaierror) or (isinstance(exc, OSError) and getattr(exc, "errno", None) in (errno.ENETUNREACH, errno.ENETDOWN, errno.EHOSTUNREACH)):
        return {"category": "network", "ticketKind": "network",
                "title": "網路不通：找不到這台寄信主機",
                "hint": "請確認這台系統主機能上網，以及寄信主機的名稱沒有打錯。公司網路若限制對外連線，需請資訊廠商放行。"}
    if isinstance(exc, (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, ConnectionError, TimeoutError, socket.timeout, ssl.SSLError)):
        return {"category": "connect", "ticketKind": "network",
                "title": "連不上信箱服務",
                "hint": "寄信主機或連接埠可能不對，也可能是公司防火牆擋住了對外寄信（常見連接埠 587、465）。請確認主機與連接埠，仍不行就按「產生設定單」交給資訊廠商。"}
    return {"category": "other", "ticketKind": "",
            "title": "寄信失敗",
            "hint": "這次沒有寄出，原因不在常見的幾種情況內。請確認設定後再試一次，仍失敗請聯絡系統管理者並提供下方的代碼。"}


def build_ticket(kind: str, *, user: str, host: str, port, company: str = "", requester: str = "") -> dict:
    """設定單（純文字）。kind：m365_auth（Microsoft 365 沒開 SMTP 驗證）／network（對外連線被擋）。不含密碼。"""
    hp = f"{host}:{port}"
    head = ["【MOTRIX 系統寄信設定單】", "", f"公司：{company or '（請填公司名稱）'}", f"提出人：{requester or '（請填姓名）'}", ""]
    if kind == "m365_auth":
        body = [
            "狀況：系統要用下列信箱對外寄通知信（簽核、提醒），但信箱服務拒絕登入。可能是這個信箱沒有開放「已驗證的 SMTP 寄信」（SMTP AUTH），或帳號密碼不符。",
            "",
            "請協助（擇一）：",
            f"  1. 為信箱 {user or '（寄件信箱）'} 開啟「已驗證的 SMTP 寄信」。Exchange Online 管理員可用：",
            f"       Set-CASMailbox -Identity {user or '（寄件信箱）'} -SmtpClientAuthenticationDisabled $false",
            "     （若整個租戶層級被關閉，另需 Set-TransportConfig -SmtpClientAuthenticationDisabled $false，或依公司資安政策評估。）",
            "  2. 若公司政策不允許，請改提供一組可用於系統寄信的信箱或公司的寄信中繼（SMTP relay）主機、連接埠與帳號密碼。",
            "  3. 若有開多重要素驗證，請提供該信箱的「應用程式密碼」。",
        ]
    else:
        body = [
            "狀況：系統要連到下列寄信主機，但連線失敗（連不上或找不到主機）。",
            "",
            "請協助：",
            f"  1. 確認系統所在主機可以對外連到 {hp}（TCP）；若被防火牆擋住，請放行。",
            "  2. 確認寄信主機名稱與連接埠正確；若改用其他信箱服務，請提供正確的主機與連接埠。",
        ]
    tail = ["", "系統目前填的值：", f"  寄信主機：{host or '（未填）'}", f"  連接埠：{port}", f"  帳號：{user or '（未填）'}",
            "  密碼：（不在此單上，請由使用者另行提供）", "", "完成後請告訴使用者，回到系統的「通知設定」按「重新寄測試信」即可。"]
    title = "Microsoft 365 寄信設定單" if kind == "m365_auth" else "寄信連線設定單"
    return {"title": title, "text": "\n".join(head + body + tail)}
