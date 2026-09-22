# -*- coding: utf-8 -*-
"""傳票 ⑥ · 摘要範本的**佔位符封閉清單**，而且要在**儲存範本時**就驗。

規格：`docs/windows/SPEC-VOUCHER.md §四`（施工圖，`5df2f48`）
```
摘要 = f(範本, 來源)，**產生當下凍結**：存文字本身 ＋ template_id ＋ template_version
⚙️ 佔位符必須在封閉清單內，**儲存範本時**就驗證，不在就拒絕儲存並指出是哪一個
   （不可等到產生摘要時才發現 => 壞範本會每次印空白，看起來像使用者沒填）
```

---

# 🔴 **「什麼時候驗」比「驗不驗」更重要**

```
儲存時驗  使用者當場看到「沒有『發票類別』這個佔位符」          => 他改掉
產生時驗  範本存下去了 => 之後每一張用它的傳票摘要**印空白**
          => 而那看起來像**使用者自己沒填**
```
☠️ 後者不會有人報修成「範本壞了」，它會被報修成「摘要有時候是空的」——
   而那個症狀查起來會指向完全不同的地方。
🔑 〈防護的副作用落在盲側〉：**擋得晚 = 錯誤被搬到一個看不出成因的位置。**

# ⚠️ 而佔位符的**語法**規格沒有定版

```
規格給的  13 個**名稱**（發票號／發票日期／…／專案名稱）
沒給的    包在什麼符號裡（{x}？{{x}}？[x]？）
```
=> 本檔**不釘語法**：驗證那幾題用「同一個壞名稱包在四種符號裡」，
   **不管真正的語法是哪一種，都會有一個被解析成佔位符**。
⚙️ 而「好的要過」那一格改用 `extract_placeholders()`：
   它必須從某一種寫法裡把 13 個**都認出來** —— 那才分辨得出
   「接受是因為它是合法的」與「接受是因為它根本沒看到佔位符」。
"""
import importlib

import pytest

#: 施工圖 `§四` 的封閉清單，**逐字、逐個**。起始版 13 個。
PLACEHOLDERS = (
    "發票號", "發票日期", "單號", "客戶名稱", "廠商名稱",
    "未稅", "稅額", "含稅", "本行金額",
    "單據日期", "上傳檔案日期",
    "案件編號", "專案名稱",
)

#: ⚠️ 我沒有釘語法 => 壞名稱同時用這四種包法寫進同一個 body。
_WRAPS = ("{%s}", "{{%s}}", "[%s]", "$%s")

_SEAM_MODULES = (
    "helpers.voucher_template",
    "helpers.voucher_templates",
    "helpers.voucher",
    "routers.voucher_templates",
)

_BAD = "發票類別"          # 聽起來很合理，而它**不在**封閉清單裡


def _module():
    for name in _SEAM_MODULES:
        try:
            mod = importlib.import_module(name)
        except Exception:                                  # noqa: BLE001
            continue
        if any(hasattr(mod, a) for a in
               ("SUMMARY_PLACEHOLDERS", "PLACEHOLDERS",
                "TEMPLATE_PLACEHOLDERS", "extract_placeholders",
                "validate_template_body")):
            return name, mod
    pytest.fail(
        "找不到摘要範本模組（找過：%s）。\n" % list(_SEAM_MODULES)
        + "⚠️ 這是**弱紅**：本檔多題會紅在同一句話上。\n"
          "   名字可以換（**退回給我**），而那個接縫必須存在。")


def _attr(mod, *names):
    for n in names:
        v = getattr(mod, n, None)
        if v is not None:
            return n, v
    return None, None


# ══════════════════════════════════════════════════════════════════════
# 清單本身
# ══════════════════════════════════════════════════════════════════════

