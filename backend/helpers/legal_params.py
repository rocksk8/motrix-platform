# -*- coding: utf-8 -*-
"""L1 法規參數服務（R1；規格 CUSTOMIZATION-SPEC §7.1）。

扣繳率、起扣標準、補充保費門檻、最低工資是「法規決定、每年會變」的數字。
這裡把它們做成**依生效日版本化**的清單，模組只問「這個日期適用哪一版」。

- 儲存：設定鍵 `tax_rules_versions`＝`[{version, effectiveFrom, resident, non_resident, nhi, minimum_wage, sources}]`。
- 相容：沒有這個鍵 ⇒ 舊的單一設定 `tax_rules`（V9）視為 `effectiveFrom=2026-01-01` 的一版。
- 選版：`effectiveFrom ≤ 日期` 的最新一版；日期早於最早一版 ⇒ `NoApplicableRules`（不猜）。
- 守門：每一版「兼職薪資補充保費門檻 thresholds["50"] ＝ 最低工資 monthly」。

純函式（不碰資料庫）與讀寫設定的函式分開，測試可以直接餵清單。
"""
import copy
import re
from datetime import date

VERSIONS_KEY = "tax_rules_versions"
LEGACY_KEY = "tax_rules"
LEGACY_EFFECTIVE_FROM = "2026-01-01"

INCOME_TYPES = ("50", "9A", "9B")

#: 115 年（2026）版。數字與來源見 docs/platform/BENCHMARK.md §6.2、§6.3（查詢日 2026-09-25）。
#: 內容與 db.py 種子 `tax_rules` 相同（test_legal_params 守住兩者一致）。
DEFAULT_TAX_RULE_VERSIONS = [
    {
        "version": "2026",
        "effectiveFrom": "2026-01-01",
        "resident": {
            # 各類所得扣繳率標準 §2 I ③（薪資 5%）、⑦（執行業務 10%）；
            # 50 起扣 90,501（稅務入口網 1506，115 年度）；9A/9B 20,010（§13 稅額 ≤ 2,000 免扣）
            "50": {"tax_rate": 0.05, "tax_threshold": 90501},
            "9A": {"tax_rate": 0.10, "tax_threshold": 20010},
            "9B": {"tax_rate": 0.10, "tax_threshold": 20010},
        },
        "non_resident": {
            # 同標準 §3：薪資 18%（≤ 基本工資 1.5 倍 6%）、執行業務 20%、稿費等每次 ≤ 5,000 免扣
            "50": {"tax_rate": 0.18, "tax_threshold": 0, "low_salary_rate": 0.06},
            "9A": {"tax_rate": 0.20, "tax_threshold": 0},
            "9B": {"tax_rate": 0.20, "tax_threshold": 5001},
        },
        "nhi": {
            # 健保署〈115年投保單位(雇主)及保險對象補充保險費資料簡表〉：費率 2.11%、單次上限 1,000 萬、
            # 9A/9B 下限 20,000；兼職薪資下限連動最低工資「115/1/1起為29,500元」
            "rate": 0.0211,
            "max_single_payment": 10000000,
            "thresholds": {"50": 29500, "9A": 20000, "9B": 20000},
        },
        "minimum_wage": {"monthly": 29500},
        "sources": [
            "各類所得扣繳率標準 §2、§3、§13 https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=G0340028&flno=2",
            "財政部稅務入口網 1506（115 年度起扣標準 90,501 元）https://www.etax.nat.gov.tw/etwmain/tax-info/understanding/tax-q-and-a/national/individual-income-tax/withheld-rule/rule/n3x6znM",
            "健保署 115 年補充保險費資料簡表 https://www.nhi.gov.tw/ch/dl-10392-b1d1f21fddd64fa6ba3391b3c661db65-1.pdf",
        ],
    },
    # 116 年（2027）刻意不預設：勞動部 2026-09-24 審議最低工資月薪 30,900 元（https://www.mol.gov.tw/1607/1632/1633/99195/post），
    # **尚待行政院核定**；116 年薪資起扣標準財政部也還沒公告。核定／公告後，由管理者在「法規參數設定」頁
    # 新增一版（effectiveFrom 2027-01-01；minimum_wage.monthly 與 nhi.thresholds["50"] 同步改成核定數字）。
]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class NoApplicableRules(ValueError):
    """日期早於最早一版，或清單是空的。"""


