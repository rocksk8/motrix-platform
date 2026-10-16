# -*- coding: utf-8 -*-
"""T64 A 設定群組：利潤提醒色帶（profit_warning）與報價單預設值（quote_defaults）。**預設值＝各畫面今天寫死的數字**（部署零行為變更）。

[單位] helper:settings_groups_profit    [層] L1    [穩定度] 實驗
[公開介面] register
[不變式] ①利潤提醒只改顏色／提示字，不擋存檔、不改金額、不改送審；故無放寬／收緊之分（立即生效）。
    ②預設有效天數不得高於 quote_approval.max_valid_days（否則每張新單一開始就要送審）；送審判斷仍由伺服器重算。
    ③（T68 Q1）profit_rules.charity_rate_pct 會改金額（公益金）⇒ risk=money；調低＝放寬（營業利益變高），走確認期間＋第二位最高管理者核准（D-K1）；調高立即生效。
[契約題] backend/tests/platform/test_profit_warning_t64.py
"""

_DISPLAY_NOTE = "只改顏色與提示字，不影響存檔、送審、審核與任何金額；沒有放寬或收緊之分，立即生效。"


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _profit_cross_check(values):
    """每一組『紅線 ≤ 達標線』。引擎第一道檢查只帶改動欄位（其餘補預設），所以沒帶的欄位改讀目前已存值（讀不到 ⇒ 用預設）。"""
    from helpers.profit_warning import DEFAULTS, _PAIRS
    try:
        from helpers import settings_registry as _SR
        stored = _SR.get_group("profit_warning")
    except Exception:                                                                    # noqa: BLE001
        stored = dict(DEFAULTS)
    names = {"quote_form": "報價單表單", "report": "報表頁", "case": "案件頁／結算摘要"}
    out = []
    for lo, hi in _PAIRS:
        a = _num(values.get(lo)) if lo in values else _num(stored.get(lo))
        b = _num(values.get(hi)) if hi in values else _num(stored.get(hi))
        if a is not None and b is not None and a > b:
            out.append("%s的紅線（%g%%）不能高於達標線（%g%%）。" % (names[lo.rsplit("_", 1)[0]], a, b))
    return out


def _valid_days_cross_check(values):
    """預設有效天數不得超過『報價單有效天數上限』（quote_approval.max_valid_days）；沒帶的欄位讀目前已存值。"""
    try:
        from helpers import settings_registry as _SR
        cap = _num(_SR.get("quote_approval", "max_valid_days"))
    except Exception:                                                                    # noqa: BLE001 — 讀不到已存值 ⇒ 不擋（使用端仍以伺服器送審為準）
        return []
    v = _num(values.get("valid_days"))
    if v is not None and cap is not None and v > cap:
        return ["預設有效天數（%g 天）不能超過「報價單有效天數上限」（%g 天）；請先到「報價送審門檻」調整上限。" % (v, cap)]
    return []


