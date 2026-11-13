# -*- coding: utf-8 -*-
"""單據類型（報價單 quote／估價單 estimate）與「單號規則」的唯一來源（2026-11-13，估價單）。

流程（簽核、狀態、權限、轉單、業績）兩種完全相同；只有 ①單號規則（字首）②標題與通知用語不同。

## 單號規則（NumberRule）
單號＝`<字首>-<日期>-<流水號>`（可再加 `-R<n>` 修訂尾巴）。**字首、日期格式、流水號位數都由規則決定**，其餘程式一律問規則、
不自己寫 `MQ-\\d{6}-\\d{3}`、`SUBSTR(quote_no, 11, 3)`、`LENGTH = 13`、`no[3:9]` 這類寫死的位移：
  - `rule_for(doc_type)`：該類型現在的規則（報價單 MQ；估價單＝設定中心「估價單單號字首」，預設 ME）。
  - `rule_of_no(no)`：由單號字首反查規則（目前的兩條規則；查不到＝None）。
  - 規則物件提供 `regex()`／`glob(month)`／`format(month, seq)`／`month_of(no)`／`seq_of(no)`／`seq_start`（SQL SUBSTR 的 1 起算位置）／
    `total_len`／`seq_key(month)`（quote_seq 的鍵）／`max_seq`。
  - `case_no_re()`：稽核／獎金從文字抓「案件單號」用的格式——**由全部規則推導**（MQ＋目前估價單字首），不是多寫死一個 ME。
目前兩條規則的日期都是 `%Y%m`（6 碼）、流水號 3 碼、字首 2 個大寫字母（要改位數／日期格式只改這裡的規則表）。

[單位] helper:doc_type    [層] L1    [穩定度] 契約
[公開介面] DEFAULT_ESTIMATE_PREFIX, ESTIMATE, LABELS, NumberRule, QUOTE, QUOTE_PREFIX, RESERVED_PREFIXES, all_rules, case_no_re,
          doc_type_of_no, estimate_prefix, estimate_prefixes_in_use, label, label_of_no, no_re, norm, prefix_for, relabel, rule_for, rule_of_no,
          seq_key, used_prefixes, validate_prefix
[不變式] ① 單號的字首／日期格式／流水號位數只由 NumberRule 決定，其餘程式不寫死 `MQ-\\d{6}-\\d{3}` 之類（稽核、獎金、通知、PDF 一律問這裡）。
         ② 報價單單號（`MQ-YYYYMM-NNN`）與 `quote_seq` 鍵（`YYYYMM`）不因估價單而改變；估價單字首改過後，舊字首的單號仍被認得。
         ③ 本檔不讀 `quotations` 表：歷史字首經串接點 `case.estimate_prefixes`（IP-ESTQ1）由 M01 提供，M01 不在 ⇒ 只認目前規則。
[契約題] backend/tests/test_estimate_doc_type_2026_11_13.py
"""
import re
from datetime import datetime

QUOTE = "quote"
ESTIMATE = "estimate"
LABELS = {QUOTE: "報價單", ESTIMATE: "估價單"}
QUOTE_PREFIX = "MQ"
DEFAULT_ESTIMATE_PREFIX = "ME"

#: 各類型單號規則的固定部分（日期格式、流水號位數）。字首：報價單固定 MQ；估價單取設定（下面 estimate_prefix）。
_DATE_FMT = "%Y%m"
_SEQ_DIGITS = 3

#: 全站已被其他單據使用的 2 字母字首（含歷史）——估價單字首不可以跟它們撞（單號是主鍵、多處以字首辨識單據）。
RESERVED_PREFIXES = frozenset({
    "MQ", "BN", "BR", "CN", "DN", "DP", "EL", "ET", "IP", "IV", "LA", "LC", "MC", "MO", "MP", "NP", "PC", "PO", "PR", "PS",
    "PV", "RP", "RQ", "SN", "TE", "TR", "WA", "WB", "XX", "YA",
    "BT", "LN", "HC", "LV", "OT", "QT",            # 站內表單範本（出差、器材借用、人力需求、請假、加班、報價）
})   # 靜態保底；真正的檢查看 used_prefixes()（再加上表單範本檔、已發布的自訂模組、費用類型現在實際用的前綴）
_PREFIX_RE = re.compile(r"^[A-Z]{2}$")