def today() -> date:
    """「今天」的唯一來源（跨年提示、已生效判斷、空白單據日期）；測試以 monkeypatch 換掉。"""
    return date.today()


# ── 純函式 ────────────────────────────────────────────────────────────────────

def _as_date(v) -> date:
    if isinstance(v, date):
        return v
    s = str(v or "").strip()[:10]
    if not _DATE_RE.match(s):
        raise ValueError(f"日期格式不正確：{v!r}（要 YYYY-MM-DD）")
    return date.fromisoformat(s)


def sort_versions(versions) -> list:
    return sorted((copy.deepcopy(v) for v in versions or []), key=lambda v: str(v.get("effectiveFrom", "")))


def rules_for_date(versions, on) -> dict:
    """`effectiveFrom ≤ on` 的最新一版（深拷貝）。沒有 ⇒ NoApplicableRules。"""
    d = _as_date(on)
    picked = None
    for v in sort_versions(versions):
        if _as_date(v["effectiveFrom"]) <= d:
            picked = v
    if picked is None:
        first = sort_versions(versions)[:1]
        raise NoApplicableRules(
            "日期 %s 沒有適用的法規參數（最早一版自 %s 起），請先到「法規參數設定」新增適用的版本"
            % (d.isoformat(), first[0]["effectiveFrom"] if first else "—"))
    return picked


def rules_by_version(versions, version):
    for v in versions or []:
        if str(v.get("version")) == str(version):
            return copy.deepcopy(v)
    return None


def minimum_wage_mismatch(v) -> str:
    """守門：兼職薪資補充保費門檻必須等於當年最低工資。符合 ⇒ ''；不符 ⇒ 說明。"""
    try:
        th = v["nhi"]["thresholds"]["50"]
        mw = v["minimum_wage"]["monthly"]
    except (KeyError, TypeError):
        return "版本 %s 缺少兼職薪資補充保費門檻或最低工資" % v.get("version", "?")
    if th != mw:
        return ("版本 %s：兼職薪資（50）補充保費門檻 %s 與最低工資 %s 不一致（健保署：兼職薪資下限＝最低工資）"
                % (v.get("version", "?"), f"{th:,}" if isinstance(th, (int, float)) else th,
                   f"{mw:,}" if isinstance(mw, (int, float)) else mw))
    return ""


def _num(x, lo=None, hi=None) -> bool:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return False
    if lo is not None and x < lo:
        return False
    if hi is not None and x > hi:
        return False
    return True


def validate_version(v) -> list:
    """一版的結構與數值檢查。回傳錯誤清單（空＝通過）。"""
    errs = []
    if not isinstance(v, dict):
        return ["每一版必須是物件"]
    name = str(v.get("version") or "").strip()
    if not name:
        errs.append("版本名稱不可空白")
    try:
        _as_date(v.get("effectiveFrom"))
    except ValueError as e:
        errs.append("版本 %s：生效日%s" % (name or "?", str(e)))
    for side in ("resident", "non_resident"):
        block = v.get(side)
        if not isinstance(block, dict):
            errs.append("版本 %s：缺少 %s" % (name or "?", side))
            continue
        for it in INCOME_TYPES:
            r = block.get(it)
            if not isinstance(r, dict) or not _num(r.get("tax_rate"), 0, 1) or not _num(r.get("tax_threshold", 0), 0):
                errs.append("版本 %s：%s.%s 的稅率（0～1）或起扣門檻（≥0）不正確" % (name or "?", side, it))
            elif "low_salary_rate" in r and not _num(r["low_salary_rate"], 0, 1):
                errs.append("版本 %s：%s.%s.low_salary_rate 不正確" % (name or "?", side, it))
    nhi = v.get("nhi")
    if not isinstance(nhi, dict) or not _num(nhi.get("rate"), 0, 1) or not _num(nhi.get("max_single_payment"), 0) \
            or not isinstance(nhi.get("thresholds"), dict) \
            or not all(_num(nhi["thresholds"].get(it), 0) for it in INCOME_TYPES):
        errs.append("版本 %s：二代健保（費率、單次上限、各類門檻）不正確" % (name or "?"))
    mw = v.get("minimum_wage")
    if not isinstance(mw, dict) or not _num(mw.get("monthly"), 1):
        errs.append("版本 %s：最低工資（月）不正確" % (name or "?"))
    if not errs:
        m = minimum_wage_mismatch(v)
        if m:
            errs.append(m)
    return errs


