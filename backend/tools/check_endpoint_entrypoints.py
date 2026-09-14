"""打包前檢查：後端新增的 API 端點，前端有沒有任何地方呼叫得到。

**為什麼需要這支**：本專案已經連續兩次出現「後端上線、前端沒入口」——

1. WebAuthn：`f8198e9` 讓四個端點在 RP ID 未設定時回 503，唯一的設定入口卻在
   另一個沒被部署的 commit 裡，結果後端上線了、卻沒有任何地方能填 RP ID。
2. 叫料（`routers/material_orders.py`）：2026-09-10 修好四個缺陷、7 題 API 測試
   全綠，但整整一天沒有任何前端呼叫得到它，見 WEEKLY-AUDIT §E-1。

兩次都不是「寫錯」，是「寫完忘了另一半」。純 API 測試對這種缺陷完全無感——
端點本身好好的，測試也真的在測它，只是沒有人走得到。

**這支只警告、不擋打包**：判斷方式是字串比對，本來就會有誤判（前端可能用
拼接的方式組網址），拿它擋打包會變成每次都要想辦法繞過。把它當成
「你是不是忘了什麼」的提醒就好。

**判斷方式**：取路由路徑最後一個非參數片段（例如
`/api/quotations/{quote_no}/material-orders` → `material-orders`），到 `frontend/`
底下所有 .html/.js 檔裡找這個字串。找不到就列出來。同一個片段被多支端點共用時
只報一次。

用法：
    python backend/tools/check_endpoint_entrypoints.py [--json]
永遠回 exit 0（除非自己壞掉）。
"""
import json
import re
import sys
from pathlib import Path

# 這台機器的 locale 是 cp932，直接 print 中文會 UnicodeEncodeError 整支炸掉
# （本專案踩過不只一次，見 memory「Windows locale 編碼陷阱」）。打包腳本是
# 透過管線收這支的輸出，更不能讓它因為編碼死在這裡。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROUTE_RE = re.compile(r"""@router\.(get|post|put|patch|delete)\(\s*["']([^"']+)["']""")

# 確定不需要前端入口的片段：寫在這裡就不會再被報出來，但**一定要附理由**，
# 否則下一個人無從判斷它是「確定不需要」還是「當年也忘了做」。
ALLOWLIST = {
    "ping": "健康檢查，給 apply_update.ps1／心跳排程用，不是給人點的",
    "healthz": "同上",
    "openapi.json": "FastAPI 自動產生",
    "docs": "FastAPI 自動產生",
    "redoc": "FastAPI 自動產生",
    "deployed-version": "部署工具在用（deploy_dashboard.py:258、check_prod_drift.ps1），不是給人點的",
}

# 「第一次掃描時就已經沒有前端入口、但還沒查證是刻意還是忘了做」的端點放這裡。
# 不放進 ALLOWLIST（那等於宣稱「確定不需要」），也不跟新冒出來的混在一起報
# ——否則每次打包都跳同樣幾行，很快就沒人看了。
#
# 2026-09-11 首次掃描時有四筆：backup-retention／cloud-backup-target／edge-path／
# pdf-base-path。查證後發現**四個都是系統真的在讀的設定，只是沒有管理介面**，
# 使用者決定四個全補，已於同日完成（company-profile-settings.html 的「系統技術設定」
# 區塊），所以這份清單現在是空的——這才是它該有的樣子。
#
# 日後若又出現一批「還沒查清楚」的，往這裡放並寫上查證狀態，查完就搬去 ALLOWLIST
# 或補前端後刪掉。不要讓它變成長期堆積區。
KNOWN_BASELINE: dict = {}


def _last_literal_segment(path: str) -> str:
    """取路徑最後一個不是 {param} 的片段。"""
    segs = [s for s in path.strip("/").split("/") if s and not s.startswith("{")]
    return segs[-1] if segs else ""


def collect_routes(routers_dir: Path):
    """回傳 {片段: set(來源檔名)}。"""
    found = {}
    for py in sorted(routers_dir.glob("*.py")):
        if py.name == "__init__.py":
            continue
        text = py.read_text(encoding="utf-8", errors="replace")
        for _verb, path in ROUTE_RE.findall(text):
            seg = _last_literal_segment(path)
            # 太短的片段拿去比對只會全部命中，沒有鑑別度
            if len(seg) < 3:
                continue
            found.setdefault(seg, set()).add(py.name)
    return found


def frontend_corpus(frontend_dir: Path) -> str:
    parts = []
    for pattern in ("**/*.html", "**/*.js"):
        for f in frontend_dir.glob(pattern):
            # vendor 是第三方函式庫，不會呼叫我們自己的 API，而且很大
            if "vendor" in f.parts:
                continue
            parts.append(f.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    routers_dir = root / "backend" / "routers"
    frontend_dir = root / "frontend"
    if not routers_dir.is_dir() or not frontend_dir.is_dir():
        print(f"[SKIP] 找不到 backend/routers 或 frontend（root={root}）")
        return 0

    routes = collect_routes(routers_dir)
    corpus = frontend_corpus(frontend_dir)

    orphans, baseline = [], []
    for seg in sorted(routes):
        if seg in ALLOWLIST or seg in corpus:
            continue
        row = {"segment": seg, "routers": sorted(routes[seg])}
        (baseline if seg in KNOWN_BASELINE else orphans).append(row)

    if "--json" in sys.argv:
        print(json.dumps({"checked": len(routes), "orphans": orphans, "baseline": baseline},
                         ensure_ascii=False, indent=2))
        return 0

    print(f"[入口檢查] 掃描 {len(routes)} 組路由片段。")
    if baseline:
        segs = "、".join(b["segment"] for b in baseline)
        print(f"[既有] {len(baseline)} 組長期沒有前端入口（未查證是否刻意）：{segs}")

    if not orphans:
        print("[OK] 沒有新的「後端上線但前端沒入口」端點。")
        return 0

    print(f"[警告] 有 {len(orphans)} 組路由在 frontend/ 完全找不到呼叫點：")
    for o in orphans:
        print(f"  - /{o['segment']}  ← {'、'.join(o['routers'])}")
    print("  這不一定是錯的（可能是給工具或排程用的），但如果是剛寫完的功能，")
    print("  請確認前端那一半也做了；確定不需要的請加進本檔 ALLOWLIST 並寫上理由。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
