# -*- coding: utf-8 -*-
"""產生「系統設定全面改版」盤點表骨架（可重現；每次凍結後重跑）。唯讀：只 import 程式、不連資料庫、不啟動伺服器。

用法（在 repo 根目錄）：
    cd backend
    set MOTRIX_DISABLE_SCHEDULERS=1 & set PYTHONUTF8=1
    python -I ../docs/platform/plans/SETTINGS-MATRIX-ROLLOUT/data/gen_seed.py

輸出（寫在本檔所在資料夾）：
  settings_groups.json        設定中心所有群組／欄位完整 meta（`SettingDef.meta()`）
  settings-center-items.csv   第一～三段：設定中心每個欄位一列（分工 甲／乙）；第四段：「設定中心以外」的設定（分工 甲／乙／丙／僅 API）
  bing-items.csv              丙份：個人權限鍵、信件類型、LINE 事件、個人 Email 通知事件、簽核單據類型、職責角色
「【填】」開頭的欄位留給各分工填寫，重跑時**不會**保留手填內容——所以只在凍結後第一次產生；之後請直接改 CSV，或改成合併式更新。
"""
import csv
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[4] / "backend"          # docs/platform/plans/SETTINGS-MATRIX-ROLLOUT/data → repo/backend
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("MOTRIX_DISABLE_SCHEDULERS", "1")

from helpers import settings_registry as R      # noqa: E402
import helpers.settings_groups                    # noqa: E402,F401  登錄在 import 時完成

# ── 分工（甲＝hichan-3；乙＝hichan-12）。新群組（例：T83 的 monitoring）預設歸乙，請在此補上 ──
JIA = {"quote_alt", "quote_approval", "quote_output", "quote_privacy", "quote_defaults", "quote_backfill", "profit_warning", "profit_rules",
       "overhead", "project_margin", "material_order", "material_recognition", "finance_reports", "finance_cashier", "case_close_gates",
       "completion_note", "payslip_dispatch_picker", "alerts", "legal_params_reminder", "change_control"}
SLICE_JIA, SLICE_YI, SLICE_BING = "甲 業務與財務規則", "乙 系統、安全、畫面與自訂", "丙 通知／權限／我的帳號"
slice_of = lambda g: SLICE_JIA if g in JIA else SLICE_YI

FILL = ["【填】建議白話名稱", "【填】一句說明（影響什麼、預設值）", "【填】選項白話後果", "【填】目前生效值與來源（公司／預設；真有個人層才寫個人）",
        "【填】影響別人／危險標示", "【填】套用樣式", "【填】備註"]
STYLE_WORDS = "矩陣｜勾選批次｜群組全開全關｜搜尋篩選｜預設組合｜套用前確認＋復原這一批｜手機卡片｜單項表單｜逐列編輯＋預覽｜精靈"


