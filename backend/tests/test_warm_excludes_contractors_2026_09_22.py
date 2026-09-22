"""§3v 補 · 外包人員的住家地址不進背景佇列（VD1／VD2）。

---

# 🔑 B 的理由（比規格原本的好，逐字留著）

> **「地圖在『有權限的人打開時』查它是『有人要求』；
> 『背景迴圈』查它是『沒有人要求而我們把它送出去』。
> 技術上一樣，性質上不一樣，而只有後者是我們自己決定的。」**

📌 那是 §3t〈外洩的出口不一定是你寫的〉的同一族，**而方向相反**：
§3t 是「別人替我們記錄了」，這一條是「**我們主動送出去**」。
☠️ `contractors` 是自然人名冊，那個 `address` 是**住家地址**
⇒ 背景暖快取會把它送到 Nominatim（一個第三方）。

---

# ⚠️ VD2 明文要求：**釘不變量，不要釘那一行 filter**

規格原話：
> **不是釘實作裡那一行 filter** —— **下一個人加一張帶住家地址的新表時，
> 要有人問他同一個問題。**

⇒ 所以這裡**不**斷言 `_WARM_EXCLUDED == ("contractors",)`。
🔑 釘那個常數的話，換一種寫法（改用 per-dataset 旗標、或把它移到
`_DATASETS` 的欄位裡）**就會在一個正確的實作上變紅**，
而今天我已經犯過那個錯四次。

⇒ 釘的是：**外包名冊的地址不出現在背景佇列裡**，
**不管那是怎麼做到的。**
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import routers.map_points as mp  # noqa: E402


def _contractor_addresses():
    """`contractors` 表裡所有非空的地址。"""
    import db
    conn = db.get_db()
    try:
        return {(r["address"] or "").strip()
                for r in conn.execute(
                    "SELECT address FROM contractors "
                    "WHERE address IS NOT NULL AND TRIM(address) <> ''")}
    finally:
        conn.close()


@pytest.fixture()
def roster(client):
    """塞兩筆外包人員（自然人）＋一筆協力廠商（公司）。

    📌 那一筆公司是**對照組**：它**應該**進佇列 ——
    🔑 否則「排除生效」與「整個佇列是空的」分不出來。
    """
    import db
    conn = db.get_db()
    try:
        for name, addr in (("VD 外包甲", "台中市梧棲區忠孝路 1 號"),
                           ("VD 外包乙", "高雄市前鎮區中山二路 2 號")):
            conn.execute(
                "INSERT INTO contractors (name, address, active, created_at) "
                "VALUES (?,?,1,?)", (name, addr, "2026-09-22T00:00:00"))
        conn.execute(
            "INSERT INTO vendor_contractors (name, address, active, created_at)"
            " VALUES (?,?,1,?)",
            ("VD 協力廠商", "台北市信義區市府路 3 號", "2026-09-22T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def test_vd1_the_personal_roster_never_reaches_the_background_queue(
        client, roster):
    """🔴🔴 VD1／VD2：**外包人員的住家地址不出現在背景佇列裡。**

    ## 🔑 三道斷言，而第一道是整題的成敗

    | | 為什麼 |
    |---|---|
    | ① 佇列**不是空的** | 否則「排除生效」與「什麼都沒撈到」分不出來 |
    | ② 外包地址**確實存在** | ☠️ **否則「`contractors` 是空表」永遠會綠** |
    | ③ 兩者交集是空的 | VD1 本體 |

    ☠️ **② 是 B 特別指出的那一道**：
    > **「沒有它的話，『contractors 表是空的』與『排除生效』
    > 會長得一模一樣，而前者永遠綠。」**

    📌 **不釘 `_WARM_EXCLUDED`** —— VD2 明文要求釘不變量不釘那行 filter
    （見檔頭）。這一題不管它是用常數、旗標、還是別的方式做到的。
    """
    backlog = set(mp._map_geocode_backlog())
    addrs = _contractor_addresses()

    assert backlog, (
        "背景佇列是空的 —— 這一題的前提不成立。\n"
        "⇒ 空佇列與「排除生效」分不出來（協力廠商那一筆應該在裡面）。"
    )
    assert addrs, (
        "`contractors` 表裡一筆有地址的都沒有 —— 這一題的前提不成立。\n"
        "☠️ 少了這道斷言，「表是空的」與「排除生效」會長得一模一樣，"
        "**而前者永遠綠**。"
    )

    leaked = backlog & addrs
    assert not leaked, (
        f"這些外包人員的**住家地址**進了背景佇列：{sorted(leaked)}\n"
        "☠️ 背景迴圈會把它們送到 Nominatim（第三方），"
        "而那是**沒有人要求而我們自己決定送出去的**。\n"
        "🔑 前景查（有權限的人打開地圖）照舊，那是有人要求。"
    )


def test_vd1b_the_business_addresses_do_reach_the_queue(client, roster):
    """🔴 VD1b 反向控制：**協力廠商（公司）的地址要進佇列。**

    ☠️ 少了這一題，一個「**整個暖快取都不撈廠商**」的實作會讓 VD1 綠 ——
    而那會讓背景定位對自有據點完全失效，
    🔑 而症狀是「**地圖上的廠商點一直要等前景查**」——
    使用者看到的是「有時候有、有時候沒有」。

    📌 那一筆是公司（`vendor_contractors` 有 `tax_id`），
    **營業地址不是住家地址** —— VD1 排除的理由不適用於它。
    """
    backlog = set(mp._map_geocode_backlog())
    assert "台北市信義區市府路 3 號" in backlog, (
        f"協力廠商的營業地址不在背景佇列裡。佇列裡有 {len(backlog)} 筆。\n"
        "⇒ VD1 排除的理由是「住家地址」，不適用於公司的營業地址。"
    )


def test_vd2_a_new_table_with_home_addresses_is_not_silently_included(
        client, roster):
    """🔴 VD2：**下一個人加一張帶住家地址的新表時，要有人問他同一個問題。**

    ## ⚠️ 這一題我做不到規格要的那件事，我明講

    規格要的是「**新表加進來時有人被問**」。
    ☠️ 而那是一個**關於未來的人的行為**的要求 —— 測試驗不到。
    🔑 我唯一做得到的是：**讓「哪些資料集會進背景佇列」這件事
    在一個地方寫著，而且與前景用的那份清單分得開。**

    ⇒ 釘的是：背景佇列的來源清單是**明示的**（不是「前景有的就全部拿」），
    而那份明示的清單**比前景的少** —— 那個差額就是被排除的東西。
    📌 差額為零的話，「排除」這個概念在程式碼裡**不存在**，
    而下一個人加新表時**沒有任何東西會讓他停下來**。

    ⚠️ 而我**不驗那份清單的內容**（那會變成釘 filter）——
    只驗「它存在、而且真的比前景少」。
    """
    foreground = set(getattr(mp, "_DATASETS", {}))
    assert foreground, "`_DATASETS` 不見了 —— 前景的資料集清單是這一題的基準"

    backlog_names = set()
    for name in foreground:
        spec = mp._DATASETS[name]
        table = spec.get("table") if isinstance(spec, dict) else None
        if table:
            backlog_names.add(name)
    assert backlog_names, "前提不成立：沒有任何一個資料集有 table"

    # 背景佇列**實際**涵蓋的資料集：用它撈出來的地址反推。
    backlog = set(mp._map_geocode_backlog())
    addrs = _contractor_addresses()
    assert addrs, "前提不成立：`contractors` 沒有地址"

    assert not (backlog & addrs), (
        "外包名冊的地址在背景佇列裡 —— 見 VD1"
    )
    excluded = getattr(mp, "_WARM_EXCLUDED", None)
    assert excluded, (
        "找不到任何「背景佇列要排除哪些資料集」的明示宣告。\n"
        "⇒ 沒有那個宣告的話，「排除」在程式碼裡不存在，"
        "而下一個人加一張帶住家地址的新表時，**沒有任何東西會讓他停下來**。\n"
        "📌 我不驗它的內容（那會變成釘 filter），只驗它存在。"
    )
    assert set(excluded) <= foreground, (
        f"排除清單裡有不存在的資料集：{set(excluded) - foreground}\n"
        "⇒ 那是一列指不到東西的資料，而它讀起來像一個決定。"
    )
