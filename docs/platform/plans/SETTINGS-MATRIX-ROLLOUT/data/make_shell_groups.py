"""產生 data/shell_groups.json（r3.2）：設定中心外框的「頁面」對應。
- 每個 registry 群組屬於一個「實際呈現的頁面」；預設一群組一頁，少數合併（builder_* 總開關面板、清單與下載檔名、首頁外觀、狀態名稱、小設定）。
- 分類只有這一套（業務／財務／系統／安全）；安全＝存取、登入、保存與隱私。
- style：checkbox＝頁面提供勾選格；form／preset-only＝保留給「卡片＋預覽」「只透過預設組合」的頁面（目前沒有頁面使用，gen_seed 與 --check 已支援）。
- privacy：影響隱私的群組（外框顯示「影響隱私」標籤）。
改此檔後務必跑 `gen_seed.py` 與 `gen_seed.py --check`。"""
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent  # data/ 資料夾；產出 shell_groups.json 放同一處
sys.stdout.reconfigure(encoding="utf-8")
Y, C, S, A = "業務", "財務", "系統", "安全"
G = {  # group: (category, plain name)
 "account_security": (A, "登入與密碼規則"), "external_login": (A, "從外網登入的防護"), "change_control": (A, "重大設定要等幾天才生效"),
 "retention": (A, "資料保存多久"), "recycle_bin": (A, "刪除的單據保留幾天"), "quote_privacy": (A, "報價單的個人資料欄位（能不能隱藏）"),
 "uploads": (S, "上傳檔案的大小與數量"), "system_hub": (S, "系統中心要不要列出你沒有權限的項目"), "download_name": (S, "下載檔案怎麼命名"),
 "ui_format": (S, "數字與日期怎麼顯示"), "brand": (S, "系統標語"), "login_greeting": (S, "登入畫面問候語"),
 "list_prefs": (S, "要不要開放個人調整清單"), "list_view": (S, "清單各項個人調整"),
 "builder_status_display": (S, "自訂狀態的名稱與顏色"), "builder_layout": (S, "自訂畫面的版面"), "builder_governance": (S, "自訂功能的版本與發布管控"),
 "builder_rules": (S, "自訂規則（標示型）"), "builder_menu": (S, "自訂選單"), "builder_custom_fields": (S, "內建畫面的自訂欄位"),
 "builder_actions": (S, "自訂按鈕"), "builder_slots": (S, "附件種類與存放位置"), "builder_exports": (S, "自訂匯出"),
 "builder_option_lists": (S, "自訂下拉選項"), "builder_notify": (S, "自訂通知用語"), "builder_stage_templates": (S, "自訂案件階段樣板"),
 "builder_custom_modules": (S, "建立自訂模組"),
 "material_order": (Y, "材料申請規則"), "material_recognition": (Y, "誰能把採購單認列到材料卡片"), "quote_alt": (Y, "報價單的「擇一方案」"),
 "quote_approval": (Y, "報價單什麼時候要送審"), "quote_output": (Y, "隱藏的報價條件要不要印在 PDF"), "quote_defaults": (Y, "報價單預設值"),
 "quote_backfill": (Y, "補登歷史案件"), "case_close_gates": (Y, "案件結案前要先完成什麼"), "completion_note": (Y, "完工單怎麼從報價單帶入"), "alerts": (Y, "保固與確認檔到期提醒"),
 "netplan_labels": (Y, "網路規劃：狀態名稱"), "procurement_labels": (Y, "採購建議：狀態名稱"), "lodging_labels": (Y, "住宿紀錄：計價單位與詢價管道"),
 "lodging_freshness": (Y, "附近旅宿：資料新舊提示"), "tender_closing": (Y, "地圖：標案即將截止標記"),
 "project_margin": (C, "專案毛利率低於多少要提醒"), "finance_reports": (C, "帳齡與未精算提醒"), "finance_cashier": (C, "出納頁與銀行對帳單"),
 "profit_warning": (C, "利潤提醒色帶"), "profit_rules": (C, "公益捐款比率"), "overhead": (C, "管銷怎麼分攤"),
 "payslip_dispatch_picker": (C, "勞報單「選派發」下拉一次載入幾筆"), "legal_params_reminder": (C, "法規參數跨年提醒"),
}
PRIVACY = {"download_name", "quote_privacy"}
# 合併頁：頁面代碼 -> (白話頁名, 分類, 成員群組, style, 原因)
MERGED = {  # 頁面代碼 -> (白話頁名, 分類, 成員群組, style, 原因)；與 h12 乙份 mockup（88ed4907d）一致，PM 已認可
 "builder_all": ("自訂功能的開關（13 組）", S, [k for k in G if k.startswith("builder_")], "checkbox", ""),
 "list_download": ("清單與下載檔名", S, ["list_view", "list_prefs", "download_name"], "checkbox", ""),
 "home_look": ("首頁外觀、數字與日期", S, ["ui_format", "login_greeting", "brand"], "checkbox", ""),
 "labels_biz": ("網路規劃、採購、住宿的狀態名稱", Y, ["netplan_labels", "procurement_labels", "lodging_labels"], "checkbox", ""),
 "small_misc": ("旅宿與標案地圖的小設定", Y, ["lodging_freshness", "tender_closing"], "checkbox", ""),
}
STYLE = {}  # 非預設樣式的單群組頁：form＝卡片＋預覽不畫勾選格；preset-only＝只透過預設組合（目前沒有）
src = json.load(open(HERE / "settings_groups.json", encoding="utf-8"))
assert set(src) == set(G), (set(src) ^ set(G))
in_merged = {g for m in MERGED.values() for g in m[2]}
pages = {}
for pid, (plain, cat, members, style, reason) in MERGED.items():
    pages[pid] = {"plain": plain, "category": cat, "groups": members, "style": style, "reason": reason}
for g, (cat, plain) in G.items():
    if g in in_merged: continue
    st, why = STYLE.get(g, ("checkbox", ""))
    pages[g] = {"plain": plain, "category": cat, "groups": [g], "style": st, "reason": why}
groups = {g: {"plain": G[g][0:2][1], "category": G[g][0], "currentName": src[g]["label"], "privacy": g in PRIVACY} for g in G}
out = {"_doc": "設定中心外框的頁面對應（SPEC §14.5）。分類只有這一套；安全＝存取、登入、保存與隱私。style：checkbox／form／preset-only。產生器：make_shell_groups.py；改完請跑 gen_seed.py 與 --check。",
       "categoryOrder": [Y, C, S, A], "pages": pages, "groups": groups}
json.dump(out, open("D:/Claude-pm/hichan4-matrix/wt/docs/platform/plans/SETTINGS-MATRIX-ROLLOUT/data/shell_groups.json", "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=1)
import collections
print(len(pages), "pages;", collections.Counter(p["category"] for p in pages.values()), "groups by cat", collections.Counter(v["category"] for v in groups.values()))