def test_the_placeholder_list_is_exactly_the_thirteen_from_the_spec():
    """🔴 **封閉清單剛好是施工圖 `§四` 的那 13 個。**

    ⚠️ 釘**集合相等**不是「包含」：
    ```
    少一個  => 使用者存不了一個規格說可以的範本
    多一個  => 有人加了一個佔位符，**而沒有人決定它從哪裡取值**
             ☠️ 而它存得下去，之後每一張都印空白
    ```
    📌 `§54c` 的形狀：**清單要能被數。**
    ⚠️ 規格寫「起始版，**只增不刪**；刪前要查有沒有範本在用」——
       所以「多一個」不是錯，而**它要先改規格**（〈不自己發編號〉）。
       這一題紅的時候請先看是不是規格動了。
    """
    where, mod = _module()
    name, got = _attr(mod, "SUMMARY_PLACEHOLDERS", "PLACEHOLDERS",
                      "TEMPLATE_PLACEHOLDERS")
    assert got is not None, (
        "`%s` 沒有封閉清單（找過 `SUMMARY_PLACEHOLDERS` / `PLACEHOLDERS` …）——\n"
        % where
        + "🔑 它要有一個**可以被數**的地方；散在 `if/elif` 或 f-string 裡數不出來。")
    assert set(got) == set(PLACEHOLDERS), (
        "封閉清單是 %s\n施工圖 `§四` 是 %s\n"
        % (sorted(set(got)), sorted(PLACEHOLDERS))
        + "缺 %s ／ 多 %s\n"
        % (sorted(set(PLACEHOLDERS) - set(got)), sorted(set(got) - set(PLACEHOLDERS)))
        + "⚠️ 多出來的那個**存得下去**，而之後每一張用它的傳票都印空白。")


