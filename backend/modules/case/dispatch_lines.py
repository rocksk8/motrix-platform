"""精算：承攬商派發單「逐行」對應的純函式（行鍵、ref 組合／解析、稅額分攤、拆分份稅額）。

規格：docs/platform/plans/DISPATCH-LINE-LINKAGE-PROPOSAL.md。本檔不讀資料庫、不碰派發單；金額與稅額一律以「整數分」＋ Decimal 運算（不用浮點）。

`offsets[].ref`（kind＝dispatch）三種寫法：
    <派發id>                      整張（舊語意）
    <派發id>#<行鍵>               整行（不帶 amount）
    <派發id>#<行鍵>#<份次>         拆分份（必帶 amount＝未稅金額，> 0、最多 2 位小數）
行鍵＝派發單 items_json 該行 id 的正規化字串（與 JS `String(x)` 逐字相同），再做 `%`→`%25`、`#`→`%23`。前端 settlement.html 有同一組規則（V7 跨語言向量鎖住兩端一致）。
"""
import re
from decimal import ROUND_HALF_UP, Decimal

MAX_PARTS_PER_LINE = 20
_KEY_RE = re.compile(r"(?:[^%#]|%25|%23)+")
_PART_RE = re.compile(r"[1-9][0-9]*")


# ── 行鍵 ──────────────────────────────────────────────────────────────────────

def _js_number_to_string(x: float) -> str:
    """ECMAScript Number::toString（十進位）：以 repr 取最短還原的有效位數與指數，再依 JS 規則排版（1e21 以上、1e-7 以下才用科學記號）。"""
    if x != x or x in (float("inf"), float("-inf")):
        return ""                                                    # NaN／Infinity 不是合法行鍵
    if x == 0:
        return "0"                                                   # JS：String(-0) === "0"
    sign = "-" if x < 0 else ""
    _, digits_t, exp = Decimal(repr(abs(x))).as_tuple()
    digits = "".join(str(d) for d in digits_t).rstrip("0") or "0"
    n = len(digits_t) + exp                                          # 小數點位置：值 = 0.digits × 10^n
    k = len(digits)
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * (-n) + digits
    e = n - 1
    mant = digits[0] + ("." + digits[1:] if k > 1 else "")
    return "%s%se%s%d" % (sign, mant, "+" if e >= 0 else "-", abs(e))


def raw_key(raw) -> str:
    """行 id ⇒ 未編碼的正規化字串：數字＝整數值寫整數（`1.0`→`"1"`），其餘同 JS `String(x)`；字串去頭尾空白；缺／布林／NaN／其他 ⇒ `""`。"""
    if raw is None or isinstance(raw, bool):
        return ""
    if isinstance(raw, int):
        return str(raw) if abs(raw) <= 2 ** 53 else _js_number_to_string(float(raw))      # JS 的 number 超過 2^53 就失去精度：兩端都以浮點為準
    if isinstance(raw, float):
        return _js_number_to_string(raw)
    if isinstance(raw, str):
        return raw.strip()
    return ""


def encode_key(s: str) -> str:
    return s.replace("%", "%25").replace("#", "%23")


def decode_key(s: str) -> str:
    return s.replace("%23", "#").replace("%25", "%")


def line_key(raw) -> str:
    """行 id ⇒ 行鍵（已做 `%`／`#` 編碼，可直接放進 ref）；缺 id ⇒ `""`（不可逐行對應）。"""
    return encode_key(raw_key(raw))


# ── ref 組合／解析（互為反函數）────────────────────────────────────────────────

def format_ref(dispatch_id, key=None, part=None) -> str:
    """`format_ref(101)`＝整張；`(101, k)`＝整行；`(101, k, 2)`＝拆分份。`key` 須已編碼（`line_key` 的輸出）。"""
    ref = str(dispatch_id)
    if key is not None:
        ref += "#" + key
        if part is not None:
            ref += "#" + str(int(part))
    return ref


def parse_ref(ref):
    """⇒ `{"dispatch": str, "key": str|None, "part": int|None, "level": "dispatch"|"line"|"part"}`；格式不合法回 None。
    合法：派發 id 非空且不含 `#`；行鍵非空且只含 `[^%#]`、`%25`、`%23`；份次為不含前導 0 的正整數字串。"""
    if not isinstance(ref, str) or not ref:
        return None
    segs = ref.split("#")
    if len(segs) > 3 or not segs[0] or segs[0] != segs[0].strip():
        return None
    if len(segs) == 1:
        return {"dispatch": segs[0], "key": None, "part": None, "level": "dispatch"}
    if not _KEY_RE.fullmatch(segs[1]):
        return None
    if len(segs) == 2:
        return {"dispatch": segs[0], "key": segs[1], "part": None, "level": "line"}
    if not _PART_RE.fullmatch(segs[2]):
        return None
    return {"dispatch": segs[0], "key": segs[1], "part": int(segs[2]), "level": "part"}


# ── 金額（整數分）────────────────────────────────────────────────────────────