class NumberRule:
    """一種單據的單號規則：字首、日期格式（strftime）、流水號位數。所有「單號長什麼樣」的問題都問它。"""

    __slots__ = ("doc_type", "prefix", "date_fmt", "seq_digits", "date_len")

    def __init__(self, doc_type, prefix, date_fmt=_DATE_FMT, seq_digits=_SEQ_DIGITS):
        self.doc_type = doc_type
        self.prefix = prefix
        self.date_fmt = date_fmt
        self.seq_digits = seq_digits
        self.date_len = len(datetime(2000, 1, 1).strftime(date_fmt))

    # ── 形狀 ──
    @property
    def total_len(self):                    # <字首>-<日期>-<流水號>
        return len(self.prefix) + 1 + self.date_len + 1 + self.seq_digits

    @property
    def seq_start(self):                    # SQL SUBSTR 用（1 起算）：流水號第一碼的位置
        return len(self.prefix) + 1 + self.date_len + 1 + 1

    @property
    def max_seq(self):
        return 10 ** self.seq_digits - 1

    def regex(self, *, revision=False):
        """完整單號格式（含日期、流水號）；`revision=True` 另允許 `-R<n>` 修訂尾巴。"""
        tail = r"(?:-R\d+)?" if revision else ""
        return re.compile(r"^%s-\d{%d}-\d{%d}%s$" % (re.escape(self.prefix), self.date_len, self.seq_digits, tail))

    def search_pattern(self):
        """從一段文字裡抓單號用的（不含 ^ $）。"""
        return r"%s-\d{%d}-\d{%d}" % (re.escape(self.prefix), self.date_len, self.seq_digits)

    def glob(self, month):
        """SQLite GLOB：該月所有（不含修訂尾巴的）單號。"""
        return "%s-%s-%s" % (self.prefix, month, "?" * self.seq_digits)

    def format(self, month, seq):
        return "%s-%s-%0*d" % (self.prefix, month, self.seq_digits, int(seq))

    # ── 解析 ──
    def month_of(self, no):
        no = str(no or "")
        return no[len(self.prefix) + 1: len(self.prefix) + 1 + self.date_len]

    def seq_of(self, no):
        no = str(no or "")
        m = re.match(r"\d+", no[len(self.prefix) + 1 + self.date_len + 1:])      # 流水號用完位數（例如 1000）時也要讀得出來
        return int(m.group(0)) if m else 0

    def seq_key(self, month):
        """quote_seq 的鍵：報價單＝'YYYYMM'（與改版前相同，舊資料不用搬）；其他＝'<字首>-YYYYMM'（各自流水號）。"""
        return month if self.doc_type == QUOTE else "%s-%s" % (self.prefix, month)

    def owns(self, no):
        return str(no or "").startswith(self.prefix + "-")

    def __repr__(self):
        return "NumberRule(%s,%s,%s,%d)" % (self.doc_type, self.prefix, self.date_fmt, self.seq_digits)


def norm(v):
    """任意輸入 → 'quote'／'estimate'。不認得、空、None ⇒ 'quote'（舊資料一律是報價單）。"""
    return ESTIMATE if (isinstance(v, str) and v.strip().lower() == ESTIMATE) else QUOTE


def label(doc_type):
    return LABELS[norm(doc_type)]


