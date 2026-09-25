"""獎金分潤（以案件為中心，SPEC-BONUS §十一／§11.7，2026-09-24）的分配計算。

純函式，不碰資料庫——算式要能單獨驗。

```
獎金池 = floor(淨利 × 比率)                          比率預設 10%（1000 基點）
三類   = 業務／專案／後勤（預設 5000／3000／2000 基點，合計須 10000）
類金額 = floor(獎金池 × 類比例)
類內   = 預設平均：每人 floor(類金額／人數)，零頭留公司（§11.7，使用者「每人一樣多，零頭留公司」）
         改過個人比例：每人 floor(獎金池 × 類比例 × 個人比例)（§11.2），該類個人比例合計須 10000
某類沒有人 ⇒ 該類不發（留公司）
尾差   = 獎金池 − 全部個人金額合計（留公司）
```
⚠️ 這裡的 10% 是**獎金比率**，與 settlement.html 的管理費 10%／公益 1% 無關（§11.2），不共用常數。
⚠️ 淨利用精算已存的 `settlement.summary.netProfit`，不自己重算、也不退回 grossProfit（§二禁令）。
"""
from decimal import Decimal, ROUND_FLOOR, InvalidOperation

CATEGORIES = ("sales", "project", "admin")
CATEGORY_LABELS = {"sales": "業務", "project": "專案", "admin": "後勤"}
DEFAULT_RATE_BP = 1000
DEFAULT_SPLIT_BP = {"sales": 5000, "project": 3000, "admin": 2000}
BP = 10000


class BonusCalcError(ValueError):
    """輸入不合法（訊息可以直接給使用者看）。"""


def _to_decimal(v) -> Decimal:
    if isinstance(v, bool):
        raise BonusCalcError("淨利必須是數字")
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise BonusCalcError("淨利必須是數字")
    if not d.is_finite():
        raise BonusCalcError("淨利必須是數字")
    return d


def _bp(v, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > BP:
        raise BonusCalcError(f"{what}必須是 0～10000 的整數基點")
    return v


def pool_amount(net_profit, rate_bp: int) -> int:
    """獎金池。淨利 ≤ 0 ⇒ 不能建立（§11.1「無獎金」）。"""
    net = _to_decimal(net_profit)
    if net <= 0:
        raise BonusCalcError("這個案件的精算淨利不大於 0，沒有獎金可以分配")
    rate = _bp(rate_bp, "獎金比率")
    if rate == 0:
        raise BonusCalcError("獎金比率不可以是 0")
    return int((net * rate / BP).to_integral_value(rounding=ROUND_FLOOR))


def allocate(net_profit, rate_bp: int, split_bp: dict, members: dict) -> dict:
    """members：{category: [{"username": str, "person_bp": int | None}, ...]}

    同一類裡 person_bp 要嘛全部是 None（平均），要嘛全部有值且合計 10000——
    混用沒有定義，直接拒絕，不猜。
    回傳 {"pool", "categories": {cat: {"amount", "mode", "lines": [{"username","person_bp","amount"}]}},
          "paid_total", "remainder"}
    """
    pool = pool_amount(net_profit, rate_bp)
    split = {c: _bp((split_bp or {}).get(c, 0), f"{CATEGORY_LABELS[c]}比例") for c in CATEGORIES}
    if sum(split.values()) != BP:
        raise BonusCalcError("業務／專案／後勤三類比例合計必須是 100%")
    out = {"pool": pool, "categories": {}, "paid_total": 0, "remainder": 0}
    for c in CATEGORIES:
        cat_amount = pool * split[c] // BP
        people = list((members or {}).get(c) or [])
        names = [p.get("username") for p in people]
        if any(not n for n in names) or len(set(names)) != len(names):
            raise BonusCalcError(f"{CATEGORY_LABELS[c]}名單有空白或重複的人員")
        custom = [p.get("person_bp") is not None for p in people]
        lines = []
        if not people:
            mode = "none"
        elif not any(custom):
            mode = "average"
            each = cat_amount // len(people)
            lines = [{"username": p["username"], "person_bp": None, "amount": each} for p in people]
        elif all(custom):
            mode = "custom"
            bps = [_bp(p["person_bp"], f"{CATEGORY_LABELS[c]}個人比例") for p in people]
            if sum(bps) != BP:
                raise BonusCalcError(f"{CATEGORY_LABELS[c]}的個人比例合計必須是 100%")
            lines = [{"username": p["username"], "person_bp": b, "amount": pool * split[c] * b // (BP * BP)}
                     for p, b in zip(people, bps)]
        else:
            raise BonusCalcError(f"{CATEGORY_LABELS[c]}的個人比例要嘛全部平均、要嘛全部指定")
        out["categories"][c] = {"split_bp": split[c], "amount": cat_amount, "mode": mode, "lines": lines}
        out["paid_total"] += sum(l["amount"] for l in lines)
    out["remainder"] = pool - out["paid_total"]
    assert out["remainder"] >= 0
    return out
