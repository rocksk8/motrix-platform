# -*- coding: utf-8 -*-
"""本公司資料設定閘門的本機工具（COMPANY-SETUP-GATE §3.4、§4.3、§6.3）。不 import main、不開網路端點。

  python company_setup_cli.py ensure-install-id --root <安裝目錄>
  python company_setup_cli.py preflight --db <庫> --root <安裝目錄>     套用前預檢：在記憶體副本上模擬 backfill＋status（不寫庫）
  python company_setup_cli.py status    --db <庫> --root <安裝目錄>     套用後檢查（不寫庫）
  python company_setup_cli.py grace     --root <安裝目錄> --hours 72 --reason "<原因>"   暫時放行（≤72 小時）
  python company_setup_cli.py sign --private-key <私鑰檔> --install <安裝識別雜湊> --tax <統編> (--permanent | [--days 365]) --out <檔>
                                                      **開發機用**：簽開發者正式機的確認檔（§6.2）。私鑰只以路徑傳入、
                                                      不印不存；簽完以內嵌的交付公鑰自驗，驗不過就不寫檔

輸出：一行 JSON。結束碼：0＝允許（已設定或放行中）、3＝未設定、2＝判定失敗（configured: null）。
**用的是這支檔旁邊的 backend 程式碼**：預檢時執行包內（staging）的這一支 ⇒ 判定用的是新版程式碼。
正式機 apply_update.ps1 **沒有**任何略過預檢的參數（CG3-M1）；非 0 一律視為拒絕（預檢）或回滾（套用後）。
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

EXIT_OK, EXIT_ERROR, EXIT_NOT_CONFIGURED = 0, 2, 3


def _emit(obj, code):
    print(json.dumps(obj, ensure_ascii=False, sort_keys=True))
    return code


def _mem_copy(db_path):
    """唯讀開啟 ⇒ 複製到記憶體（預檢在副本上模擬 backfill，正式庫一個位元組都不動）。"""
    src = sqlite3.connect("file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
    try:
        mem = sqlite3.connect(":memory:")
        src.backup(mem)
        return mem
    finally:
        src.close()


def _result(st, root=None, conn=None):
    from helpers import company_setup as cs
    allowed = cs.allows(st)
    # D E4S3-S1：請款單匯款三欄是否齊全（只報不擋；缺 ⇒ 升級後請款單 PDF 428 company_bank_required）
    bank = None
    if conn is not None:
        try:
            bank = cs.payment_bank_missing(cs._get(conn, "company_profile", {}) or {})
        except Exception:  # noqa: BLE001 —— 只是回報，讀不到就回 null
            bank = None
    # CGI-S1：印出安裝識別雜湊——開發者正式機被拒（developer_identity_unsigned／install_mismatch）時，開發者要照這個值簽確認檔
    return {"configured": bool(st.get("configured")), "reason": st.get("reason"), "via": st.get("via"),
            "install": cs.install_hash(root),
            "developer": bool(st.get("developer")), "missing": st.get("missing") or [],
            "grace": bool(st.get("grace")), "grace_until": (st.get("grace") or {}).get("until"),
            "allowed": allowed, "payment_bank_missing": bank}, (EXIT_OK if allowed else EXIT_NOT_CONFIGURED)


def cmd_ensure(a):
    from helpers import company_setup as cs
    created, h = cs.ensure_install_id(a.root)
    if not h:
        return _emit({"ok": False, "error": "安裝識別檔無法建立"}, EXIT_ERROR)
    return _emit({"ok": True, "created": created, "install": h}, EXIT_OK)


def cmd_check(a, simulate_backfill):
    from helpers import company_setup as cs
    conn = _mem_copy(a.db)
    try:
        if simulate_backfill:
            cs.backfill_once(conn, a.root)
        out, code = _result(cs.status(conn, a.root), a.root, conn)
        return _emit(out, code)
    finally:
        conn.close()


def cmd_grace(a):
    from helpers import company_setup as cs
    if not (0 < a.hours <= cs.GRACE_MAX_HOURS):
        return _emit({"ok": False, "error": "--hours 必須在 1～%d" % cs.GRACE_MAX_HOURS}, EXIT_ERROR)
    if not a.reason.strip():
        return _emit({"ok": False, "error": "--reason 必填"}, EXIT_ERROR)
    _created, ih = cs.ensure_install_id(a.root)
    if not ih:
        return _emit({"ok": False, "error": "安裝識別檔無法建立"}, EXIT_ERROR)
    now = datetime.now()
    body = {"created": now.isoformat(timespec="seconds"),
            "until": (now + timedelta(hours=a.hours)).isoformat(timespec="seconds"),
            "reason": a.reason.strip(), "install": ih,
            "created_by_os_user": os.environ.get("USERNAME") or os.environ.get("USER") or ""}
    path = cs._files(a.root)[2]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False)
    os.replace(tmp, path)
    return _emit({"ok": True, "until": body["until"]}, EXIT_OK)


#: 使用者授權的確認檔有效期上限（2026-09-29 兩次變更：~~400~~ ⇒ ~~30~~ ⇒ 365；授權再變時改這裡與題）
SIGN_MAX_DAYS = 365


def cmd_sign(a):
    """§6.2 第 2 步（開發機）。只簽「開發者身分」＋一個安裝識別；檔案已存在不覆蓋。"""
    import re
    from helpers import company_setup as cs
    if not re.fullmatch(r"[0-9a-f]{64}", a.install or ""):
        return _emit({"ok": False, "error": "--install 必須是 64 個小寫十六進位字（正式機 ensure-install-id 印出的 install）"}, EXIT_ERROR)
    tax = re.sub(r"\D", "", a.tax or "")
    fp = cs.identity_fp("tax", tax)
    if fp not in cs.DEVELOPER_IDENTITY_FP:
        return _emit({"ok": False, "error": "--tax 不是開發者公司的統編：確認檔只簽開發者身分（其他安裝在設定頁由最高管理員確認）"}, EXIT_ERROR)
    if a.permanent and a.days is not None:
        return _emit({"ok": False, "error": "--permanent 與 --days 只能擇一"}, EXIT_ERROR)
    days = SIGN_MAX_DAYS if a.days is None else a.days
    if not a.permanent and not (0 < days <= SIGN_MAX_DAYS):
        return _emit({"ok": False, "error": "--days 必須在 1～%d" % SIGN_MAX_DAYS}, EXIT_ERROR)
    if os.path.exists(a.out):
        return _emit({"ok": False, "error": "輸出檔已存在，不覆蓋：%s" % a.out}, EXIT_ERROR)
    today = datetime.now().date()
    payload = {"identity_fp": fp, "install": a.install, "issued": today.isoformat()}
    if a.permanent:
        # 使用者 2026-09-29「正式機為永久授權」：不寫 expires、寫 permanent（都在簽章範圍內）；只准開發者身分（上面已驗）
        payload["permanent"] = True
    else:
        payload["expires"] = (today + timedelta(days=days)).isoformat()
    try:
        with open(a.private_key, "rb") as f:
            text = cs.sign_confirmation(payload, f.read())
    except Exception as exc:  # noqa: BLE001 —— 不印例外內容（可能含檔案片段）
        return _emit({"ok": False, "error": "私鑰讀取或簽章失敗（%s）" % type(exc).__name__}, EXIT_ERROR)
    if cs.verified_doc(text) is None:
        return _emit({"ok": False, "error": "簽出的檔用內嵌交付公鑰驗不過：私鑰不是交付金鑰，未寫檔"}, EXIT_ERROR)
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, a.out)
    return _emit({"ok": True, "out": a.out, "install": a.install, "issued": payload["issued"],
                  "expires": payload.get("expires"), "permanent": bool(a.permanent)}, EXIT_OK)


def main(argv=None):
    # 一律 UTF-8 輸出：apply_update.ps1 以 UTF-8 讀；Windows 主控台預設 cp950／cp932 會讓中文變亂碼、JSON 解不開
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    p = argparse.ArgumentParser(description="本公司資料設定閘門本機工具")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("ensure-install-id")
    e.add_argument("--root", required=True)
    for name in ("preflight", "status"):
        s = sub.add_parser(name)
        s.add_argument("--db", required=True)
        s.add_argument("--root", required=True)
    g = sub.add_parser("grace")
    g.add_argument("--root", required=True)
    g.add_argument("--hours", type=int, default=72)
    g.add_argument("--reason", required=True)
    s = sub.add_parser("sign")
    s.add_argument("--private-key", required=True)
    s.add_argument("--install", required=True)
    s.add_argument("--tax", required=True)
    s.add_argument("--days", type=int, default=None)   # 不帶 ⇒ 365（使用者授權上限；2026-09-29：~~30~~ ⇒ 365）
    s.add_argument("--permanent", action="store_true")  # 開發者本公司正式機：永久（使用者 2026-09-29）
    s.add_argument("--out", required=True)
    a = p.parse_args(argv)
    try:
        if a.cmd == "ensure-install-id":
            return cmd_ensure(a)
        if a.cmd == "grace":
            return cmd_grace(a)
        if a.cmd == "sign":
            return cmd_sign(a)
        return cmd_check(a, simulate_backfill=(a.cmd == "preflight"))
    except Exception as exc:  # noqa: BLE001 — 判定失敗：configured null、結束碼 2（呼叫端視為拒絕／回滾）
        return _emit({"configured": None, "reason": "status_error", "allowed": False,
                      "error": "%s: %s" % (type(exc).__name__, exc)}, EXIT_ERROR)


if __name__ == "__main__":
    sys.exit(main())