def label_of_no(no, conn=None):
    """單號 → 單據類型名稱（報價單／估價單）。只有單號、沒有 `doc_type` 欄位可用的地方（通知信、PDF 上「關聯單據」的字樣）用這支；
    手上有 `quotations.doc_type` 的地方照舊用 `label(doc_type)`（欄位才是權威，這支只看字首）。查不到字首 ⇒ 報價單。"""
    return label(doc_type_of_no(no, conn))


def used_prefixes(conn=None):
    """⇒ `{前綴: 說明}`：現在實際有效的各種單據單號前綴——靜態保底清單＋表單範本＋已發布的自訂模組＋費用類型（預設＋公司另外發布）。
    估價單字首用它擋撞號；反方向（自訂模組／費用類型的前綴不可等於估價單字首）見 estimate_prefixes_in_use。"""
    out = {p: "其他單據" for p in RESERVED_PREFIXES}
    own = None
    try:
        if conn is None:
            import db
            own = conn = db.get_db()
        from helpers import custom_modules as _cm, expense_types as _et
        for src in (_cm.used_prefixes, _et.used_prefixes):
            try:
                for k, v in src(conn).items():
                    out.setdefault(k, v)
            except Exception:                                                                # noqa: BLE001 — 某一來源讀不到不可擋設定
                pass
    except Exception:                                                                        # noqa: BLE001
        pass
    finally:
        if own is not None:
            own.close()
    return out


def estimate_prefixes_in_use(conn=None):
    """目前的估價單字首＋曾經用過的（歷史）——別的單據（自訂模組、費用類型）的前綴不可與它們相同。"""
    return {rule_for(ESTIMATE, conn).prefix, *_historical_estimate_prefixes(conn)}


def validate_prefix(p, conn=None):
    """估價單字首是否合法；回問題描述字串，合法回 ''。不可撞到任何現在實際有效的單據前綴（used_prefixes）。"""
    if not isinstance(p, str) or not _PREFIX_RE.match(p):
        return "必須是 2 個大寫英文字母（例如 ME）"
    hit = used_prefixes(conn).get(p)
    if hit:
        return "「%s」已被%s使用，請換一組" % (p, hit)
    return ""


def estimate_prefix(conn=None):
    """目前的估價單字首（設定 quote_defaults.estimate_no_prefix；讀不到／不合法 ⇒ ME）。
    **熱路徑**（每次稽核寫入、取號、PDF、通知都會呼叫）：這裡只做格式＋靜態保留清單的便宜檢查，不碰資料庫、不讀檔；
    和其他單據前綴有沒有撞，只在「存設定」的當下查（validate_prefix → used_prefixes，見 settings_groups_profit）。"""
    try:
        from helpers import settings_registry as sr
        v = sr.get("quote_defaults", "estimate_no_prefix", conn=conn)
        if isinstance(v, str):
            v = v.strip().upper()
            if _PREFIX_RE.match(v) and v not in RESERVED_PREFIXES:
                return v
    except Exception:                                                                    # noqa: BLE001 — 讀不到設定不可擋開單
        pass
    return DEFAULT_ESTIMATE_PREFIX


def rule_for(doc_type, conn=None):
    """該單據類型現在的單號規則。"""
    if norm(doc_type) == ESTIMATE:
        return NumberRule(ESTIMATE, estimate_prefix(conn))
    return NumberRule(QUOTE, QUOTE_PREFIX)


_HIST_CACHE = {"v": (None, ())}


