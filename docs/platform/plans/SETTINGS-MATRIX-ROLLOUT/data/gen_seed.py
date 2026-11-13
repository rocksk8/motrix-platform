# -*- coding: utf-8 -*-
"""產生「系統設定全面改版」盤點表骨架（可重現；每次凍結後重跑）。唯讀：只 import 程式、不連資料庫、不啟動伺服器。

用法（在 repo 根目錄）：
    cd backend
    set MOTRIX_DISABLE_SCHEDULERS=1 & set PYTHONUTF8=1
    python -I ../docs/platform/plans/SETTINGS-MATRIX-ROLLOUT/data/gen_seed.py

輸出（寫在本檔所在資料夾）：
  settings_groups.json              設定中心所有群組／欄位完整 meta（`SettingDef.meta()`；機器產生，可覆蓋）
  settings-center-items.seed.csv    骨架：第一～三段＝設定中心每個欄位一列（分工 甲／乙）；第四段＝「設定中心以外」的設定
  bing-items.seed.csv               丙份骨架：個人權限鍵、信件類型、僅行事曆事件、LINE 事件、個人 Email 通知事件、簽核單據類型
  settings-center-items.csv／bing-items.csv   **工作檔**（各分工在這裡填「【填】」欄）。本腳本**絕不覆蓋**工作檔：只有工作檔不存在時才由 .seed.csv 複製一份
重產後要合併：用 `python -I diff_seed.py`（見檔尾說明）或自行 diff 工作檔與 .seed.csv 的「非【填】」欄。
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


FINANCE_ROLE_KEYS = ("cashier", "finance", "financial_view")          # 由角色決定，批次永遠唯讀
BATCH_GRANT_REFUSED = ("project_approve_eng", "project_approve_biz", "quotation", "expense_forms", "file_center", "contractor_list")  # C4


def batchable(f, group_sensitive=False):
    """PM 2026-11-13 M1：risk none／ops 可批次（ops 要確認視窗）；security／money／legal、受 change_control 管（待生效／放寬）、`sensitive` 群組者永不進批次。"""
    if group_sensitive or f["risk"] in ("security", "money", "legal") or f["requiresPending"] or f["loosen"]:
        return "否（永不進批次）"
    if f["type"] == "str" and not f["choices"]:
        return "否（文字欄位，逐列編輯）"  # 自由文字：每家公司內容不同，不能「一鍵套同一段字」；逐列編輯、儲存前預覽
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
                         f["unit"], ch, f["risk"], f["riskText"], "是" if f["advanced"] else "", "是" if f["requiresPending"] else "", f["loosen"] or "", batchable(f, v["sensitive"])] + [""] * len(FILL))
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
    return _write_seed("settings-center-items", cols, rows)


def _write_seed(stem, cols, rows):
    """只寫 .seed.csv；工作檔不存在才複製一份。工作檔存在就不動（可能有人手填）。"""
    seed, work = HERE / (stem + ".seed.csv"), HERE / (stem + ".csv")
    with open(seed, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh); w.writerow(cols); w.writerows(rows)
    if not work.exists():
        work.write_bytes(seed.read_bytes())
    return len(rows)


def _fill(cat, name, ev="", sens=False, extra=""):
    """丙份可由資料直接推得的欄位先填好（建議名稱沿用現名稱：實測皆已是白話；有疑義的人工覆核）。順序同 FILL。"""
    if cat == "信件類型":
        return [name, "「%s」這封信預設寄給：%s。預設：信件開。" % (name, ev or "（無固定收件人）"),
                "照預設＝依這種信的預設收件人；僅最高管理者＝只寄給最高管理者；指定＝除事件相關人外，另寄給指定帳號或角色",
                "公司（改過才算）／預設", "系統技術類：關閉後告警可能沒人看到（影響大）" if sens else "簽核類：關閉後簽核人收不到通知，流程可能卡住" if extra == "approval" else "",
                "矩陣｜勾選批次｜搜尋篩選｜套用前確認＋復原這一批｜手機卡片", "行事曆欄標「需外部設定」"]
    if cat == "僅行事曆事件":
        return [name, "%s。預設：依事件預設。" % (ev or name), "開／關（只有公司層，沒有個人層）", "公司／預設", "需外部設定：要先連上 Google 行事曆才會真的推送",
                "矩陣｜勾選批次｜搜尋篩選｜套用前確認＋復原這一批｜手機卡片", "與 google-calendar-settings 是同一份資料（INVENTORY §五-7）"]
    if cat == "LINE 事件":
        return [name, "有「%s」時用 LINE 推播給指定對象。預設：關。" % name, "收件對象：照 Email 收件人／只發給指定人員（建議）／原本＋指定",
                "公司／預設", "影響別人（收件人會收到 LINE）", "矩陣｜勾選批次｜群組全開全關｜搜尋篩選｜預設組合｜套用前確認＋復原這一批｜手機卡片",
                "沿用 hichan-6 稿；每則訊息每位收件人算一則（用量提示）"]
    if cat == "個人 Email 通知事件":
        return [name, "取消後，不再寄「%s」給這位同仁。預設：收。" % name, "收／不收", "個人（有個人層）／預設", "個人偏好，只影響自己；簽核類取消可能漏看待簽單據",
                "群組全開全關｜預設組合｜搜尋篩選｜套用前確認＋復原這一批｜手機卡片", "本人入口待使用者決定（INVENTORY §五-3）"]
    if cat == "個人權限鍵":
        return [name, "能不能使用「%s」這項功能。預設依各人的角色範本。" % name, "有／無（個別加減會與角色範本不同）", "預設（角色範本）／個別加減",
                "影響大：高敏感權限，要原因、寫權限變更紀錄，永不進批次" if sens else "影響別人（改變這個人的選單與操作權限）",
                "單項表單（高敏感）" if sens else "矩陣｜勾選批次｜群組全開全關｜搜尋篩選｜預設組合｜套用前確認＋復原這一批｜手機卡片", ""]
    if cat == "簽核單據類型":
        return [name, "「%s」送出後要經過幾層、由誰簽核。" % name, "統一流程（共用一條）／獨立流程（各自一條）", "公司／預設", "影響別人（簽核人與進行中單據）",
                "矩陣｜勾選批次｜預設組合｜套用前確認＋復原這一批｜手機卡片", "確認視窗要顯示進行中單據受影響件數"]
    return [""] * len(FILL)


def bing_csv():
    from helpers import mail_types as MT, notification_prefs as NP, module_registry as MR, tiered_approval as TA, duty_roles as DR
    from helpers import line_catalog as LC, line_notify as LN
    cols = ["類別", "頁面", "群組", "項目代碼", "現名稱", "現說明／事件", "現影響／建議處理", "預設", "備註（來源）", "可批次?"] + FILL
    rows = []
    for t in MT.all_types():
        who = "＋".join(x for x in (t.event, {"admins": "管理者", "superadmins": "最高管理者"}.get(t.group, "")) if x)
        rows.append(["信件類型", "mail-settings", t.category, t.key, t.name, "預設收件人：" + (who or "（無固定收件人）"), "影響：%s｜處理：%s" % (t.impact, t.action),
                     "信件開／照預設收件人／行事曆關", "mail_types.all_types()", "是（系統技術類要紅字提醒）" if t.category == "system" else "是"] + _fill("信件類型", t.name, who, t.category == "system", t.category))
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
        rows.append(["LINE 事件", "notification-settings（LINE 卡）", gp, k, nm, "", "", "關", "line_notify.wired_events()（hichan-6 稿）", "是"] + _fill("LINE 事件", nm))
    for i, (gname, evs) in enumerate(NP.EVENT_GROUPS):
        for key, label in evs:
            rows.append(["個人 Email 通知事件", "users.html（管理員代設）／my-account（本人，待決）", gname, key, label, "", "", "收（opt-out 清單預設全收）",
                         "notification_prefs.EVENT_GROUPS", "是"] + _fill("個人 Email 通知事件", label))
    sens = set(DR.HIGH_SENSITIVITY_KEYS)
    for key, label, grp in MR.MODULES:
        # 使用者裁示 C4：另列「批次拒絕清單」——禁止批次授予（取消可以），不併入高敏感清單
        batch = ("否（由角色決定，唯讀）" if key in FINANCE_ROLE_KEYS else "授予否／取消可（高敏感）" if key in sens
                 else "授予否／取消可（批次拒絕清單）" if key in BATCH_GRANT_REFUSED else "是")
        rows.append(["個人權限鍵", "users.html（存取模組）", grp, key, label, "", "高敏感權限：要原因、寫權限變更紀錄" if key in sens else "", "依角色範本", "module_registry.MODULES",
                     batch] + _fill("個人權限鍵", label.split("（")[0], sens=key in sens))
    from helpers import google_calendar as GC, notify_matrix as NM
    cal = {x["code"]: x for x in GC.event_types()}
    for code in NM.calendar_only_codes(GC.EVENT_CODES):
        x = cal[code]
        rows.append(["僅行事曆事件", "mail-settings／google-calendar-settings", x["group"], code, x["label"], x["description"], "", "預設：" + ("開" if x["default"] else "關"),
                     "google_calendar.event_types()（沒有對應信件的行事曆事件）", "是（需連上 Google 才會推送）"] + _fill("僅行事曆事件", x["label"], x["description"]))
    for key, label in TA.APPROVAL_DOC_TYPE_LABELS.items():
        rows.append(["簽核單據類型", "approval-settings", "統一流程" if key in TA.DEFAULT_UNIFIED_DOC_TYPES else "獨立流程", key, label, "", "", "", "tiered_approval", "是"] + _fill("簽核單據類型", label))
    return _write_seed("bing-items", cols, rows)


def check_batchable():
    """自我檢查（PM r3 ②）：不經 batchable()，另依 SPEC §4.1 文字獨立重算，與 seed／工作檔的「可批次?」欄逐列比對；不符就 raise。
    用法：python -I gen_seed.py --check（不需 import 後端，只讀 settings_groups.json＋兩份 CSV）。"""
    groups = json.load(open(HERE / "settings_groups.json", encoding="utf-8"))
    want = {}
    for g, v in groups.items():
        for f in v["fields"]:
            if v.get("sensitive") or f["risk"] in ("security", "money", "legal") or f.get("requiresPending") or f.get("loosen"):
                w = "否（永不進批次）"
            elif f["type"] == "str" and not f["choices"]:
                w = "否（文字欄位，逐列編輯）"
            else:
                w = "是（需確認視窗）" if f["risk"] == "ops" else "是"
            want[(g, f["key"])] = w
    for name in ("settings-center-items.seed.csv", "settings-center-items.csv"):
        with open(HERE / name, encoding="utf-8-sig", newline="") as fh:
            rows = [r for r in csv.DictReader(fh) if r["段"].startswith("一")]
        got = {(r["群組代碼"], r["欄位代碼"]): r["可批次?"] for r in rows}
        assert set(got) == set(want), "%s：欄位集合與 settings_groups.json 不同" % name
        bad = [k for k in want if got[k] != want[k]]
        assert not bad, "%s：可批次? 與 SPEC §4.1 重算不符 %d 列，例：%s" % (name, len(bad), bad[:5])
        n_yes = sum(1 for k in want if want[k].startswith("是"))
        print("check ok  %s  rows=%d 可批次=%d" % (name, len(rows), n_yes))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--check" in sys.argv:
        check_batchable(); sys.exit(0)
    reg = dump_registry()
    n_fields = sum(len(v["fields"]) for v in reg.values())
    print("groups=%d fields=%d" % (len(reg), n_fields))
    print("settings-center-items.csv rows=%d" % settings_center_csv(reg))
    print("bing-items.csv rows=%d" % bing_csv())
    print("style words:", STYLE_WORDS)
    print("（工作檔的【填】欄不會被覆寫；只有 *.seed.csv 重寫。工作檔「可批次?」欄請用 --check 驗證）")
