"""標案雷達（L2）自己的測試夾具。

2026-09-25（AUDIT-X-9c A-2）自 backend/conftest.py 搬來：L1 的測試設定每一題都跑，
在那裡 import 本模組 ⇒ 真的 `modules.tender_radar` 永遠已經在 sys.modules 裡，
「停用後不 import」就只能用合成模組驗；而拿掉本模組（core-only 產品）時那一段變成死碼。
範圍因此縮到本模組的測試——`_fetch_details` 只經 `run_scan()` 呼叫，只有這裡的題會跑到。
守門：tests/platform/test_module_selection.py::test_conftest_names_no_l2_module。
"""
import pytest


@pytest.fixture(autouse=True)
def _no_politeness_delay(monkeypatch):
    """**把「對別人伺服器的禮貌延遲」在測試裡設成 0。**

    ## 🔴 它關掉了什麼

    ```
    modules/tender_radar/source.py:149  DETAIL_INTERVAL_SECONDS = 2
                           :596   if i: time.sleep(DETAIL_INTERVAL_SECONDS)
    ```
    ⇒ 在測試裡設成 **0**。**只有這一個常數**，沒有碰別的
    （`geo.GEOCODE_INTERVAL_SECONDS` 與重設端點的每日節流**都不在射程內**）。

    ## 🔴 要驗節流的測試，**必須自己把它設回去**

    ```python
    monkeypatch.setattr(ts, "DETAIL_INTERVAL_SECONDS", 2)   # 要正數才驗得到
    ```
    📌 現在這樣做的是 `test_tender_detail_2026_09_21.py::test_d3_…`，
    而它是**唯一**守「對別人伺服器的禮貌」那個承諾的題。
    ⚠️ **看到這裡是 0 不要以為那個延遲不存在** —— 它在產品裡是 2 秒。

    ## 📌 為什麼預設是 0（方向反過來）

    ```
    預設 2 秒  ⇒ 每一個新寫的題都要記得 patch ⇒ **第七題一定會再發生**
    預設 0     ⇒ 新題自動快；**唯一需要正數的那一題自己宣告**
    ⇒ 要慢的人舉手，不是要快的人舉手
    ```
    🔑 實測（2026-09-22）：六題各 24~33 秒，`cProfile` 顯示
    **16 次 `time.sleep` × 2.000 秒 ＝ 32.005 秒，而其餘加起來不到 3 秒。**
    ☠️ 而同一個檔裡**早就有一題**寫了這個 patch（`:667`）——
    **修法一直存在，只是沒有被套到其他題上。**

    ## ⚙️ 這支 fixture 自己的兩側對照

    ```
    生效這一側   test_tender_platform_controls_2026_09_25.py::test_the_politeness_delay_is_zero_in_tests
    設回去那一側 test_d3_interval_between_detail_fetches（它把常數設回正數）
    ```
    ☠️ **只有前者的話，這支 fixture 以後壞掉不會有人發現。**
    """
    try:
        from modules.tender_radar import source as tender_source
    except Exception:       # noqa: BLE001 —— 匯入不了就不是這支 fixture 的事
        return
    monkeypatch.setattr(tender_source, "DETAIL_INTERVAL_SECONDS", 0,
                        raising=False)