def validate_versions(versions) -> list:
    if not isinstance(versions, list) or not versions:
        return ["至少要有一版法規參數"]
    errs = []
    for v in versions:
        errs += validate_version(v)
    names = [str(v.get("version")) for v in versions if isinstance(v, dict)]
    dates = [str(v.get("effectiveFrom")) for v in versions if isinstance(v, dict)]
    if len(set(names)) != len(names):
        errs.append("版本名稱重複")
    if len(set(dates)) != len(dates):
        errs.append("生效日重複")
    return errs


def frozen_changes(old_versions, new_versions, today) -> list:
    """已生效（effectiveFrom ≤ today）的版本不能改、不能刪。回傳違規說明。"""
    t = _as_date(today)
    new_by_name = {str(v.get("version")): v for v in new_versions if isinstance(v, dict)}
    errs = []
    for old in old_versions:
        try:
            eff = _as_date(old.get("effectiveFrom"))
        except ValueError:
            continue
        if eff > t:
            continue
        name = str(old.get("version"))
        new = new_by_name.get(name)
        if new is None:
            errs.append("版本 %s 已生效（%s 起），不能刪除" % (name, old.get("effectiveFrom")))
        elif _comparable(new) != _comparable(old):
            errs.append("版本 %s 已生效（%s 起），不能修改；要更正請新增一版" % (name, old.get("effectiveFrom")))
    return errs


def _comparable(v):
    v = copy.deepcopy(v)
    v.pop("sources", None)        # 來源說明可以補，不影響計算
    return v


def year_status(versions, today) -> dict:
    """跨年提示。12 月且沒有任何 effectiveFrom 在下一年 ⇒ nextYearMissing。"""
    t = _as_date(today)
    vs = sort_versions(versions)
    years = {str(v.get("effectiveFrom", ""))[:4] for v in vs}
    try:
        current = rules_for_date(vs, t)
    except NoApplicableRules:
        current = None
    next_missing = t.month == 12 and str(t.year + 1) not in years
    this_missing = str(t.year) not in years
    warnings = []
    if next_missing:
        warnings.append("已進入 12 月，%d 年的法規參數（最低工資、扣繳起扣標準、補充保費門檻）還沒有設定；"
                        "1 月起開立的勞報單會沿用 %s 版。請到「法規參數設定」新增一版（沿用也要新增一版以示確認）"
                        % (t.year + 1, current["version"] if current else "—"))
    if this_missing and current:
        warnings.append("今年（%d）沒有設定法規參數，勞報單沿用 %s 版（%s 起）的規則" %
                        (t.year, current["version"], current["effectiveFrom"]))
    if current is None:
        warnings.append("今天沒有適用的法規參數版本")
    for v in vs:
        m = minimum_wage_mismatch(v)
        if m:
            warnings.append(m)
    return {
        "today": t.isoformat(),
        "currentVersion": current["version"] if current else None,
        "nextYear": t.year + 1,
        "nextYearMissing": next_missing,
        "currentYearMissing": this_missing,
        "warnings": warnings,
    }