def dump_registry():
    out = {}
    for g, d in R._GROUPS.items():                  # noqa: SLF001
        out[g] = {"label": d["label"], "owner": d["owner"], "risk": d["risk"], "sensitive": d["sensitive"], "help": d["help"],
                  "fields": [f.meta() for f in d["fields"].values()]}
    (HERE / "settings_groups.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def batchable(f):
    """PM 2026-11-13 M1：risk none／ops 可批次（ops 要確認視窗）；security／money／legal 與受 change_control 管（待生效／放寬）者永不進批次。"""
    if f["risk"] in ("security", "money", "legal") or f["requiresPending"] or f["loosen"]:
        return "否（永不進批次）"
    return "是（需確認視窗）" if f["risk"] == "ops" else "是"


def settings_center_csv(reg):
    cols = ["段", "分工", "群組代碼", "現群組名", "群組風險標示(內含高風險項目?)", "欄位代碼", "現名稱(label)", "現問句", "現說明", "現影響說明", "型別",
            "預設值", "建議值", "單位", "現選項(標籤：後果)", "風險類別", "風險提示", "收進進階", "確認期間才生效", "放寬須雙人核准", "可批次?"] + FILL
    rows = []
    for g, v in sorted(reg.items(), key=lambda kv: (slice_of(kv[0]), kv[0])):
        hi = any(f["risk"] in ("security", "money", "legal") or f["requiresPending"] for f in v["fields"])
        for f in v["fields"]:
            ch = "；".join("%s：%s" % (c["label"], c["impact"]) for c in f["choices"])
            rows.append(["一～三 設定中心欄位", slice_of(g), g, v["label"], "內含高風險項目" if hi else "", f["key"], f["label"], f["question"], f["help"], f["impact"],
                         f["type"], json.dumps(f["default"], ensure_ascii=False), "" if f["recommended"] is None else json.dumps(f["recommended"], ensure_ascii=False),
                         f["unit"], ch, f["risk"], f["riskText"], "是" if f["advanced"] else "", "是" if f["requiresPending"] else "", f["loosen"] or "", batchable(f)] + [""] * len(FILL))
    # 第四段：設定中心以外（PM 2026-11-13 M2）。位置請負責人補到「備註」；不在本次範圍的只有 API 的兩項，不替它們發明畫面。
    outside = [
        (SLICE_JIA, "bonus 預設", "獎金", ""), (SLICE_JIA, "憑證帳戶", "", ""), (SLICE_JIA, "扣款設定", "", ""),
        (SLICE_JIA, "overhead 模式與公益模式", "settlement.html", ""), (SLICE_JIA, "營運目標", "reports.js", ""), (SLICE_JIA, "T100 匯出設定", "cashier.js", ""),
        (SLICE_JIA, "報價條款與付款條件", "quotation-form.html", ""),
        (SLICE_YI, "回收桶隔離目錄", "recycle-bin", ""), (SLICE_YI, "標案雷達排程", "tender-radar", ""),
        (SLICE_YI, "backup-monitor 頁（T83 加入）", "backup-monitor.html", "T83 凍結後確認項目"),
        (SLICE_YI, "custom-module 審核設定", "", "先確認 builder_governance 有沒有涵蓋"),
        (SLICE_BING, "my-account 全頁", "my-account.html", "含安全設定、LINE 綁定與個人偏好"),
        ("僅 API（不在本次範圍）", "ledger fiscal_year_start_month", "API", "只有 API、沒有畫面；不替它發明畫面"),
        ("僅 API（不在本次範圍）", "remit_require_payslip", "API", "只有 API、沒有畫面；不替它發明畫面"),
    ]
    for sl, name, where, note in outside:
        rows.append(["四 設定中心以外", sl, "", "", "", "", name, "", "", "", "", "", "", "", "", "", "", "", "", "", ""] + [""] * (len(FILL) - 1) + [("位置：" + where + "　" + note).strip()])
    with open(HERE / "settings-center-items.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh); w.writerow(cols); w.writerows(rows)
    return len(rows)


def bing_csv():
    from helpers import mail_types as MT, notification_prefs as NP, module_registry as MR, tiered_approval as TA, duty_roles as DR
    from helpers import line_catalog as LC, line_notify as LN
    cols = ["類別", "頁面", "群組", "項目代碼", "現名稱", "現說明／事件", "現影響／建議處理", "預設", "備註（來源）", "可批次?"] + FILL
    rows = []
    for t in MT.all_types():
        rows.append(["信件類型", "mail-settings", t.category, t.key, t.name, "何時寄：" + t.event, "影響：%s｜處理：%s" % (t.impact, t.action),
                     "信件開／照預設收件人／行事曆關", "mail_types.all_types()", "是（系統技術類要紅字提醒）" if t.category == "system" else "是"] + [""] * len(FILL))
    try:
        wired = LN.wired_events()
        names = list(wired) if not isinstance(wired, dict) else list(wired.keys())
    except Exception:                                  # noqa: BLE001
        names = []
    for k in names:
        try:
            nm, gp = LC.name_of(k), LC.group_of(k)
        except Exception:                              # noqa: BLE001
            nm, gp = k, ""
        rows.append(["LINE 事件", "notification-settings（LINE 卡）", gp, k, nm, "", "", "關", "line_notify.wired_events()（hichan-6 稿）", "是"] + [""] * len(FILL))
    for i, (gname, evs) in enumerate(NP.EVENT_GROUPS):
        for key, label in evs:
            rows.append(["個人 Email 通知事件", "users.html（管理員代設）／my-account（本人，待決）", gname, key, label, "", "", "收（opt-out 清單預設全收）",
                         "notification_prefs.EVENT_GROUPS", "是"] + [""] * len(FILL))
    sens = set(DR.HIGH_SENSITIVITY_KEYS)
    for key, label, grp in MR.MODULES:
        rows.append(["個人權限鍵", "users.html（存取模組）", grp, key, label, "", "高敏感權限：要原因、寫權限變更紀錄" if key in sens else "", "依角色範本", "module_registry.MODULES",
                     "否（高敏感）" if key in sens else "是"] + [""] * len(FILL))
    for key, label in TA.APPROVAL_DOC_TYPE_LABELS.items():
        rows.append(["簽核單據類型", "approval-settings", "統一流程" if key in TA.DEFAULT_UNIFIED_DOC_TYPES else "獨立流程", key, label, "", "", "", "tiered_approval", "是"] + [""] * len(FILL))
    with open(HERE / "bing-items.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh); w.writerow(cols); w.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    reg = dump_registry()
    n_fields = sum(len(v["fields"]) for v in reg.values())
    print("groups=%d fields=%d" % (len(reg), n_fields))
    print("settings-center-items.csv rows=%d" % settings_center_csv(reg))
    print("bing-items.csv rows=%d" % bing_csv())
    sys.stdout.reconfigure(encoding="utf-8"); print("style words:", STYLE_WORDS)
