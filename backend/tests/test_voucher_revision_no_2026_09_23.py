# -*- coding: utf-8 -*-
"""傳票退回重送的**單號升版**。

# ☠️ 不可以呼叫 `quotations.py` 那一支 —— 它**寫死了 `MQ-` 前綴**

```python
quotations.py:164
    m = _re.match(r'^(MQ-\\d{6}-\\d{3})(?:-R(\\d+))?$', quote_no)
    if not m:
        return quote_no + '-R1'        # ☠️ 對不上就無腦加 -R1
```

**我實跑過，不是讀碼推的**：
```
MQ-202501-001    -> MQ-202501-001-R1    -> MQ-202501-001-R2   -> MQ-202501-001-R3   ✅
20260330-006     -> 20260330-006-R1     -> 20260330-006-R1-R1 -> 20260330-006-R1-R1-R1
V-20260330-006   -> V-20260330-006-R1   -> V-20260330-006-R1-R1 -> …
```
🔑 **它無限累積**，而不是只錯一次。
☠️ 而 `UNIQUE INDEX` **擋不住**：`-R1-R1` 與 `-R1` 是不同字串 ⇒
   **不報錯，只是產生一個錯的單號。**
📌 那與〈降級之後它還是會動〉同族：**沒有人會報修一個「成功了」的動作。**

---

# ⚠️ 釘的是**不變量**，不是實作

```
連續退回 n 次 ⇒ 尾碼必須是 -Rn，而 n 單調遞增
```
⚙️ **而 `MQ-` 格式要一起丟進同一支測** ——
   證明它**不是**靠「字串長度／有沒有 `-R`／前綴長什麼樣」判的。
🔑 〈守門守的對象被搬走〉：只釘 `-R2` 這個字面值的話，
   **日後包一層間接就照樣全綠**。
"""
import importlib
import re

import pytest

#: 我釘的接縫。名字要改**退回給我**，不要自己改題。
_SEAMS = (
    ("helpers.voucher_no", "next_revision_no"),
    ("modules.accounting.voucher", "next_revision_no"),
    ("modules.accounting.api.vouchers", "_next_revision_no"),
)

#: 三種起始單號 —— **格式刻意不同**，而它們必須得到同樣的升版行為。
#: `MQ-…` 是對照組：它在既有實作下是對的，所以它**分辨不出**實作換沒換。
START_NOS = (
    "V-20260330-006",      # 傳票預期的形狀
    "20260330-006",        # 沒有前綴
    "MQ-202501-001",       # ⚙️ 對照組（既有實作對它是對的）
)


def _next_revision_no():
    """找到那支函式。找不到 ⇒ 紅，而訊息要說得出**為什麼不能借用既有那支**。"""
    for mod_name, fn_name in _SEAMS:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:                                  # noqa: BLE001
            continue
        fn = getattr(mod, fn_name, None)
        if callable(fn):
            return "%s.%s" % (mod_name, fn_name), fn
    pytest.fail(
        "找不到傳票的單號升版函式（找過：%s）。\n"
        % ", ".join("%s.%s" % s for s in _SEAMS)
        + "🔴 **不可以借用 `quotations.py::_next_revision_no()`** —— 它把\n"
          "   `^(MQ-\\d{6}-\\d{3})(?:-R(\\d+))?$` **寫死**，對不上就無腦 `+ '-R1'`\n"
          "   ⇒ 傳票單號退第二次會變 `-R1-R1`，而 `UNIQUE INDEX` 擋不住。\n"
        "⚠️ 名字可以換（**退回給我**），而那個接縫必須存在。")