def test_extract_recognises_every_one_of_the_thirteen():
    """🔴 **13 個佔位符，解析器要一個不漏地認出來。**

    ⚙️ 而這一題是下面「好的要過」那一格的**前提**：
    ```
    少了它  => 「合法範本要接受」可以靠「**根本沒解析**」變綠
    ```
    ☠️ 那就是〈假綠燈：清單為空的斷言〉—— 一個什麼都認不出來的解析器
       會讓每一個範本都合法。
    ⚠️ 語法沒定版 => 四種包法各試一次，**有一種能認出全部 13 個**就算通過。
    """
    where, mod = _module()
    _n, extract = _attr(mod, "extract_placeholders", "_extract_placeholders",
                        "parse_placeholders")
    assert extract is not None, (
        "`%s` 沒有 `extract_placeholders()` ——\n" % where
        + "⚠️ 名字可以換（**退回給我**）。而沒有這支的話，"
          "「合法範本要接受」那一題可以靠**根本沒解析**變綠。")

    tried = {}
    for wrap in _WRAPS:
        body = "，".join(wrap % p for p in PLACEHOLDERS)
        try:
            got = set(extract(body))
        except Exception as e:                             # noqa: BLE001
            tried[wrap] = "例外 %s" % type(e).__name__
            continue
        if got == set(PLACEHOLDERS):
            return
        tried[wrap] = "認出 %d 個，缺 %s" % (
            len(got), sorted(set(PLACEHOLDERS) - got)[:4])
    pytest.fail(
        "四種寫法都沒有把 13 個全部認出來：\n  "
        + "\n  ".join("%-8s %s" % (w, r) for w, r in tried.items())
        + "\n⚠️ 若真正的語法是第五種，**退回給我**，我把它加進去。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 儲存時驗，而且要說出是哪一個
# ══════════════════════════════════════════════════════════════════════

def _validate(mod, where):
    n, fn = _attr(mod, "validate_template_body", "validate_placeholders",
                  "_validate_template_body")
    assert fn is not None, (
        "`%s` 沒有 `validate_template_body()` ——\n" % where
        + "⚠️ 名字可以換（**退回給我**），而它必須是**儲存範本那條路上**"
          "叫得到的一支，不是產生摘要時才叫的。")
    return fn


def _result(out):
    """驗證的回傳形狀沒定版 => `(ok, bad)` 或 `bad 清單` 或丟例外，都收。"""
    if isinstance(out, tuple) and len(out) == 2:
        return bool(out[0]), out[1]
    if isinstance(out, (list, tuple, set)):
        return not out, list(out)
    if out is None or out is True:
        return True, []
    if out is False:
        return False, []
    return True, out


def test_saving_a_template_with_an_unknown_placeholder_is_refused():
    """🔴🔴 **不在清單裡的佔位符 => 拒絕儲存。**

    ```
    範本   「{發票類別} 客戶 {客戶名稱}」
    ```
    ⚠️ `發票類別` 聽起來**非常合理** —— 它就是會被打出來的那一種。
    ☠️ 而放行的後果不是報錯：
    ```
    範本存下去 => 之後每一張用它的傳票，摘要那一段**印空白**
    => 使用者看到的是「摘要有時候是空的」
    => 而那個症狀查起來會指向完全不同的地方
    ```
    🔑 〈防護的副作用落在盲側〉：**擋得晚 = 錯誤被搬到一個看不出成因的位置。**
    """
    where, mod = _module()
    fn = _validate(mod, where)
    body = "，".join(wrap % _BAD for wrap in _WRAPS) + "  客戶 {客戶名稱}"
    try:
        ok, bad = _result(fn(body))
    except Exception as e:                                 # noqa: BLE001
        ok, bad = False, [str(e)]
    assert not ok, (
        "含 `%s` 的範本**存得下去** ——\n" % _BAD
        + "☠️ 之後每一張用它的傳票摘要都印空白，"
          "而使用者會以為是自己沒填。")


def test_the_refusal_names_which_placeholder_is_wrong():
    """🔴 **拒絕的時候要指出是哪一個佔位符。**

    ☠️ 只說「範本含有無效的佔位符」的話，使用者要自己把 13 個名稱
       跟他打的每一個逐字對一次 —— 🔑 **而那個字串是檢查它的人手上就有的。**
    📌 與 ② 的「不平衡要說出差額」同一族：
       **一個不說是哪一個的錯誤訊息，等於要使用者重做一次檢查。**
    """
    where, mod = _module()
    fn = _validate(mod, where)
    body = "，".join(wrap % _BAD for wrap in _WRAPS) + "  客戶 {客戶名稱}"
    try:
        ok, bad = _result(fn(body))
    except Exception as e:                                 # noqa: BLE001
        ok, bad = False, [str(e)]
    text = bad if isinstance(bad, str) else "／".join(str(x) for x in bad)
    assert _BAD in text, (
        "擋下來了，而訊息／回傳裡沒有 `%s`：%r\n" % (_BAD, text)
        + "🔑 使用者要自己把 13 個名稱逐字對一次 —— "
          "**而那個字串是檢查它的人手上就有的。**")


def test_a_template_with_only_valid_placeholders_is_accepted():
    """⚙️ **正對照：13 個都合法的範本必須存得下去。**

    ☠️ 少了它，一支「一律拒絕」也會讓上面兩題綠 ——
       而症狀是**使用者一個範本都存不了**。
    🔑 〈降級之後它還是會動〉的鏡像：擋過頭會讓功能不能用，
       **而它看起來像「我們很嚴格」。**
    ⚙️ 而它要配上一題（解析器認得出 13 個），否則
       「根本沒解析」也會讓這一題綠。
    """
    where, mod = _module()
    fn = _validate(mod, where)
    tried = {}
    for wrap in _WRAPS:
        body = "，".join(wrap % p for p in PLACEHOLDERS)
        try:
            ok, bad = _result(fn(body))
        except Exception as e:                             # noqa: BLE001
            ok, bad = False, [str(e)]
        if ok:
            return
        tried[wrap] = bad
    detail = "\n  ".join("%-8s %r" % (w, b) for w, b in tried.items())
    pytest.fail(
        "四種寫法的合法範本**全部**被拒絕：\n  " + detail + "\n"
        + "☠️ 擋過頭 => **使用者一個範本都存不了**。\n"
        + "⚠️ 這裡只要求「**有一種**寫法會過」不是四種都過 ——\n"
          "   真正的語法只有一種，另外三種在它眼裡是字面文字或壞名稱，\n"
          "   要求它們也過會讓這一題**紅在一段寫對的碼上**。\n"
          "🔑 鑑別力由 `test_extract_recognises_every_one_of_the_thirteen` 提供，\n"
          "   **兩題要一起看**：少了那一題，「根本沒解析」也會讓這一題綠。")
