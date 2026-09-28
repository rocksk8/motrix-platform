# -*- coding: utf-8 -*-
"""產品碼裡寫死的「本公司」資料掃描器（2026-09-27 H10；守門：test_no_our_company_literals.py）。

使用者：「已經有潛在客戶，要把原先的 logo、名稱、電話這些都換成客戶的」⇒ 產品碼（backend、frontend、tools，
不含 tests 與文件）不可以出現本公司的公司名、統編、電話、email／網域、地址、座標、人員姓名。
客戶看得到的一律改讀 company_profile；少數必須留著的（凍結的 migration、只在本公司安裝才會動作的升級回填、
安全黑名單、升級演練資料、已出貨的版本紀錄）逐筆登記在 `ALLOWED`，而且次數要一致——同一檔多寫一處也會紅。
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

#: 掃描的根目錄（相對 repo）
ROOTS = ("backend", "frontend", "tools")
#: 只掃這些副檔名（文字檔）；.md 是文件，不在產品碼範圍
SUFFIXES = {".py", ".html", ".js", ".css", ".json", ".ps1", ".bat", ".cmd", ".txt", ".ini", ".cfg",
            ".toml", ".yml", ".yaml", ".sql", ".xml", ".svg",
            ".vbs", ".pyw"}                 # 2026-09-28 稽核 D 建議（fc5c47f4）：兩者都是會出貨的文字檔
#: 路徑中任何一段是這些名稱 ⇒ 不掃（測試、測試資料、第三方、產出物）
EXCLUDED_PARTS = {"tests", "fixtures", "vendor", "node_modules", "__pycache__", "deploy_logs", "logs",
                  ".venv", ".venv312", "uploads", "backups"}

#: 名稱 ⇒ 樣式（不分大小寫）
NEEDLES = {
    "公司名（允碩）": r"允碩",
    "英文名（Synergy Integration）": r"synergy[\s_-]*integration",
    "統編": r"60575481",
    "電話": r"3610[\s-]?6566",
    "舊電話": r"3602[\s-]?2818",
    "email／網域（miac）": r"miac",
    "地址": r"八德路一段",
    "辦公室座標": r"24\.2549|120\.5316",
    "人員姓名": r"黃玉龍",
    "人員 email": r"jeff@",
    # 預設圖檔要經 /api/system/branding/<kind>（沒上傳才回預設），直接引用就換不掉（MODULE-GUIDE §3.7）
    "直接引用預設圖檔": r"static/(?:logo|logo-white|favicon)\.png",
}
_COMPILED = {k: re.compile(v, re.I) for k, v in NEEDLES.items()}

#: 決定過的例外：(相對路徑, 樣式名稱) ⇒ (次數, 類別, 理由)。類別只能是 CATEGORIES 之一；
#: frontend/ 底下一律不可以登記（頁面是客戶看得到的）。
CATEGORIES = {
    "凍結 migration": "db.py 的 _mNNN：歷史不可以改（MODULE-GUIDE §4）",
    "本公司安裝的升級回填": "只在統編對得上本公司時才動作（2026-09-28 起不看公司名），全新安裝與客戶安裝不會寫入",
    "安全黑名單": "舊弱密碼清單：啟動時掃描並強制改密碼，不會顯示",
    "升級演練資料": "模擬本公司 V9 升級的合成資料（演練工具）",
    "已出貨的版本紀錄": "已出貨的條目不改寫；全新安裝只顯示安裝基準版本之後的紀錄（使用者表單裁示 2026-09-27，"
                         "判定在 routers/module_versions.py）",
}

#: 不是文字、不在掃描範圍、但同樣帶本公司字樣的預設圖檔：`frontend/static/logo.png`、`logo-white.png`、
#: `favicon.png`（圖中有「MOTRIX SYNERGY INTEGRATION」）。**維持現在的圖**（使用者表單裁示 2026-09-27）；
#: 客戶在「公司資料設定 › 品牌與公司名稱」上傳自己的圖即取代（helpers/branding.py）。
KEPT_DEFAULT_IMAGES = {
    "frontend/static/logo.png": "使用者裁示 2026-09-27：維持現在的預設圖",
    "frontend/static/logo-white.png": "使用者裁示 2026-09-27：維持現在的預設圖",
    "frontend/static/favicon.png": "使用者裁示 2026-09-27：維持現在的預設圖（已壓成 256×256）",
}

ALLOWED = {
    ("backend/db.py", "統編"): (7, "凍結 migration", "_m106 只認 tax_id == 60575481 才回填（含說明）；:768 為說明"),
    ("backend/db.py", "電話"): (1, "凍結 migration", "_m106 說明文字"),
    ("backend/db.py", "email／網域（miac）"): (2, "凍結 migration", "_m008 補 jeff email（全新安裝時 users 是空的）；_m106 說明"),
    ("backend/db.py", "人員 email"): (1, "凍結 migration", "_m008"),
    ("backend/db.py", "英文名（Synergy Integration）"): (1, "凍結 migration", "_m106 回填英文名（僅本公司統編）"),
    ("backend/db.py", "人員姓名"): (2, "凍結 migration", "_m008 舊顯示名修正；_m1xx 說明"),
    ("backend/core/upgrade.py", "公司名（允碩）"): (2, "本公司安裝的升級回填", "V9_COMPANY_DEFAULTS 與出處註解"),
    ("backend/core/upgrade.py", "英文名（Synergy Integration）"): (2, "本公司安裝的升級回填", "V9_COMPANY_DEFAULTS 與出處註解"),
    ("backend/core/upgrade.py", "統編"): (3, "本公司安裝的升級回填", "V9_COMPANY_DEFAULTS 與出處註解"),
    ("backend/core/upgrade.py", "電話"): (2, "本公司安裝的升級回填", "V9_COMPANY_DEFAULTS 與出處註解"),
    ("backend/core/upgrade.py", "email／網域（miac）"): (2, "本公司安裝的升級回填", "V9_COMPANY_DEFAULTS 與出處註解"),
    ("backend/helpers/auth.py", "統編"): (1, "安全黑名單", "_LEGACY_WEAK_PASSWORDS"),
    ("backend/helpers/auth.py", "email／網域（miac）"): (1, "安全黑名單", "_LEGACY_WEAK_PASSWORDS"),
    ("tools/platform/upgrade_drill.py", "公司名（允碩）"): (1, "升級演練資料", "DRILL_COMPANY_PROFILE"),
    ("tools/platform/upgrade_drill.py", "統編"): (1, "升級演練資料", "DRILL_COMPANY_PROFILE"),
    ("tools/platform/upgrade_drill.py", "電話"): (1, "升級演練資料", "DRILL_COMPANY_PROFILE"),
    ("backend/version_manifest.json", "統編"): (1, "已出貨的版本紀錄", "2026-08 demo 帳號條目"),
    ("backend/version_manifest.json", "電話"): (1, "已出貨的版本紀錄", "2026-08 公司電話更正條目"),
    ("backend/version_manifest.json", "舊電話"): (2, "已出貨的版本紀錄", "2026-08 公司電話更正條目"),
    ("backend/version_manifest.json", "人員姓名"): (1, "已出貨的版本紀錄", "案件動態月曆修正條目提及人員姓名"),
    ("backend/version_manifest.json", "email／網域（miac）"): (1, "已出貨的版本紀錄", "v74 WebAuthn 條目"),
}


def read_text_any(path: Path) -> str:
    """讀文字檔，不因編碼而安靜略過：.vbs／.bat 常見 UTF-16（有 BOM）或系統碼頁（cp950）。
    依序：UTF-16 BOM ⇒ utf-16；utf-8(-sig)；cp950；都不行 ⇒ latin-1（不會失敗，ASCII 樣式照樣比得到）。"""
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    for enc in ("utf-8-sig", "cp950"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _scannable(rel_parts, suffix) -> bool:
    return suffix.lower() in SUFFIXES and not any(p in EXCLUDED_PARTS for p in rel_parts)


def scan(root: Path = REPO, roots=ROOTS) -> dict:
    """⇒ {(相對路徑, 樣式名稱): 次數}。只列有出現的。"""
    hits = {}
    for top in roots:
        base = root / top
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if not _scannable(rel.parts[:-1], path.suffix) or path.name.startswith("conftest"):
                continue
            try:
                text = read_text_any(path)
            except OSError:
                continue
            for name, rx in _COMPILED.items():
                n = len(rx.findall(text))
                if n:
                    hits[(rel.as_posix(), name)] = n
    return hits


def problems(hits: dict, allowed: dict = None) -> list:
    """掃描結果 × 登記表 ⇒ 問題清單（空＝通過）。三種：沒登記、次數不符、登記了卻沒出現（過期）；
    另外驗登記表本身：類別要在 CATEGORIES、frontend/ 不可以登記。"""
    allowed = ALLOWED if allowed is None else allowed
    out = []
    for key, (count, category, _reason) in allowed.items():
        if category not in CATEGORIES:
            out.append("登記的類別不在清單裡：%s %s（%s）" % (key[0], key[1], category))
        if key[0].startswith("frontend/"):
            out.append("頁面不可以登記例外（客戶看得到）：%s %s" % key)
    for key, n in sorted(hits.items()):
        if key not in allowed:
            out.append("寫死本公司資料：%s 的「%s」×%d——客戶看得到的改讀 company_profile；"
                       "必須留著的在 _our_company_literals.ALLOWED 登記（寫類別與理由）" % (key[0], key[1], n))
        elif allowed[key][0] != n:
            out.append("次數不符：%s 的「%s」登記 %d 次、實際 %d 次（新增的那一處要改讀設定，或更新登記）"
                       % (key[0], key[1], allowed[key][0], n))
    for key in sorted(set(allowed) - set(hits)):
        out.append("登記過期（已經沒有出現，請拿掉這一筆）：%s 的「%s」" % key)
    return out


if __name__ == "__main__":
    import sys
    for (rel, name), n in sorted(scan().items()):
        print("%-60s %-28s %d" % (rel, name, n))
    ps = problems(scan())
    print("\n".join(ps) or "OK")
    sys.exit(1 if ps else 0)