def test_consecutive_revisions_are_numbered_r1_r2_r3(
        ):
    """🔴🔴 **連續退回 n 次 ⇒ 尾碼是 `-Rn`，而 n 單調遞增。**

    ☠️ 現況（若借用 `quotations` 那一支）：
    ```
    20260330-006 -> -R1 -> **-R1-R1** -> **-R1-R1-R1**
    ```
    🔑 **它不報錯**，`UNIQUE INDEX` 也擋不住（`-R1-R1` 與 `-R1` 是不同字串）
    ⇒ 資料庫裡會長出一個**看起來像版本號、而不是版本號**的東西。

    ⚙️ 三種格式一起測，其中 `MQ-…` 是**對照組**：
    ```
    它在既有實作下就是對的 ⇒ 只測它，換不換實作都全綠
    ⇒ 而另外兩種會紅 ⇒ **兩者並排才證明「判準不是綁在格式上」**
    ```
    📌 〈守門守的對象被搬走〉：只釘 `-R2` 這個字面值，日後包一層就照樣全綠。
    """
    where, fn = _next_revision_no()

    for start in START_NOS:
        current = start
        seen = []
        for n in (1, 2, 3):
            current = fn(current)
            seen.append(current)
            expect_suffix = "-R%d" % n
            assert current.endswith(expect_suffix), (
                "`%s`：`%s` 連續升版 %d 次得到 %s\n"
                % (where, start, n, " → ".join(seen))
                + "⇒ 第 %d 次應該以 `%s` 結尾，實際是 %r。\n"
                  % (n, expect_suffix, current)
                + "☠️ `%s` 這種形狀會變成 `-R1-R1-R1` —— "
                  "**而 `UNIQUE INDEX` 擋不住，它不報錯。**" % start)
            assert current.count("-R") == 1, (
                "`%s` 出現了 %d 個 `-R` 片段：%r\n"
                % (start, current.count("-R"), current)
                + "🔑 那正是 `quotations.py` 那一支的症狀："
                  "對不上它寫死的 `MQ-` 格式時**無腦追加**。")

        base = seen[-1][: -len("-R3")]
        assert base == start, (
            "升版三次之後的基底是 %r，而起點是 %r ——\n" % (base, start)
            + "☠️ 基底被改掉了 ⇒ 那張單的歷史版本**對不回同一張單**。")


def test_the_revision_numbering_is_not_borrowed_from_quotations():
    """🔴 **那支函式不可以就是 `quotations.py` 的那一支。**

    ⚠️ 上一題有一種**過得去而錯的**實作方式：直接 `from routers.quotations import
    _next_revision_no` —— 而它對 `MQ-…` 是對的、對另外兩種是錯的 ⇒
    上一題會紅，**而紅的原因看起來像「還沒實作」**。
    🔑 這一題把那個可能性單獨講出來，**讓訊息指得準**。

    📌 而理由不是「不要重用程式碼」，是〈模組化：L2 功能模組彼此不可依賴〉：
       傳票依賴報價單的內部函式 ⇒ **改報價單的單號格式會靜默改掉傳票的。**
    """
    where, fn = _next_revision_no()
    try:
        import routers.quotations as q
    except Exception:                                      # noqa: BLE001
        pytest.skip("`routers.quotations` 載不進來，這一題的比較對象不存在。")

    borrowed = getattr(q, "_next_revision_no", None)
    assert borrowed is not None, (
        "`quotations._next_revision_no` 不見了 —— **儀器失效**，"
        "這一題比不出東西。")
    assert fn is not borrowed, (
        "`%s` **就是** `quotations._next_revision_no` 本人 ——\n" % where
        + "☠️ 它把 `MQ-` 前綴寫死，傳票單號退第二次會變 `-R1-R1`。\n"
        "🔑 而更根本的問題是相依方向：傳票依賴報價單的內部函式 ⇒ "
        "**改報價單的單號格式會靜默改掉傳票的。**")


def test_the_quotation_helper_really_does_have_this_defect():
    """⚙️ **正對照：證明我描述的那個缺陷是真的。**

    ☠️ 少了它，上面兩題的理由可能建立在一個**我讀錯的碼**上 ——
    而今天我已經有兩次從「這個機制看起來很脆」推出一個**不存在**的失敗故事。
    🔑 ⇒ 那個缺陷要**跑出來**，不是讀出來。

    ⚠️ 而這一題**不是要求修 `quotations`** —— 它對 `MQ-…` 的行為是對的，
       而報價單的單號一律是那個格式。**它在自己的地盤上沒有壞。**
    📌 〈同一段碼在新脈絡下的風險不同〉：問題是**借用它**，不是它本身。
    """
    import routers.quotations as q
    fn = getattr(q, "_next_revision_no", None)
    if fn is None:
        pytest.skip("`quotations._next_revision_no` 不存在。")

    cur = "20260330-006"
    got = [cur := fn(cur) for _ in range(3)]
    assert got[-1].count("-R") > 1, (
        "`quotations._next_revision_no` 對 `20260330-006` 連跑三次得到 %s\n" % got
        + "⇒ 它**沒有**我描述的那個缺陷 ⇒ 上面兩題的理由要重寫。\n"
          "🔑 那是好消息，而它表示**我的描述過期了**。")

    mq = "MQ-202501-001"
    mq_got = [mq := fn(mq) for _ in range(3)]
    assert mq_got[-1].endswith("-R3"), (
        "`quotations._next_revision_no` 對 `MQ-…` 也不對：%s\n" % mq_got
        + "⚙️ 這是對照組 —— 它在自己的格式上**應該是對的**，"
          "而那正是這個缺陷一直沒被發現的原因。")