def register(S, _register_core):
    def pct(name, default, label, question, where, lo=0, hi=100, extra=""):
        return S(name, "float", default, min=lo, max=hi, unit="%", risk="none", recommended=default,
                 question=question, label=label,
                 help="%s目前的預設是 %g%%（＝這個畫面原本的做法）。%s" % (where, default, extra),
                 impact="影響範圍：%s。%s" % (where.rstrip("。"), _DISPLAY_NOTE))

    _register_core(
        "profit_warning", "利潤提醒色帶",
        [
            pct("quote_form_low", 12, "報價單表單紅線", "報價單表單上，營業利益率低於多少要顯示紅色警示？",
                "報價單表單右側的營業利益率低於這個數字會變紅、並顯示「低於目標」。"),
            pct("quote_form_good", 20, "報價單表單達標線", "報價單表單上，營業利益率達到多少才顯示綠色？",
                "報價單表單的營業利益率介於紅線與這個數字之間顯示黃色，達到這個數字顯示綠色。", extra="不可低於紅線。"),
            pct("report_low", 10, "報表頁紅線", "報表頁的分項利潤率低於多少要顯示紅色？",
                "報表頁分項表格的營業利益率低於這個數字顯示紅色。"),
            pct("report_good", 20, "報表頁達標線", "報表頁的分項利潤率達到多少才顯示綠色？",
                "報表頁分項表格的營業利益率達到這個數字顯示綠色，介於紅線與此之間顯示橘色。", extra="不可低於紅線。"),
            pct("case_floor", 0, "案件頁與結算摘要紅線", "案件頁、報表結算摘要與結算 PDF，營業利益率低於多少要顯示紅色？",
                "案件頁、報表結算摘要與結算 PDF 的營業利益率低於這個數字顯示紅色（預設 0＝虧損才紅）。可設負數。", lo=-100),
            pct("case_good", 20, "案件頁與結算摘要達標線", "案件頁、報表結算摘要與結算 PDF，營業利益率達到多少才顯示綠色？",
                "案件頁、報表結算摘要與結算 PDF 的營業利益率達到這個數字顯示綠色，介於紅線與此之間顯示黃色。", extra="不可低於紅線。"),
            pct("settlement_good", 20, "結算頁達標線", "結算頁的營業利益率達到多少才顯示綠色？",
                "結算頁摘要的營業利益率達到這個數字顯示綠色，其餘顯示紅色。"),
        ],
        sensitive=False, risk="none", cross_check=_profit_cross_check,
        help="各畫面的利潤顏色門檻。只改顏色與提示字；每個畫面各自一組，預設都是該畫面原本的數字。",
    )

    _register_core(
        "quote_defaults", "報價單預設值",
        [
            S("valid_days", "int", 30, min=1, max=365, unit="天", risk="none", recommended=30,
              question="新報價單預設的有效天數要幾天？", label="新報價單預設有效天數",
              help="新增報價單時，「有效天數」欄位預先帶入的數字，業務仍可逐張修改。不可超過「報價單有效天數上限」，否則每張新單一開始就會被列為『有效期限過長』。預設 30。",
              impact="只影響之後新增的報價單的預設值；已存的報價單不變。這個預設值本身不放寬也不收緊審核（超過上限仍由伺服器列為審核原因）。立即生效。注意：之後若把「報價單有效天數上限」調到低於這個預設，每張新報價單一開始就會被列為『有效期限過長』而需要審核，請一併調整。"),
        ],
        sensitive=False, risk="none", cross_check=_valid_days_cross_check,
        help="新增報價單時預先帶入的值；業務可逐張修改。",
    )

    _register_core(
        "profit_rules", "利潤口徑",
        [
            S("charity_rate_pct", "float", 1, min=0, max=10, unit="%", risk="money", loosen="down", recommended=1,
              risk_text="【高影響】調低公益捐款比率後，新算的報價單與精算會少扣公益金、營業利益變高，並影響獎金基數與營運報表；已完結精算的存檔公益金不會被改寫。",
              impact_scope={"documents": ["報價單", "精算", "營運報表", "結案精算"], "roles": ["業務", "最高管理者", "財務"],
                            "amounts": "改變之後新算的公益金與營業利益（報價 PDF「公益捐款」列、精算頁、營運報表同步）；不改已完結精算的存檔值。",
                            "reversible": True, "effective": "pending"},
              question="公益捐款要扣報價（或直接毛利）的百分之幾？", label="公益捐款比率",
              help="報價單與精算的「公益捐款」＝基數 × 這個比率（基數是直接毛利或報價含稅金額，由既有的公益基數開關決定）。預設 1％（＝目前的做法）。",
              impact="調高＝多扣公益金（立即生效）；調低＝少扣公益金、營業利益變高（放寬，需第二位最高管理者核准並經確認期間）。只影響之後新算的數字；已完結精算的存檔公益金不回頭改寫。"),
        ],
        sensitive=True, risk="money",
        help="報價單與精算的公益捐款比率；管銷比率另在精算頁／管銷設定調整，營業利益率目標沿用「利潤提醒色帶」的報價單紅線。",
    )
