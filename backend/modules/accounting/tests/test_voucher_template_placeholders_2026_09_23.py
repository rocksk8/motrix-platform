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

# ✅ 語法：**`{名稱}`（單層大括號）** —— B 2026-09-23 明著選的

```
規格給的  13 個**名稱**（發票號／發票日期／…／專案名稱）
規格沒給  包在什麼符號裡
B 選的    `{名稱}`，例：收到{客戶名稱}貨款{含稅}元
```
⚠️ 我原本寫成「四種包法各試一次、**有一種過就算過**」——
   而 B 要求我釘準那一種：🔑 **寬的判準永遠比較好過**，
   它給你綠燈所以你不會回來看它（〈判準的寬窄都會騙人〉）。
📌 ⇒ 語法一旦定版，寬判準就沒有存在理由了。**它改語法要退回給我。**
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

#: ✅ B 2026-09-23 定版的語法：單層大括號。**改語法要退回給我。**
WRAP = "{%s}"

_SEAM_MODULES = (
    "modules.accounting.voucher_template",
    "helpers.voucher_templates",
    "modules.accounting.voucher",
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

    🔴 **釘的是「只增不刪」的不刪那半，不是集合相等。** A 2026-09-23 裁：
    ```
    「湊出來的一格」與「漏掉的一格」是兩種缺陷，**判準不同**
      湊的 => 問「它擋得住什麼失敗」
      漏的 => 問「**這份清單的來源是什麼**」
    ```
    ⚠️ 而這 13 個**沒有來源**（A-2 自己列的，不是抄任何法規）
       => 風險方向是**太短**（使用者想用的欄位不在裡面），不是「有湊的」
       => 釘集合相等會**擋住一個正當的新增**，那就是〈擋太早會讓功能不能用〉。
    ☠️ 而「少一個」是真的壞：**已經有範本在用它** => 那些範本全部失效。
    📌 ⇒ 這一題只擋「不刪」；「多一個而沒有人決定它從哪取值」由下一題擋。
    """
    where, mod = _module()
    name, got = _attr(mod, "SUMMARY_PLACEHOLDERS", "PLACEHOLDERS",
                      "TEMPLATE_PLACEHOLDERS")
    assert got is not None, (
        "`%s` 沒有封閉清單（找過 `SUMMARY_PLACEHOLDERS` / `PLACEHOLDERS` …）——\n"
        % where
        + "🔑 它要有一個**可以被數**的地方；散在 `if/elif` 或 f-string 裡數不出來。")
    missing = [ph for ph in PLACEHOLDERS if ph not in set(got)]
    assert not missing, (
        "封閉清單少了 %s\n現有 %s\n" % (missing, sorted(set(got)))
        + "☠️ 刪掉一個佔位符 => **已經在用它的範本全部失效**，"
          "而症狀是那一段印空白。\n"
        + "⚠️ 規格逐字：「起始版，**只增不刪**；刪前要查有沒有範本在用」。\n"
        + "📌 而新增**不會**讓這一題紅 —— 這份清單沒有權威來源，"
          "它的風險方向是太短。")


def test_every_placeholder_has_somewhere_to_get_its_value_from():
    """🔴 **清單裡每一個佔位符，都要有人決定它從哪裡取值。**

    ☠️ 這一題擋的是「多一個」那一側，而它的症狀最安靜：
    ```
    有人加了 {合約編號} 進清單  => 範本存得下去 ✅
    而沒有人寫它從哪取值        => 之後每一張傳票那一段**印空白**
    => 使用者看到的是「摘要有時候少一塊」，他會以為是自己沒填
    ```
    🔑 〈守門要驗「有沒有人做過決定」〉：不是驗「取值取得對不對」，
       是驗**有沒有人替它做過那個決定**。
    ⚙️ 而它與上一題互補：
    ```
    上一題  擋「少一個」（刪掉會讓既有範本失效）
    這一題  擋「多一個」（加了而沒人接它）
    => 兩題合起來才是「只增不刪，而增的那個要能用」
    ```
    """
    where, mod = _module()
    _n, resolvers = _attr(mod, "PLACEHOLDER_RESOLVERS", "PLACEHOLDER_SOURCES",
                          "_PLACEHOLDER_RESOLVERS")
    _n2, listed = _attr(mod, "SUMMARY_PLACEHOLDERS", "PLACEHOLDERS",
                        "TEMPLATE_PLACEHOLDERS")
    assert resolvers is not None, (
        "`%s` 沒有「每個佔位符從哪取值」的對應表"
        "（找過 `PLACEHOLDER_RESOLVERS` / `PLACEHOLDER_SOURCES`）——\n" % where
        + "⚠️ 名字可以換（**退回給我**），而它必須**可以被數** ——\n"
          "   散在 `if/elif` 裡的話，加一個佔位符而忘了接它**不會有任何訊號**。")
    orphan = [ph for ph in (listed or ()) if ph not in set(resolvers)]
    assert not orphan, (
        "清單裡有 %s 沒有取值來源。\n" % orphan
        + "☠️ 範本存得下去，而那一段**每一張都印空白** ——\n"
          "   使用者看到的是「摘要有時候少一塊」，他會以為是自己沒填。")
    stale = [k for k in resolvers if k not in set(listed or ())]
    assert not stale, (
        "取值表裡有 %s **不在封閉清單裡**。\n" % stale
        + "⚙️ 這是反向控制：少了它，「把每一個想得到的名字都放進取值表」"
          "可以讓上面那個斷言永遠綠。")


def test_extract_recognises_every_one_of_the_thirteen():
    """🔴 **13 個佔位符，解析器要一個不漏地認出來。**

    ⚙️ 而這一題是下面「好的要過」那一格的**前提**：
    ```
    少了它  => 「合法範本要接受」可以靠「**根本沒解析**」變綠
    ```
    ☠️ 那就是〈假綠燈：清單為空的斷言〉—— 一個什麼都認不出來的解析器
       會讓每一個範本都合法。
    ✅ 語法已定版（`{名稱}`）=> 這一題釘**剛好認出那 13 個**，
       不多不少 —— 多認出一個表示它把不該當佔位符的東西當成佔位符了。
    """
    where, mod = _module()
    _n, extract = _attr(mod, "extract_placeholders", "_extract_placeholders",
                        "parse_placeholders")
    assert extract is not None, (
        "`%s` 沒有 `extract_placeholders()` ——\n" % where
        + "⚠️ 名字可以換（**退回給我**）。而沒有這支的話，"
          "「合法範本要接受」那一題可以靠**根本沒解析**變綠。")

    body = "，".join(WRAP % ph for ph in PLACEHOLDERS)
    got = set(extract(body))
    assert got == set(PLACEHOLDERS), (
        "`%s` 從 13 個佔位符的範本裡認出 %s\n" % (where, sorted(got))
        + "缺 %s ／ 多 %s\n"
        % (sorted(set(PLACEHOLDERS) - got), sorted(got - set(PLACEHOLDERS)))
        + "☠️ 少認出一個 => 那個佔位符會被當成**字面文字**印出來"
          "（版面上出現「{客戶名稱}」連大括號一起印）。")

    plain = "收到貨款，沒有任何佔位符"
    assert not set(extract(plain)), (
        "`%s` 從一段**沒有佔位符**的文字裡認出了 %r ——\n"
        % (where, extract(plain))
        + "⚙️ 這是正對照：一個「什麼都認成佔位符」的解析器會讓下面那題"
          "**一律拒絕**，而症狀是使用者一個範本都存不了。")


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
    body = "客戶 %s 的 %s" % (WRAP % "客戶名稱", WRAP % _BAD)
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
    body = "客戶 %s 的 %s" % (WRAP % "客戶名稱", WRAP % _BAD)
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
    body = "，".join(WRAP % ph for ph in PLACEHOLDERS)
    try:
        ok, bad = _result(fn(body))
    except Exception as e:                                 # noqa: BLE001
        ok, bad = False, [str(e)]
    assert ok, (
        "13 個全部合法的範本被拒絕了：%r\n" % (bad,)
        + "☠️ 擋過頭 => **使用者一個範本都存不了**。\n"
        + "🔑 而鑑別力由 `test_extract_recognises_every_one_of_the_thirteen` 提供："
          "少了那一題，「根本沒解析」也會讓這一題綠。")
