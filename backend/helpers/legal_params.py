# -*- coding: utf-8 -*-
"""L1 法規參數服務（R1；規格 CUSTOMIZATION-SPEC §9.1）。

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
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

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
            # 同簡表：所屬投保單位給付的獎金，全年累計「超過投保金額 4 倍」的部分計收補充保費（U4 獎金分潤用）
            "bonus_insured_multiple": 4,
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


# ── 法規金額的捨入（唯一來源；稽核 D-1，2026-09-26）──────────────────────────────
#
# 🔴 Python 內建 `round()` 是銀行家捨入（.5 捨入到偶數：round(738.5) == 738），浮點乘法另有誤差
#    ⇒ 法規金額一律走這裡：金額與費率都轉成十進位（Decimal）再捨入，不經過浮點乘積。
# - 補充保費：健保署「保險費之繳納，以元為單位，角以下 4 捨 5 入」
#   （https://www.nhi.gov.tw/ch/cp-2947-71ec6-3150-1.html，2026-09-26 查）⇒ `round_half_up`。
# - 扣繳稅額：沿用「元以下捨去」（V9 起即如此；官方條文未核對，稽核 L-5／O-5）⇒ `floor_amount`。
# 守門：tests/platform/test_legal_amount_rounding_guard.py（讀法規參數的程式不可以直接用 round()／math.floor()）。
# 前端同一套算法：frontend/static/legal-round.js（整數運算），全域比對題守住兩邊一致。

def _dec(x) -> Decimal:
    if isinstance(x, bool):
        raise TypeError("法規金額不接受布林值")
    if isinstance(x, Decimal):
        return x
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        return Decimal(repr(x))       # 0.0211 ⇒ Decimal('0.0211')（最短表示，不是二進位展開）
    return Decimal(str(x).strip())


def round_half_up(amount, rate=1) -> int:
    """`amount × rate` 四捨五入到元（角以下 4 捨 5 入）。補充保費等「四捨五入」的法規金額用這個。"""
    return int((_dec(amount) * _dec(rate)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def floor_amount(amount, rate=1) -> int:
    """`amount × rate` 元以下捨去。扣繳稅額用這個。"""
    return int((_dec(amount) * _dec(rate)).quantize(Decimal(1), rounding=ROUND_FLOOR))


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
    elif not _num(nhi.get("bonus_insured_multiple"), 1):
        errs.append("版本 %s：獎金補充保費門檻倍數（投保金額 × N，nhi.bonus_insured_multiple）必填且 ≥ 1"
                    % (name or "?"))
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


# ── R2（CUSTOMIZATION-SPEC §9.2）：零稅率、免稅的依據 ─────────────────────────────
#
# 營業稅法 §7（零稅率，第 1～9 款；全國法規資料庫 G0340080 flno=7，2026-09-25 查，款名為摘要）、
# §8（免稅，第一項第 1～32 款，第 7 款已刪除）。
# 〔原句（R，2026-09-25）：「§8（免稅，第一項共三十餘款；款次與內容由使用者填，本檔不逐款抄錄——未逐字取得條文）」
#   ⇒ 2026-09-26 稽核 S-4：已取得逐字條文，改成逐款下拉〕
# 依據存在單據 data_json.taxBasis = {code, note}；核心欄位（稅別、稅率、金額）不動。

#: 加值型及非加值型營業稅法 §8 第一項**逐字**條文（款次, 內容）。
#: 出處：全國法規資料庫 https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=G0340080&flno=8
#: 查詢日 2026-09-26（該站「法規整編資料截止日：民國 115 年 09 月 18 日」）。條文修正時照新條文改這張表。
ARTICLE_8_SOURCE = ("加值型及非加值型營業稅法 §8 第一項，全國法規資料庫 "
                    "https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=G0340080&flno=8"
                    "（2026-09-26 查；整編截止 115-09-18）")
ARTICLE_8_ITEMS = [
    (1, "出售之土地。"),
    (2, "供應之農田灌溉用水。"),
    (3, "醫院、診所、療養院提供之醫療勞務、藥品、病房之住宿及膳食。"),
    (4, "依法經主管機關許可設立之社會福利團體、機構及勞工團體，提供之社會福利勞務及政府委託代辦之社會福利勞務。"),
    (5, "學校、幼稚園與其他教育文化機構提供之教育勞務及政府委託代辦之文化勞務。"),
    (6, "出版業發行經主管教育行政機關審定之各級學校所用教科書及經政府依法獎勵之重要學術專門著作。"),
    (7, "（刪除）"),
    (8, "職業學校不對外營業之實習商店銷售之貨物或勞務。"),
    (9, "依法登記之報社、雜誌社、通訊社、電視臺與廣播電臺銷售其本事業之報紙、出版品、通訊稿、廣告、節目播映及節目播出。但報社銷售之廣告及電視臺之廣告播映不包括在內。"),
    (10, "合作社依法經營銷售與社員之貨物或勞務及政府委託其代辦之業務。"),
    (11, "農會、漁會、工會、商業會、工業會依法經營銷售與會員之貨物或勞務及政府委託其代辦之業務，或依農產品市場交易法設立且農會、漁會、合作社、政府之投資比例合計占百分之七十以上之農產品批發市場，依同法第二十七條規定收取之管理費。"),
    (12, "依法組織之慈善救濟事業標售或義賣之貨物與舉辦之義演，其收入除支付標售、義賣及義演之必要費用外，全部供作該事業本身之用者。"),
    (13, "政府機構、公營事業及社會團體，依有關法令組設經營不對外營業之員工福利機構，銷售之貨物或勞務。"),
    (14, "監獄工廠及其作業成品售賣所銷售之貨物或勞務。"),
    (15, "郵政、電信機關依法經營之業務及政府核定之代辦業務。"),
    (16, "政府專賣事業銷售之專賣品及經許可銷售專賣品之營業人，依照規定價格銷售之專賣品。"),
    (17, "代銷印花稅票或郵票之勞務。"),
    (18, "肩挑負販沿街叫賣者銷售之貨物或勞務。"),
    (19, "飼料及未經加工之生鮮農、林、漁、牧產物、副產物；農、漁民銷售其收穫、捕獲之農、林、漁、牧產物、副產物。"),
    (20, "漁民銷售其捕獲之魚介。"),
    (21, "稻米、麵粉之銷售及碾米加工。"),
    (22, "依第四章第二節規定計算稅額之營業人，銷售其非經常買進、賣出而持有之固定資產。"),
    (23, "保險業承辦政府推行之軍公教人員與其眷屬保險、勞工保險、學生保險、農、漁民保險、輸出保險及強制汽車第三人責任保險，以及其自保費收入中扣除之再保分出保費、人壽保險提存之責任準備金、年金保險提存之責任準備金及健康保險提存之責任準備金。但人壽保險、年金保險、健康保險退保收益及退保收回之責任準備金，不包括在內。"),
    (24, "各級政府發行之債券及依法應課徵證券交易稅之證券。"),
    (25, "各級政府機關標售賸餘或廢棄之物資。"),
    (26, "銷售與國防單位使用之武器、艦艇、飛機、戰車及與作戰有關之偵訊、通訊器材。"),
    (27, "肥料、農業、畜牧用藥、農耕用之機器設備、農地搬運車及其所用油、電。"),
    (28, "供沿岸、近海漁業使用之漁船、供漁船使用之機器設備、漁網及其用油。"),
    (29, "銀行業總、分行往來之利息、信託投資業運用委託人指定用途而盈虧歸委託人負擔之信託資金收入及典當業銷售不超過應收本息之流當品。"),
    (30, "金條、金塊、金片、金幣及純金之金飾或飾金。但加工費不在此限。"),
    (31, "經主管機關核准設立之學術、科技研究機構提供之研究勞務。"),
    (32, "經營衍生性金融商品、公司債、金融債券、新臺幣拆款及外幣拆款之銷售額。但佣金及手續費不包括在內。"),
]
#: 已刪除的款次：不列入選項
ARTICLE_8_DELETED = {n for n, t in ARTICLE_8_ITEMS if t == "（刪除）"}
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
    "exempt": [("8-%d" % n, "營業稅法 §8 第一項第 %d 款：%s" % (n, t))
               for n, t in ARTICLE_8_ITEMS if n not in ARTICLE_8_DELETED]
              + [("exempt-other", "其他法律規定之免稅（請於說明填寫法條）")],
}
#: 選這些代碼時「說明」必填（§8 已逐款列出 ⇒ 不再要求說明；「其他法律規定」仍要）
TAX_BASIS_NOTE_REQUIRED = {"zero-other", "exempt-other"}
#: 已不在選項裡、但舊資料可能存著的代碼（只用於顯示；新送出的單據要改選）。
#: "8"＝R2 初版的「§8 第一項＋說明填款次」（2026-09-25～26，只在 platform 分支、正式機沒有）。
LEGACY_TAX_BASIS_LABELS = {"8": "營業稅法 §8 第一項（舊選項，款次見說明）"}


def tax_basis_label(basis) -> str:
    """依據的顯示文字（開票申請快照與畫面用）。沒有 ⇒ ''。"""
    if not isinstance(basis, dict):
        return ""
    code = basis.get("code")
    label = next((lb for opts in TAX_BASIS_OPTIONS.values() for c, lb in opts if c == code),
                 LEGACY_TAX_BASIS_LABELS.get(code, ""))
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
        if tax_type == "exempt" and code in LEGACY_TAX_BASIS_LABELS:
            return ("免稅依據已改為逐款選擇，請重新選擇 §8 的款次（原說明：%s）"
                    % (str(basis.get("note") or "").strip() or "—"))
        return f"{name}依據不正確，請重新選擇（{law}）"
    if code in TAX_BASIS_NOTE_REQUIRED and not str(basis.get("note") or "").strip():
        return f"{name}依據選了「{dict(TAX_BASIS_OPTIONS[tax_type])[code]}」，請在說明欄填寫款次或法條"
    return ""


# ── 讀寫設定 ──────────────────────────────────────────────────────────────────

def _backfill(v: dict) -> dict:
    """後加的欄位：舊資料（V9 的 tax_rules、欄位加入前存的清單）沒有 ⇒ 補 115 年簡表的值。
    只補「沒有這個鍵」；存了的值（含錯的）照原樣交給驗證。"""
    nhi = v.get("nhi")
    if isinstance(nhi, dict) and "bonus_insured_multiple" not in nhi:
        nhi["bonus_insured_multiple"] = DEFAULT_TAX_RULE_VERSIONS[0]["nhi"]["bonus_insured_multiple"]
    return v


def load_versions() -> list:
    from helpers.settings import _get_setting
    stored = _get_setting(VERSIONS_KEY, None)
    if isinstance(stored, list) and stored:
        return [_backfill(v) for v in sort_versions(stored)]
    legacy = _get_setting(LEGACY_KEY, None)
    if isinstance(legacy, dict) and legacy:
        v = copy.deepcopy(legacy)
        v.setdefault("version", "2026")
        v.setdefault("effectiveFrom", LEGACY_EFFECTIVE_FROM)
        if "sources" not in v:
            v["sources"] = copy.deepcopy(DEFAULT_TAX_RULE_VERSIONS[0]["sources"])
        return [_backfill(v)]
    return sort_versions(DEFAULT_TAX_RULE_VERSIONS)


def save_versions(versions) -> None:
    from helpers.settings import _set_setting
    _set_setting(VERSIONS_KEY, sort_versions(versions))
