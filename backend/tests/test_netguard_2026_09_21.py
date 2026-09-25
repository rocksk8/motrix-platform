"""NETGUARD 自己的守門，＋ 產品側的一個缺口（`fetch_detail` 沒有開關檢查）。

## 為什麼 NETGUARD 需要自測

它是一支 autouse fixture ⇒ **它失效的樣子是「全部照樣綠」**。
⚠️ 「現在沒有人連外」與「攔截器壞了」**在結果上完全一樣**。
🔑 所以要有一題**刻意連外**，證明它會出聲。
（A 的判準：「如果你做完它是綠的，那就表示它沒在攔它該攔的東西。」）
"""
import urllib.request

import pytest

FAKE_URL = "https://example.invalid/netguard-self-test"


def test_netguard_records_an_attempt_and_blocks_it():
    """🔑 **刻意連外** → 攔截器要 ① 擋下來 ② 記錄下來。

    ⚠️ 這一題**自己不能紅** —— 它在同一支測試裡把攔截器的兩個行為都驗完，
    而不是讓 fixture 在收尾時報錯。
    ⇒ 所以它**捕捉**那個 `OSError`，並在結束前把記錄清乾淨。

    📌 為什麼要清乾淨：`_netguard` 在收尾時會斷言「沒有任何嘗試」。
    這一題刻意製造了一次嘗試 ⇒ 不清的話它會在收尾紅，
    **而紅的原因看起來像「這一題真的偷連外網」。**
    """
    blocked = False
    try:
        urllib.request.urlopen(FAKE_URL, timeout=1)
    except OSError as exc:
        blocked = "NETGUARD" in str(exc)
    assert blocked, (
        "刻意連外卻沒有被擋下來 —— NETGUARD 沒有生效。\n"
        "⚠️ 那代表整個測試套件現在可以在沒有人知道的情況下對外連線。"
    )
    # 把自己製造的那一筆清掉（見 docstring）
    closure = urllib.request.urlopen.__closure__
    for cell in closure or ():
        if isinstance(cell.cell_contents, list):
            cell.cell_contents.clear()


def test_netguard_does_not_break_a_test_that_patches_urlopen_itself(monkeypatch):
    """對照組：**自己 patch 掉 `urlopen` 的測試不可以被 NETGUARD 波及。**

    ⚠️ `test_d20c`（`fetch_detail` 的契約題）就是這樣寫的 ——
    它把 `urlopen` 換成自己的假物件。NETGUARD 先 patch、它後 patch ⇒ 蓋過去。
    🔑 沒有這一題，NETGUARD 可能讓一批**完全正當**的測試紅，
    而那種紅會讓人直接把 NETGUARD 拿掉。
    """
    calls = []
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **kw: calls.append(a) or "ok")
    assert urllib.request.urlopen(FAKE_URL) == "ok"
    assert calls, "自己的 patch 沒有生效"