def _historical_estimate_prefixes(conn=None):
    """曾經開過估價單的字首（不含目前字首／MQ）。改了字首之後，舊字首開出去的單號仍要認得（稽核搜尋、獎金推導案件單號）。
    資料屬 M01（quotations.doc_type）⇒ L1 不讀那張表，經串接點 `case.estimate_prefixes`（IP-ESTQ1）取；M01 不在 ⇒ 空。
    依「設定世代＋資料庫」快取：字首只會因設定變更而新增，設定一變世代就變、下次重查，平常不碰資料庫。"""
    try:
        import db
        from core import registry
        from helpers import settings_registry as sr
        key = (sr.generation(), str(getattr(db, "DB_PATH", "")))
        hit = _HIST_CACHE["v"]                       # (key, prefixes) 是一個物件、一次讀一次寫：不會讀到新 key 配舊字首
        if hit[0] == key:
            return hit[1]
        fn = registry.single_provider("case.estimate_prefixes")
        raw = fn(conn) if fn is not None else ()
        got = tuple(sorted(p for p in raw if p and _PREFIX_RE.match(p) and p != QUOTE_PREFIX))
        _HIST_CACHE["v"] = (key, got)
        return got
    except Exception:                                                                    # noqa: BLE001 — 讀不到歷史字首不可擋開單／稽核
        return ()


def all_rules(conn=None):
    """全部規則：報價單、目前的估價單，再加上「曾經用過的估價單字首」（改字首後舊單號仍可辨識）。報價單在前、目前估價單第二。"""
    cur = rule_for(ESTIMATE, conn)
    rules = [rule_for(QUOTE, conn), cur]
    for p in _historical_estimate_prefixes(conn):
        if p != cur.prefix:
            rules.append(NumberRule(ESTIMATE, p))
    return rules


def rule_of_no(no, conn=None):
    """由單號的字首反查規則（目前的兩條＋曾用過的估價單字首）；查不到 ⇒ None。正式判定以 quotations.doc_type 欄位為準。"""
    for r in all_rules(conn):
        if r.owns(no):
            return r
    return None


def prefix_for(doc_type, conn=None):
    return rule_for(doc_type, conn).prefix


def seq_key(no):
    """單號 → quote_seq 的鍵（與單號的字首無關的通則：MQ＝'YYYYMM'；其他字首＝'XX-YYYYMM'）。"""
    no = str(no or "")
    r = rule_of_no(no)
    if r is not None:
        return r.seq_key(r.month_of(no))
    # 字首不是目前任何一條規則（例如改過字首之後的舊估價單號）：用同一套形狀通則推
    if len(no) >= 3 and no[2] == "-" and no[:2] != QUOTE_PREFIX:
        return no[:2 + 1 + _date_len()]
    return no[3:3 + _date_len()]


def _date_len():
    return len(datetime(2000, 1, 1).strftime(_DATE_FMT))


def doc_type_of_no(no, conn=None):
    """只看單號字首判類型（資料庫查不到時的後備）：目前估價單字首 ⇒ estimate；其他 ⇒ quote。
    正式判定以 quotations.doc_type 欄位為準。"""
    r = rule_of_no(no, conn)
    return r.doc_type if r is not None else QUOTE


def no_re(prefix_or_rule, *, revision=False):
    """某字首（或規則）的完整單號格式。傳字串＝以預設日期格式／位數建規則。"""
    r = prefix_or_rule if isinstance(prefix_or_rule, NumberRule) else NumberRule(ESTIMATE if prefix_or_rule != QUOTE_PREFIX else QUOTE, prefix_or_rule)
    return r.regex(revision=revision)


_CASE_RE_CACHE = {}


def case_no_re(conn=None):
    """稽核／獎金從文字裡抓「案件單號」用的格式——由全部規則推導（報價單 MQ＋目前估價單字首＋曾用過的估價單字首）。依規則組合快取。"""
    pats = tuple(r.search_pattern() for r in all_rules(conn))
    rx = _CASE_RE_CACHE.get(pats)
    if rx is None:
        rx = _CASE_RE_CACHE[pats] = re.compile("(?:%s)" % "|".join(pats))
    return rx


def relabel(text, doc_type):
    """站內訊息／文字用：估價單 ⇒ 把「報價單」換成「估價單」；報價單（含 None／未知）⇒ 原字串不動。"""
    if text is None or norm(doc_type) != ESTIMATE:
        return text
    return str(text).replace(LABELS[QUOTE], LABELS[ESTIMATE])
