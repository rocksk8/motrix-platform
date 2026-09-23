# -*- coding: utf-8 -*-
"""`EM5` · `helpers/build_info.py::_reload_flag()` 要回三態，不可以把
「不知道」silently coerce 成 `False`（已出貨，補題）。

# 🔴 為什麼是「補題」不是「派工」

全庫沒有任何測試提到 `_reload_flag`／`build-info`（`grep -rl` 零命中）
——這支修復已出貨，卻沒有任何東西守著它。

# 🔴 判準：釘行為（三態），不要釘文字

```
uvicorn CLI／`python -m uvicorn` 起的  => True／False（argv 裡看得到）
其他方式起的（例如程式裡 uvicorn.run()）
                                       => None（**不知道**，不是「沒開」）
sys.argv 存取本身失敗                  => None
```
☠️ 〈null 不等於 0〉在這裡的落點：`None`（不可得）與 `False`（確定關）是
兩件事，混在一起的後果不是版面錯字，是**啟動行**（`startup_line()`）與
`/api/build-info` 的 `reload` 欄位會在「不知道」的時候說「關」——而
`--reload` 開著的時候程式碼是熱重載的，那個保證是給人拿去判斷「我看到
的到底是不是磁碟上這一版」用的，說錯比不說還糟。

# ⚙️ 觀測點：兩層

```
① _reload_flag() 本身——**直接測**，因為它是 sys.argv 的純函式，
   而 `_RELOAD`／build_info()["reload"] 是 import 當下就凍結的模組層級
   常數（見它自己的註解：「在 import 時算，不是每次請求算」）——測試
   行程的 argv 是 pytest 的 argv，不是 uvicorn，凍結值在整個測試過程
   裡**不會變**，沒辦法從下游重現 True／False 兩態，只能直測這支純函式。
② GET /api/build-info——驗**這個測試環境裡它現在真的是什麼**（pytest
   起的行程，argv 不是 uvicorn ⇒ 應該是 None），順便驗 JSON 傳輸沒有
   把 `None` 序列化成 `false`。
```

# ✅ 牙齒已驗證（方式：突變驗證／live，非常設）

monkeypatch 掉「只有真的是 uvicorn 本身才有資格回 False」那道判斷式
（模擬把 `prog not in (...)` 那道守門拿掉，變成看到 argv 有 `--reload`
字串就回 True／False，不管是誰在跑）：`argv=["python","app.py"]`
（程式裡呼叫 `uvicorn.run()` 那一種）本來應該是 `None`，突變後**真的
變成 False（编的）**，① 的「程式化啟動回 None」那題**真的會紅**；
正對照（真的是 `uvicorn --reload` 起的那題）在同一個突變下**仍然是
綠的**，證明這道守門分辨得出「哪一種呼叫方式該回什麼」。
"""
import sys

import pytest

from helpers.build_info import _reload_flag


def _with_argv(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", argv)


# ══════════════════════════════════════════════════════════════════════
# ① _reload_flag() 直測：三態逐一釘
# ══════════════════════════════════════════════════════════════════════

def test_em5_uvicorn_cli_with_reload_is_true(monkeypatch):
    _with_argv(monkeypatch, ["uvicorn", "main:app", "--reload"])
    assert _reload_flag() is True


def test_em5_uvicorn_cli_without_reload_is_false(monkeypatch):
    _with_argv(monkeypatch, ["uvicorn", "main:app"])
    assert _reload_flag() is False, (
        "沒有 `--reload` 應該是 `False`——若這裡不是 `is False`（例如變成"
        "`None`），代表判斷式把『確定關』也算成『不知道』了。")


def test_em5_uvicorn_exe_on_windows_is_recognized(monkeypatch):
    """⚙️ Windows 上 argv[0] 可能是 `uvicorn.exe`，一樣要判得出來。"""
    _with_argv(monkeypatch, ["uvicorn.exe", "main:app", "--reload"])
    assert _reload_flag() is True


def test_em5_python_dash_m_uvicorn_with_reload_is_true(monkeypatch):
    _with_argv(monkeypatch, ["python", "-m", "uvicorn", "main:app", "--reload"])
    assert _reload_flag() is True


def test_em5_python_dash_m_uvicorn_without_reload_is_false(monkeypatch):
    _with_argv(monkeypatch, ["python", "-m", "uvicorn", "main:app"])
    assert _reload_flag() is False


def test_em5_programmatic_uvicorn_run_is_unknown_not_false(monkeypatch):
    """🔴🔴 **程式裡呼叫 `uvicorn.run()` 時，argv 完全不提 reload——要回
    `None`（不知道），不可以編一個 `False`。**

    ☠️ 這是本題的核心：`main.py` 若改成 `uvicorn.run(app, reload=True)`
    這種寫法，argv 只有 `["python", "main.py"]`，這裡**沒有任何資訊**能
    判斷 reload 到底開了沒——回 `False` 是騙人的（明明可能是開著的）。
    """
    _with_argv(monkeypatch, ["python", "main.py"])
    assert _reload_flag() is None, (
        "回的是 %r——程式化啟動時 argv 不提 reload，正確答案是「不知道」"
        "（`None`），不是編一個確定值。" % (_reload_flag(),))


def test_em5_python_dash_c_mentioning_uvicorn_is_unknown_not_false(monkeypatch):
    """⚙️ **`argv` 裡含有 `"uvicorn"` 這個字不代表判得出來**——
    `python -c "import uvicorn; uvicorn.run(...)"` 的 argv[0] 是
    `python`，不是 `uvicorn` 本身，一樣要回 `None`。"""
    _with_argv(monkeypatch, ["python", "-c",
                             "import uvicorn; uvicorn.run(app)"])
    assert _reload_flag() is None


def test_em5_argv_access_failure_is_unknown(monkeypatch):
    """⚙️ `sys.argv` 存取本身失敗（`list()` 炸開）時一樣回 `None`，
    不是讓例外炸穿到呼叫端（`build_info()` 的規則是任何一步都不丟例外）。
    """
    monkeypatch.setattr(sys, "argv", 12345)  # int 不可疊代 => list() 炸開
    assert _reload_flag() is None


# ══════════════════════════════════════════════════════════════════════
# ② 下游：/api/build-info 在這個測試環境裡真的回 None，且 JSON 沒有把它
#    序列化成 false
# ══════════════════════════════════════════════════════════════════════

def test_em5_build_info_endpoint_reload_is_null_not_false_under_pytest(
        client, make_user):
    """🔴 **這個測試行程是 pytest 起的，不是 uvicorn——`/api/build-info`
    的 `reload` 應該是 JSON `null`，不是 `false`。**

    ⚠️ 用 `is None` 驗，不是 `assert not body["reload"]`——後者
    `False` 與 `None` 都會通過，證明不了兩者有被分開。
    """
    u, p = make_user(username="em5_reload", role="viewer")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    hdr = {"Authorization": "Bearer " + r.json()["token"]}

    r = client.get("/api/build-info", headers=hdr)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert "reload" in body, "回應裡沒有 `reload` 這個鍵：%r" % body
    assert body["reload"] is None, (
        "測試行程不是 uvicorn 起的，`reload` 應該是 `null`，實際是 %r——"
        "若是 `False`，代表『不知道』被編成了『確定關』。" % body["reload"])