def to_dec(x) -> Decimal:
    """浮點 ⇒ Decimal（最短表示，與 legal_params._dec 相同）；壞值 ⇒ 0。"""
    if isinstance(x, bool) or x is None:
        return Decimal(0)
    if isinstance(x, Decimal):
        return x
    if isinstance(x, int):
        return Decimal(x)
    try:
        return Decimal(repr(float(x))) if not isinstance(x, str) else Decimal(x.strip() or "0")
    except Exception:                                                                              # noqa: BLE001
        return Decimal(0)


def cents(x) -> int:
    """金額 ⇒ 整數分（四捨五入到分）。"""
    return int((to_dec(x) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def parse_amount(raw):
    """拆分份的 amount ⇒ 整數分；非數字／布林／NaN／≤0／超過 2 位小數 ⇒ None。"""
    if raw is None or isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return None
    try:
        d = to_dec(raw) if not isinstance(raw, str) else Decimal(raw.strip())
    except Exception:                                                                              # noqa: BLE001
        return None
    if not d.is_finite() or d <= 0:
        return None
    c = d * 100
    r = c.to_integral_value(rounding=ROUND_HALF_UP)
    if abs(c - r) > Decimal("1e-6"):                                  # 超過 2 位小數；容許 0.1＋0.2＝0.30000000000000004 這種浮點雜訊（以分正規化）
        return None
    return int(r) if r > 0 else None


def amount_out(c: int):
    """整數分 ⇒ JSON 數字（整數元回 int，否則 float）。"""
    return c // 100 if c % 100 == 0 else c / 100


def _rate_dec(rate) -> Decimal:
    return to_dec(rate if rate is not None else 0)


def tax_of(amount_cents: int, rate) -> int:
    """`round_half_up(金額, 稅率)`（元）；`amount_cents` 為整數分。與 `helpers.legal_params.round_half_up` 同一個捨入。"""
    return int((Decimal(amount_cents) / 100 * _rate_dec(rate)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ── 一張派發單的逐行分解 ──────────────────────────────────────────────────────

def line_taxes(amount_cents, total_cents: int, rate) -> list:
    """累計進位法：第 i 行稅額（元）= R(前 i 行累計) − R(前 i−1 行累計)，R(x)＝round_half_up(x, rate)。
    最後一行的累計用 `total_cents`（派發單實際總額），所以各行稅額加總**恆等於** `round_half_up(total, rate)`。空清單回 []。"""
    out, prev, cum, n = [], 0, 0, len(amount_cents)
    for i, a in enumerate(amount_cents):
        cum += a
        cur = tax_of(total_cents if i == n - 1 else cum, rate)
        out.append(cur - prev)
        prev = cur
    return out


def split_tax(line_tax: int, line_cents: int, part_cents) -> tuple:
    """拆分份稅額（§3.4）：累計比例進位，全程整數。回 `(各份稅額 list, 餘額稅額)`；Σ各份稅額＋餘額稅額＝line_tax 恰好成立。
    前提：`line_cents > 0`、各份 > 0、Σ份 ≤ line_cents（呼叫端先驗）。RH(n/d)＝(2n＋d)//(2d)（n≥0、d>0）。"""
    if line_cents <= 0:
        return [0] * len(part_cents), line_tax
    out, prev, cum = [], 0, 0
    for a in part_cents:
        cum += a
        cur = (2 * line_tax * cum + line_cents) // (2 * line_cents)
        out.append(cur - prev)
        prev = cur
    return out, line_tax - prev


def lines_of(items, total, rate) -> dict:
    """派發單 `items_json` ⇒ 逐行分解。回
    `{"ok": bool, "reason": str, "totalCents": int, "taxTotal": int,
      "lines": [{"key", "description", "qty", "unit", "unitPrice", "cents", "tax", "mappable", "reason"}]}`。
    `ok`（可逐行對應）＝有 taxRate、行數 > 0、Σ行金額（分）＝總額（分）；缺 id 或行鍵重複的行 `mappable=False`（其餘行仍可）。
    稅額一律照整張算（行稅額加總＝R(total)），與哪幾行被對應無關。"""
    items = [it for it in (items if isinstance(items, list) else []) if isinstance(it, dict)]
    total_c = cents(total)
    amts = [cents(it.get("amount")) for it in items]
    reason = ""
    if rate is None:
        reason = "派發單沒有稅率資料"
    elif not items:
        reason = "派發單沒有品項行"
    elif sum(amts) != total_c:
        reason = "各行金額加總與派發單總額不符，只能整張對應"
    taxes = line_taxes(amts, total_c, rate) if not reason else [0] * len(items)
    keys = [line_key(it.get("id")) for it in items]
    dup = {k for k in keys if k and keys.count(k) > 1}
    out = []
    for it, k, a, t in zip(items, keys, amts, taxes):
        why = reason or ("缺行 id，不可逐行對應" if not k else ("行 id 重複" if k in dup else ""))
        out.append({"key": k, "description": str(it.get("description") or ""), "qty": it.get("qty"), "unit": str(it.get("unit") or ""), "unitPrice": it.get("unitPrice"),
                    "cents": a, "tax": t, "mappable": not why, "reason": why})
    return {"ok": not reason, "reason": reason, "totalCents": total_c, "taxTotal": tax_of(total_c, rate) if not reason else 0, "lines": out}


# ── 一張派發單的行層級分配（compute 用）──────────────────────────────────────

def view_lines(ld: dict, taxed: bool) -> list:
    """`lines_of` 的結果 ⇒ 給 API 的行列表（金額為元）：`pretax`＝未稅、`tax`＝分攤稅額（整數元）、`amount`＝計入成本（taxed＝未稅＋稅額；pretax 口徑＝未稅）。"""
    return [{"lineKey": l["key"], "description": l["description"], "qty": l["qty"], "unit": l["unit"], "unitPrice": l["unitPrice"],
             "pretax": amount_out(l["cents"]), "tax": l["tax"], "amount": amount_out(l["cents"] + (l["tax"] * 100 if taxed else 0)),
             "mappable": l["mappable"], "reason": l["reason"]} for l in ld["lines"]]


def allocate(d: dict, specs: dict, taxed: bool):
    """把行層級對應分配到各品項。`d`＝`dispatch_rows(with_lines=True)` 的一列；`specs`＝`{行鍵: {"line": 品項id|None, "parts": [(份次, 品項id, 整數分)]}}`
    （品項已確認存在）。回 `None`（呼叫端退回整張未對應；理論上不會發生）或
    `{"assigned": [(品項id, 份 dict)], "remainder": 元, "remainderTax": 元, "lines": [行狀態], "warnings": [(code, ref, 訊息)]}`。
    整行與拆分並存（驗證會擋）⇒ 整行生效並警告；拆分 Σ份 > 行未稅 ⇒ 整行拆分忽略並警告 `dispatch_line_split_exceeds`；行不存在／不可對應 ⇒ `dispatch_line_removed`。
    餘額＝派發單計入成本金額（分）− 已分配（分）：整數相減，所以「已對應份＋未對應＝該張」恆成立。"""
    did = str(d["itemId"])
    by = {l["lineKey"]: l for l in d.get("lines") or []}
    warns, assigned, state = [], [], {}
    paid_c = paid_tax_c = 0

    def piece(key, ln, part, pre_c, tax, item_id, kind):
        nonlocal paid_c, paid_tax_c
        amt_c = pre_c + (tax * 100 if taxed else 0)
        paid_c += amt_c
        paid_tax_c += tax * 100
        assigned.append((item_id, {"part": kind, "lineKey": key, "partNo": part, "lineDescription": ln["description"], "pretaxAmount": amount_out(pre_c),
                                   "tax": tax, "amount": amount_out(amt_c), "report": amount_out(pre_c), "grandTotal": amount_out(pre_c + tax * 100)}))
        return {"partNo": part, "itemId": item_id, "pretax": amount_out(pre_c), "tax": tax, "amount": amount_out(amt_c)}

    for key, sp in specs.items():
        ref0 = format_ref(did, key)
        ln = by.get(key)
        if ln is None or not ln["mappable"]:
            warns.append(("dispatch_line_removed", ref0, "派發單的這一行已不存在或不可對應，對應暫時失效，金額列入未對應"))
            continue
        A, tL = cents(ln["pretax"]), int(ln["tax"])
        if sp.get("line"):
            if sp.get("parts"):
                warns.append(("dispatch_line_conflict", ref0, "同一行同時有整行與拆分對應，以整行為準"))
            p = piece(key, ln, None, A, tL, sp["line"], "line")
            state[key] = {"state": "line", "itemId": sp["line"], "parts": [p], "remainder": 0}
            continue
        parts = sorted(sp.get("parts") or [])
        if not parts:
            continue
        if sum(c for _, _, c in parts) > A:
            warns.append(("dispatch_line_split_exceeds", ref0, "拆分金額加總超過目前的行金額（派發單被改過？），這一行的拆分暫時忽略，金額列入未對應"))
            continue
        taxes, rem_tax = split_tax(tL, A, [c for _, _, c in parts])
        ps = [piece(key, ln, no, c, t, iid, "split") for (no, iid, c), t in zip(parts, taxes)]
        state[key] = {"state": "split", "parts": ps, "remainder": amount_out(A - sum(c for _, _, c in parts) + ((rem_tax * 100) if taxed else 0)), "remainderPretax": amount_out(A - sum(c for _, _, c in parts)), "remainderTax": rem_tax}
    rem_c = cents(d["amount"]) - paid_c
    if rem_c < 0:
        return None
    lines = []
    for l in d.get("lines") or []:
        row = dict(l)
        row.update(state[l["lineKey"]] if l["lineKey"] in state else {"state": "unassigned"})
        lines.append(row)
    return {"assigned": assigned, "remainder": amount_out(rem_c), "remainderTax": amount_out(cents(d.get("tax")) - paid_tax_c), "lines": lines, "warnings": warns}