# ── R2（CUSTOMIZATION-SPEC §7.2）：零稅率、免稅的依據 ─────────────────────────────
#
# 營業稅法 §7（零稅率，第 1～9 款；全國法規資料庫 G0340080 flno=7，2026-09-25 查，款名為摘要）、
# §8（免稅，第一項共三十餘款；款次與內容由使用者填，本檔不逐款抄錄——未逐字取得條文）。
# 依據存在單據 data_json.taxBasis = {code, note}；核心欄位（稅別、稅率、金額）不動。
TAX_BASIS_OPTIONS = {
    "zero": [
        ("7-1", "營業稅法 §7 ① 外銷貨物"),
        ("7-2", "營業稅法 §7 ② 與外銷有關之勞務，或在國內提供而在國外使用之勞務"),
        ("7-3", "營業稅法 §7 ③ 免稅商店銷售與過境或出境旅客之貨物"),
        ("7-4", "營業稅法 §7 ④ 銷售與保稅區營業人供營運之貨物或勞務"),
        ("7-5", "營業稅法 §7 ⑤ 國際間之運輸"),
        ("7-6", "營業稅法 §7 ⑥ 國際運輸用之船舶、航空器及遠洋漁船"),
        ("7-7", "營業稅法 §7 ⑦ 銷售與國際運輸用之船舶、航空器及遠洋漁船所使用之貨物或修繕勞務"),
        ("7-8", "營業稅法 §7 ⑧ 保稅區營業人銷售與課稅區營業人未輸往課稅區而直接出口之貨物"),
        ("7-9", "營業稅法 §7 ⑨ 保稅區營業人銷售與課稅區營業人存入自由港區事業或海關管理之保稅倉庫、物流中心以供外銷之貨物"),
        ("zero-other", "其他法律規定之零稅率（請於說明填寫法條）"),
    ],
    "exempt": [
        ("8", "營業稅法 §8 第一項（請於說明填寫款次與內容）"),
        ("exempt-other", "其他法律規定之免稅（請於說明填寫法條）"),
    ],
}
#: 選這些代碼時「說明」必填
TAX_BASIS_NOTE_REQUIRED = {"zero-other", "8", "exempt-other"}


def tax_basis_label(basis) -> str:
    """依據的顯示文字（開票申請快照與畫面用）。沒有 ⇒ ''。"""
    if not isinstance(basis, dict):
        return ""
    code = basis.get("code")
    label = next((lb for opts in TAX_BASIS_OPTIONS.values() for c, lb in opts if c == code), "")
    note = str(basis.get("note") or "").strip()
    return "；".join(x for x in (label, note) if x)


def tax_basis_error(tax_type: str, basis) -> str:
    """零稅率／免稅的依據是否有效。有效（或應稅）⇒ ''；否則回傳給使用者看的錯誤訊息。"""
    if tax_type not in ("zero", "exempt"):
        return ""
    name = "零稅率" if tax_type == "zero" else "免稅"
    law = "營業稅法 §7" if tax_type == "zero" else "營業稅法 §8"
    code = basis.get("code") if isinstance(basis, dict) else None
    if not code:
        return f"稅別為{name}，請選擇{name}依據（{law}）"
    if code not in {c for c, _l in TAX_BASIS_OPTIONS[tax_type]}:
        return f"{name}依據不正確，請重新選擇（{law}）"
    if code in TAX_BASIS_NOTE_REQUIRED and not str(basis.get("note") or "").strip():
        return f"{name}依據選了「{dict(TAX_BASIS_OPTIONS[tax_type])[code]}」，請在說明欄填寫款次或法條"
    return ""


# ── 讀寫設定 ──────────────────────────────────────────────────────────────────

def load_versions() -> list:
    from helpers.settings import _get_setting
    stored = _get_setting(VERSIONS_KEY, None)
    if isinstance(stored, list) and stored:
        return sort_versions(stored)
    legacy = _get_setting(LEGACY_KEY, None)
    if isinstance(legacy, dict) and legacy:
        v = copy.deepcopy(legacy)
        v.setdefault("version", "2026")
        v.setdefault("effectiveFrom", LEGACY_EFFECTIVE_FROM)
        if "sources" not in v:
            v["sources"] = copy.deepcopy(DEFAULT_TAX_RULE_VERSIONS[0]["sources"])
        return [v]
    return sort_versions(DEFAULT_TAX_RULE_VERSIONS)


def save_versions(versions) -> None:
    from helpers.settings import _set_setting
    _set_setting(VERSIONS_KEY, sort_versions(versions))
