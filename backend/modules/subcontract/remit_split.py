# -*- coding: utf-8 -*-
"""匯款分期的金額規則（31-B S1；設計 docs/platform/plans/REMIT-KINDS-31B-DESIGN.md §4）——純函式，後端建立與前端預覽試算共用同一支。

[單位] m04:remit_split    [層] L2（M04 subcontract）    [穩定度] 實驗（31-B 逐切片補齊）
[公開介面] RemitSplitError, plan
[不變式] 不碰資料庫、不 import 其他模組；金額一律整數元、用 `helpers.legal_params.round_half_up`（Decimal，不經浮點）。

使用者裁示 2026-10-02：D3＝比例或固定金額都可以；D4＝逐期算稅、最後一期補到與整筆一致、畫面顯示差額。
記號：`T`＝派發稅前總額、`r`＝稅率、`X = round_half_up(T×r)`＝整筆稅額、`R = T − Σ前期稅前`＝剩餘額度。
- 比例模式：`A = round_half_up(T × p)`（`0 < p ≤ 1`）；固定金額模式：`A` 為整數元（≥1）。兩者都不得超過 `R`。
- **最後一期**＝使 `R` 歸零的那一期：固定金額 `A == R`；比例模式累計比例 ≥ 100%（前期比例申請用其比例、固定金額申請用 `A/T`，容許 1e-9），
  或算出的 `A == R`。最後一期的稅前一律取 `R`（補尾差）。
- 稅額：非最後一期 `round_half_up(A × r)`；最後一期 `X − Σ前期稅額`，補差 `d = tax − round_half_up(A × r)`（通常 0，偶爾 ±1～±2）。⇒ 全部期別稅額合計恆等於 `X`；唯一例外：前期稅額合計已超過 `X`（逐期進位）時，最後一期稅額取 0 並警示，合計多出前期超出的部分。
- 派發金額帶角分時（REAL 欄）由呼叫端四捨五入成整數元再傳入，並警示。
"""
from decimal import Decimal

from helpers.legal_params import round_half_up

EPS = Decimal("1E-9")


class RemitSplitError(ValueError):
    """輸入不合法（訊息可直接給使用者）。"""


def _dec(v, label):
    try:
        d = Decimal(str(v))
    except Exception:                                              # noqa: BLE001
        raise RemitSplitError("%s不是數字：%r" % (label, v))
    if not d.is_finite():
        raise RemitSplitError("%s不是有限的數字" % label)
    return d


def _int_yuan(v, label):
    d = _dec(v, label)
    if d != d.to_integral_value():
        raise RemitSplitError("%s必須是整數元（目前是 %s）" % (label, v))
    return int(d)


def plan(total, rate, previous, mode, value):
    """試算一期。
    `total`＝派發稅前總額（整數元）；`rate`＝稅率（0～1，例 0.05）；`previous`＝**未作廢**的前期 `[{"pretax": 整數元, "tax": 整數元, "ratio": 比例或 None}]`；
    `mode`＝`"ratio"`（`value`＝比例 0～1，例 0.3）或 `"amount"`（`value`＝稅前整數元）。
    ⇒ `{"pretax", "tax", "is_last", "make_up", "remaining_before", "remaining_after", "total_tax", "tax_sum_after", "cum_ratio", "near_complete", "warnings"}`。
    不合法 ⇒ RemitSplitError。"""
    T = _int_yuan(total, "派發稅前總額")
    if T <= 0:
        raise RemitSplitError("派發稅前總額必須大於 0")
    r = _dec(rate, "稅率")
    if r < 0 or r >= 1:
        raise RemitSplitError("稅率必須在 0 到 1 之間（例：5%% 寫 0.05），目前是 %s" % rate)
    if mode not in ("ratio", "amount"):
        raise RemitSplitError("輸入方式只能是 ratio（比例）或 amount（固定金額）")
    prev = list(previous or [])
    prev_pre = [_int_yuan(p.get("pretax"), "前期稅前金額") for p in prev]
    prev_tax = [_int_yuan(p.get("tax"), "前期稅額") for p in prev]
    if any(x < 1 for x in prev_pre):
        raise RemitSplitError("前期稅前金額必須是正整數")
    remaining = T - sum(prev_pre)
    if remaining <= 0:
        raise RemitSplitError("這張派發的稅前金額已經全部申請完了（剩餘 0 元），不能再開")
    X = int(round_half_up(T, r))
    prev_cum = sum((_dec(p["ratio"], "前期比例") if p.get("ratio") is not None else Decimal(a) / Decimal(T)) for p, a in zip(prev, prev_pre))

    near = False
    cum = None
    if mode == "amount":
        A = _int_yuan(value, "本期金額")
        if A < 1:
            raise RemitSplitError("本期金額必須至少 1 元")
        if A > remaining:
            raise RemitSplitError("本期金額 %d 元超過剩餘額度 %d 元" % (A, remaining))
        is_last = A == remaining
        cum = prev_cum + Decimal(A) / Decimal(T)
    else:
        p = _dec(value, "本期比例")
        if p <= 0 or p > 1:
            raise RemitSplitError("本期比例必須大於 0 且不超過 100%")
        cum = prev_cum + p
        if cum > 1 + EPS:
            raise RemitSplitError("累計比例會到 %s%%，超過 100%%（前期已用 %s%%）" % ((cum * 100).quantize(Decimal("0.01")), (prev_cum * 100).quantize(Decimal("0.01"))))
        A = int(round_half_up(T, p))
        is_last = cum >= 1 - EPS or A == remaining
        if is_last:
            A = remaining                                           # 補尾差：最後一期取剩餘額
        elif A < 1:
            raise RemitSplitError("本期比例太小，換算出來不到 1 元")
        elif A > remaining:
            raise RemitSplitError("本期金額 %d 元超過剩餘額度 %d 元" % (A, remaining))
        else:
            near = (remaining - A) <= 1
    own_tax = int(round_half_up(A, r))
    if is_last:
        tax = max(X - sum(prev_tax), 0)                             # 前期逐期進位可能讓稅額合計超過整筆稅額：最後一期稅額取 0，不擋（否則剩餘額度用不掉）
    else:
        tax = own_tax
    make_up = tax - own_tax
    warnings = []
    if is_last and sum(prev_tax) > X:
        warnings.append("前期稅額合計 %d 元已超過整筆稅額 %d 元（逐期進位），本期稅額取 0，整筆稅額合計多出 %d 元，待會計確認" % (sum(prev_tax), X, sum(prev_tax) - X))
    elif make_up:
        warnings.append("最後一期含補差 %+d 元：整筆稅額 %d 元，前期稅額合計 %d 元，本期逐期算是 %d 元，待會計確認發票稅額" % (make_up, X, sum(prev_tax), own_tax))
    if near:
        warnings.append("再填一期就會補齊（剩餘 %d 元）" % (remaining - A))
    return {"pretax": A, "tax": tax, "is_last": bool(is_last), "make_up": make_up, "remaining_before": remaining, "remaining_after": remaining - A,
            "total_tax": X, "tax_sum_after": sum(prev_tax) + tax, "cum_ratio": float(cum), "near_complete": near, "warnings": warnings}
