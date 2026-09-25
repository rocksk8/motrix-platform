"""NETGUARD 自己的守門，＋ 產品側的一個缺口（`fetch_detail` 沒有開關檢查）。

## 為什麼 NETGUARD 需要自測

它是一支 autouse fixture ⇒ **它失效的樣子是「全部照樣綠」**。
⚠️ 「現在沒有人連外」與「攔截器壞了」**在結果上完全一樣**。
🔑 所以要有一題**刻意連外**，證明它會出聲。
（A 的判準：「如果你做完它是綠的，那就表示它沒在攔它該攔的東西。」）
"""
import urllib.request

import pytest

import modules.tender_radar.source as ts

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


# ══════════════════════════════════════════════════════════════════════
# 產品側：`fetch_detail` 沒有開關檢查
# ══════════════════════════════════════════════════════════════════════

def test_fetch_detail_respects_the_radar_switch(monkeypatch):
    """🔴 `radar_on()` 是關的時候，直接呼叫 `fetch_detail` **不可以連外**。

    ## 現況（B 讀出來，我複核過）

        run_scan()      第一行  if not radar_on(): return     ✅ 有守
        fetch_detail()  沒有任何開關檢查                       🔴 沒有

    > **B：「今天只有 `_fetch_details` 會叫它，而它在 `run_scan` 底下 ⇒ 目前安全。
    > 但那是**呼叫端剛好都在守衛底下**，不是那個函式本身安全。」**

    🔑 那跟 `DEFAULT_SCAN_HOUR` 靠「寫入端剛好擋了範圍」活下來是同一個形狀：
    **一個不變量由呼叫端維持，而呼叫端會增加。**
    ⚠️ 而這個不變量是「這台機器不會在沒有人知道的情況下對外連線」——
    它是整條線最外層的那個承諾。

    📌 這一題**不靠 NETGUARD 的紅**（那是 fixture 收尾時的事），
    而是直接觀測「有沒有嘗試」—— 觀測點在被測對象的下游，不在測試框架裡。
    """
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", False)
    monkeypatch.delenv("MOTRIX_TENDER_RADAR", raising=False)
    assert ts.radar_on() is False, "前提不成立：雷達應該是關的"

    attempts = []

    def _record(req, *a, **kw):
        attempts.append(req if isinstance(req, str) else getattr(req, "full_url", ""))
        raise OSError("不連出去")

    monkeypatch.setattr(ts.urllib.request, "urlopen", _record)
    ts.fetch_detail("https://web.pcc.gov.tw/tps/QueryTender/query/x")

    assert not attempts, (
        f"雷達是關的，而 `fetch_detail` 還是嘗試連出去了：{attempts}\n"
        "⇒ 那個函式本身沒有守衛，它只是**剛好**都被守衛底下的人呼叫。"
        "而呼叫端會增加 —— 下一個呼叫者不會知道自己需要先檢查開關。"
    )


def test_fetch_detail_still_works_when_the_radar_is_on(monkeypatch):
    """對照組：**雷達開著時它要真的去抓**。

    ⚠️ 沒有這一題，一個 `def fetch_detail(...): return None, "disabled"` 的實作
    會讓上一題全綠 —— 而詳細頁從此再也抓不到，地點永遠是 NULL。
    🔑 「不該做的時候不做」與「該做的時候要做」是兩件事。
    """
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    attempts = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"<html>ok</html>"

        def geturl(self):
            return FAKE_URL

    def _ok(req, *a, **kw):
        attempts.append(req if isinstance(req, str) else getattr(req, "full_url", ""))
        return _Resp()

    monkeypatch.setattr(ts.urllib.request, "urlopen", _ok)
    html, _second = ts.fetch_detail("https://web.pcc.gov.tw/tps/QueryTender/query/x")
    assert attempts, "雷達開著，而 `fetch_detail` 一次都沒有嘗試連線"
    assert html is not None, "雷達開著卻沒有拿到內容"
