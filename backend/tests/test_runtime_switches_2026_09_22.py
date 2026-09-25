"""§8 FX1a／FX1b · 執行期開關的回報端點。

> **它存在的理由**：`GET /api/system/runtime-switches` 回報**跑著的那個行程**
> 實際看到的開關值 —— 🔑 **跑著的行程 ≠ 磁碟上的碼。**

---

# ⚠️⚠️ 怎麼驗它有一個陷阱，A 先撞到了

A 在**跑著的 666** 上打這一支 ⇒ **回 404**。
☠️ **而那不是缺陷** —— 是那個行程在這個 commit 之前就啟動了。
📌 **那正好演示了 FX1a 要解決的問題本身。**

⇒ 🔑 **所以這個檔一律用 `client`（行程內、從磁碟匯入），不打 666。**
⚠️ 用「打 666 看得到」當判準的話，**每次 B 剛 commit 完就會紅**，
而紅的理由與程式碼無關。

---

# 🔴 而這一支端點的形狀本身就是一個外洩風險

**一個「把環境變數印出來除錯」的端點是外洩的標準形狀。**
`os.environ` 裡有 SMTP 密碼、雲端金鑰、資料庫路徑。
⇒ FX1a1 的反向控制是這個檔最重要的一題：
**塞一個假的密鑰進環境，它不可以出現在回應裡。**
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

PATH = "/api/system/runtime-switches"

#: 一個**不在白名單裡**的環境變數，名字刻意長得像我們自己的。
#: 🔑 名字像才有意義：一個「白名單用 `startswith("MOTRIX_")`」的實作
#: **會把它一起倒出來**，而那種實作看起來完全合理。
FAKE_SECRET_NAME = "MOTRIX_FAKE_SMTP_PASSWORD"
FAKE_SECRET_VALUE = "ya-bu-ke-yi-chu-xian-zai-hui-ying-li-9a8b7c"


def _login(client, make_user, **kw):
    kw.setdefault("role", "superadmin")
    username, password = make_user(**kw)
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _get(client, hdr, expect=200):
    r = client.get(PATH, headers=hdr)
    assert r.status_code == expect, (
        f"{PATH} 預期 {expect}，實際 {r.status_code}：{r.text[:220]}"
    )
    return r.json() if r.status_code == 200 else r


# ══════════════════════════════════════════════════════════════════════
# FX1a1 · 🔴 只回白名單，不可以倒出整個環境
# ══════════════════════════════════════════════════════════════════════

def test_fx1a_the_endpoint_never_leaks_an_unlisted_variable(
        client, make_user, monkeypatch):
    """🔴🔴 FX1a1：**只回白名單裡的名字，不可以倒出整個 `os.environ`。**

    ## ☠️ `os.environ` 裡有什麼

    SMTP 密碼、雲端金鑰、資料庫路徑。
    🔑 **一個「把環境變數印出來除錯」的端點是外洩的標準形狀** ——
    而它通常是這樣長出來的：先回三個開關、然後有人說「順便看一下路徑」。

    📌 反向控制的名字刻意取成 `MOTRIX_FAKE_SMTP_PASSWORD` ——
    ⚠️ 一個用 `startswith("MOTRIX_")` 當白名單的實作**會把它一起倒出來**，
    而那種實作**看起來完全合理**。
    """
    monkeypatch.setenv(FAKE_SECRET_NAME, FAKE_SECRET_VALUE)
    hdr = _login(client, make_user)
    body = _get(client, hdr)

    blob = json.dumps(body, ensure_ascii=False)
    assert FAKE_SECRET_VALUE not in blob, (
        f"回應裡有那個假密鑰的**值**：{blob[:300]}\n"
        "☠️ `os.environ` 裡有 SMTP 密碼、雲端金鑰、資料庫路徑。"
    )
    assert FAKE_SECRET_NAME not in blob, (
        f"回應裡有那個假密鑰的**名字**：{blob[:300]}\n"
        "⇒ 名字本身也是情報（它說明這台機器設了什麼）。\n"
        "⚠️ 而它同時說明白名單是用 `startswith(\"MOTRIX_\")` 做的。"
    )


def test_fx1a1b_the_listed_switches_are_still_reported(client, make_user):
    """🔴 FX1a1b 反向控制：**白名單裡的那幾個要真的回得出來。**

    ☠️ 少了這一題，一個「**什麼都不回**」的實作會讓 FX1a1 綠 ——
    而那讓整個端點失去存在的意義（它是為了回答「跑著的行程看到什麼」）。
    🔑 〈判準的寬窄都會騙人〉：**「沒有洩漏」是一個空集合永遠滿足的條件。**
    """
    hdr = _login(client, make_user)
    body = _get(client, hdr)

    names = {s.get("name") for s in body.get("switches") or []}
    # L1 的開關；M11 的 MOTRIX_TENDER_RADAR 由 modules/tender_radar/tests/ 自己釘
    assert {"MOTRIX_GEO"} <= names, (
        f"白名單裡的開關沒有回出來，只有：{sorted(names)}"
    )
    for s in body["switches"]:
        for field in ("name", "label", "present", "raw", "on"):
            assert field in s, f"{s.get('name')} 少了 `{field}`：{s}"


# ══════════════════════════════════════════════════════════════════════
# FX1a2 · 🔴 on 要走各模組自己的 *_on()
# ══════════════════════════════════════════════════════════════════════

def test_fx1a2_the_resolved_value_comes_from_the_modules_own_rule(
        client, make_user, monkeypatch):
    """🔴🔴 FX1a2：**`on` 要走各模組自己的 `*_on()`**，不可以在端點裡重寫判斷式。

    ## 📌 B 的註解寫得很好，判準照它釘

    > 「重寫的話，這個端點會回報『**我以為的規則**』而不是
    > 『**它們實際用的規則**』—— 而那正是這個端點存在的理由。」

    ## ☠️ 沒有這一題會怎樣

    一個「自己判 `os.getenv(...) == '1'`」的實作**會全綠** ——
    🔑 而它會在 `geo_on()` 的規則改變那一天**安靜地開始說謊**。
    📌 〈守門守的對象被搬走〉：**斷言沒變、字面值沒變，
    而決定行為的已經不是它了。**

    ⇒ 判準：把 `geo_on()` 換成永遠回 `False` 的替身，
    **而環境變數設成會開啟的值** ⇒ 端點必須跟著回 `False`。
    ⚠️ 兩者要**反向**才分得出來：只換替身而環境變數也是關的話，
    **一個自己判環境變數的實作也會回 `False`** —— 那就分不出來了。
    """
    from helpers import geo

    monkeypatch.setenv("MOTRIX_GEO", "1")          # 環境說「開」
    monkeypatch.setattr(geo, "geo_on", lambda: False)   # 模組說「關」

    hdr = _login(client, make_user)
    body = _get(client, hdr)
    got = {s["name"]: s for s in body["switches"]}

    entry = got.get("MOTRIX_GEO")
    assert entry, f"回應裡沒有 MOTRIX_GEO：{sorted(got)}"
    assert entry.get("raw") == "1", (
        f"`raw` 應該照實回環境變數的值 `1`，實際 {entry.get('raw')!r}"
    )
    assert entry.get("on") is False, (
        f"`geo_on()` 回 False 而端點回 `on={entry.get('on')!r}`——\n"
        "⇒ 那個 `on` 是端點自己判環境變數算出來的，"
        "**不是模組實際用的規則**。\n"
        "☠️ 它會在 `geo_on()` 的規則改變那一天安靜地開始說謊。"
    )


def test_fx1a2b_a_module_that_says_on_is_reported_as_on(
        client, make_user, monkeypatch):
    """🔴 FX1a2b 反向控制：**模組說「開」時端點也要說「開」。**

    ☠️ 少了這一題，一個「`on` **一律回 `False`**」的實作會讓 FX1a2 綠 ——
    而畫面上會永遠寫著「開關沒生效」，
    🔑 **而那正是使用者拿這個端點去排除的那個問題本身。**

    📌 這裡把環境變數設成**關**、模組替身設成**開** —— 與上一題反向。
    """
    from helpers import geo

    monkeypatch.delenv("MOTRIX_GEO", raising=False)   # 環境說「關」
    monkeypatch.setattr(geo, "geo_on", lambda: True)  # 模組說「開」

    hdr = _login(client, make_user)
    got = {s["name"]: s for s in _get(client, hdr)["switches"]}
    entry = got["MOTRIX_GEO"]

    assert entry.get("present") is False, (
        f"環境變數沒設，而 `present` 是 {entry.get('present')!r}"
    )
    assert entry.get("on") is True, (
        f"`geo_on()` 回 True 而端點回 `on={entry.get('on')!r}`——\n"
        "⇒ 那個 `on` 沒有問模組。"
    )


# ══════════════════════════════════════════════════════════════════════
# FX1a3 · pid 與 startedAt
# ══════════════════════════════════════════════════════════════════════

def test_fx1a3_the_process_identity_is_reported(client, make_user):
    """🔴 FX1a3：**`pid` 與 `startedAt` 要在。**

    ## 🔑 它們分辨的是兩件在畫面上一模一樣的事

    | | 處置 |
    |---|---|
    | 開關沒生效 | 去改 `autostart.bat` |
    | **行程根本沒重啟** | 去重跑那個排程工作 |

    ☠️ 沒有它們，使用者只看到「開關是關的」⇒ **他會去改設定檔**，
    而問題是那個行程還是舊的 ⇒ 🔑 **他改完之後畫面不會變，
    而他會以為設定檔也壞了。**

    📌 而 A 今天就撞到這件事的實例：它在跑著的 666 上打這一支 ⇒ 404，
    **而那不是缺陷，是那個行程在這個 commit 之前就啟動了。**
    """
    hdr = _login(client, make_user)
    body = _get(client, hdr)

    assert isinstance(body.get("pid"), int) and body["pid"] > 0, (
        f"`pid` 不是正整數：{body.get('pid')!r}"
    )
    assert body["pid"] == os.getpid(), (
        f"`pid` 是 {body['pid']}，而這個行程是 {os.getpid()} ——\n"
        "⇒ 它回的不是自己的 pid，那個欄位分辨不出「行程沒重啟」。"
    )
    started = body.get("startedAt")
    assert isinstance(started, str) and started.strip(), (
        f"`startedAt` 是 {started!r} —— 沒有它就分不出「行程沒重啟」"
    )


def test_fx1a3b_started_at_does_not_move_between_two_calls(client, make_user):
    """🔴 FX1a3b 反向控制：**`startedAt` 是「行程啟動的時間」，不是「現在」。**

    ☠️ 少了這一題，一個回 `datetime.now()` 的實作會讓 FX1a3 綠 ——
    而它**永遠看起來像剛剛才重啟過**，
    🔑 **那個欄位的唯一用途（分辨行程有沒有重啟）就完全失效了**，
    而畫面上它看起來一直很健康。
    📌 〈計數器要有落點〉的鄰居：**一個永遠是「現在」的時間戳，
    與一個正確的時間戳在畫面上長得一樣。**
    """
    hdr = _login(client, make_user)
    first = _get(client, hdr)["startedAt"]
    second = _get(client, hdr)["startedAt"]
    assert first == second, (
        f"兩次呼叫的 `startedAt` 不同：{first!r} vs {second!r}\n"
        "⇒ 它回的是「現在」，而那讓這個欄位永遠看起來像剛剛才重啟過。"
    )


# ══════════════════════════════════════════════════════════════════════
# FX1a4 · 權限
# ══════════════════════════════════════════════════════════════════════

def test_fx1a4_only_a_superadmin_can_read_it(client, make_user):
    """🔴 FX1a4：**限 superadmin。**

    ⚠️ 它回報的是這台機器的執行期狀態（pid、啟動時間、哪些開關開著）——
    🔑 那是**偵察情報**：一個知道 `MOTRIX_TENDER_RADAR` 是關的人，
    知道哪一條線現在不會留下痕跡。
    """
    hdr = _login(client, make_user, role="sales", modules=["dev_crm"])
    _get(client, hdr, expect=403)


def test_fx1a4b_it_is_not_in_the_public_path_list():
    """🔴 FX1a4b：**不在 `_PUBLIC_API_PATHS` 裡。**

    📌 這一條是 YD1b 的第一個受益者 —— 我昨天才在那裡釘過
    「那個豁免清單**已經有 13 條**，再多一條不會有人注意」。
    🔑 ⇒ 所以這一題直接檢查那張清單，**而不是等它被加進去之後才發現**。

    ⚠️ 而它與 FX1a4 是兩條：FX1a4 驗「路由自己擋」，
    這一條驗「**沒有人幫它開後門**」。
    """
    import main

    assert PATH not in main._PUBLIC_API_PATHS, (
        f"`{PATH}` 被加進 `_PUBLIC_API_PATHS` 了 ——\n"
        "☠️ 那會讓未登入的人讀到這台機器的 pid、啟動時間與開關狀態。"
    )


# ══════════════════════════════════════════════════════════════════════
# FX1b1 · 部署腳本要去問它
# ══════════════════════════════════════════════════════════════════════

def test_fx1b_the_deploy_script_asks_the_endpoint():
    """🟡 FX1b1：部署腳本結束時要去問那個端點並印出來，不一致要**明著喊**。

    ## ⚠️ 兩個限制，我明講

    1. **這是文字比對**（`.ps1`），它答的是「有沒有被寫出來」。
    2. 🔴 **而它可能落在「只警告」那一桶** ——
       A 說「若是，在 docstring 裡講明，不要假裝它會擋」。
       ⇒ 我查過 `build_deploy_package.ps1`：⚠️ **那一段在腳本的結尾**，
       而結尾的動作**不可能中止已經做完的打包** ——
       🔑 **它是一個「告知」不是一個「關卡」**，而那是它的本質不是缺陷：
       **部署完成之後才能問那台機器，而那時包已經出去了。**

    📌 ⇒ 這一題的價值只有一個：**那一段不可以被順手刪掉**。
    真正會擋的是 `FX1c`（把兩個 `set` 搬到 `:loop` 之前），而那要 A 裁。

    ## 🔴 2026-09-22 FX30：**失敗訊息改成它實際在驗的那件事**

    D 找到的：這個斷言是 `"runtime-switches" in text` 的**子字串比對**，
    ☠️ 而腳本裡任何一行 `Write-Host` 的提醒文字就足以讓它綠。
    🔑 **而它的失敗訊息宣稱的是「有沒有去問」** ——
    兩者差得很遠：一個是「有沒有發出那個請求」，一個是「檔案裡有沒有這個字」。

    ⚠️ A 原本把它排進 `NEXT`（照「誰要的」分類），而我請求現在就改，
    理由是：**一個正在誤導的綠燈，不是下一包的技術債，是現在就在說謊的東西。**
    📌 A 准了，並補了一句我認為更準的：**分類是給還沒做的事用的。**

    ⇒ **只改訊息、不改行為、不增紅燈。**
    真正驗行為（那個請求有沒有被發出去）要在 `.ps1` 上跑一次，
    那是 `FX28`／`FX29` 那一批，留在 `NEXT`。
    """
    ps1 = (Path(__file__).resolve().parent.parent
           / "tools" / "build_deploy_package.ps1")
    assert ps1.exists(), f"找不到 {ps1}"
    text = ps1.read_text(encoding="utf-8", errors="replace")

    assert "runtime-switches" in text, (
        "`build_deploy_package.ps1` 裡找不到 `runtime-switches` 這個字。\n"
        "⚠️ **這一題驗的是「那個字還在檔案裡」，不是「那個請求真的被發出去」** ——\n"
        "   子字串比對連一行 `Write-Host` 的提醒文字都會收下。\n"
        "🔑 它唯一的作用是：**那一段不可以被順手刪掉。**\n"
        "📌 要驗行為得在 `.ps1` 上真的跑一次（`FX28`／`FX29`，在 `NEXT`）。"
    )
