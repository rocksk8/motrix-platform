"""`tests/_ports.py::free_safe_port()` 自己的守門（視窗 A 第 5 輪 §3f P1）。

## 為什麼這支必須存在

第 5 輪的⑥抓到 21 個 e2e 檔各自用 `port=0`，會隨機抽到瀏覽器封鎖埠。
修法是把挑埠邏輯收進**一個**共用函式 —— **bug 的家從 21 個變成 1 個**。

> 🔑 **而唯一的那個家需要一道守門。**
> 少了它，這次的修正會變成一個**沒有人守著的單點** ——
> 21 個地方一起壞，比 21 個地方各自壞更難發現，因為它會一次全紅而看起來像環境問題。

⚠️ 更直接的理由：**同一個 bug 十天前就被修好過一次**
（`test_e2e_passkey` 於 2026-09-11 抽到 1723）。那次沒有守門，
所以十天後它在另一個檔又咬了一次。**這一支就是那個缺口。**
"""
from tests._ports import (
    CHROMIUM_RESTRICTED_PORTS, SAFE_PORT_HI, SAFE_PORT_LO, free_safe_port,
)


def test_never_returns_a_browser_restricted_port():
    """跑很多次，回傳值**一次都不可以**落在封鎖清單裡（§3f P1 明文）。"""
    got = [free_safe_port() for _ in range(200)]
    bad = [p for p in got if p in CHROMIUM_RESTRICTED_PORTS]
    assert not bad, f"回傳了瀏覽器封鎖埠：{sorted(set(bad))}"


def test_returns_distinct_usable_ports():
    """對照組：**證明它真的在挑不同的埠**，不是每次回同一個。

    ⚠️ 沒有這題，一個「永遠回 20001」的實作會讓上一題全綠 ——
    而那會讓兩支 e2e 同時跑時互搶同一個埠。
    🔑 「沒有回壞值」與「有在做事」是兩件事。
    """
    got = {free_safe_port() for _ in range(50)}
    assert len(got) > 1, f"每次都回同一個埠：{got}"
    for p in got:
        assert SAFE_PORT_LO <= p <= SAFE_PORT_HI, f"{p} 超出安全區間"


def test_safe_range_is_above_every_restricted_port():
    """釘住**區間與封鎖清單的關係**，而不只是現在的狀態。

    ⚠️ 這一題現在必然是綠的（清單最大 10080 < 20000）。
    **它守的是未來**：有人把 `SAFE_PORT_LO` 調低到 10080 以下時，這題會紅。

    🔑 守門要守的是未來的改動，不是現在的狀態 ——
    否則它只是把一個已經成立的事實再寫一次。
    """
    assert SAFE_PORT_LO > max(CHROMIUM_RESTRICTED_PORTS), (
        "安全區間下界 %d 沒有高過封鎖清單最大值 %d —— "
        "區間裡會混進瀏覽器拒連的埠" % (SAFE_PORT_LO, max(CHROMIUM_RESTRICTED_PORTS))
    )


def test_restricted_list_contains_the_two_we_actually_hit():
    """清單裡必須含**我們真的撞到過的那兩個**：1723（2026-09-11）、2049（2026-09-21）。

    ⚠️ 這不是重複上面那題。上面驗的是「區間高過清單」，這題驗的是
    **清單本身沒有被人順手刪掉** —— 兩個都成立才擋得住。
    """
    for port, when in ((1723, "2026-09-11 passkey"), (2049, "2026-09-21 material_orders")):
        assert port in CHROMIUM_RESTRICTED_PORTS, (
            f"{port} 不在清單裡，但我們在 {when} 真的撞到過它"
        )
