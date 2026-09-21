"""E1～E4 · 重掃端點（`POST /api/tender-radar/reset-today`）。

B 把「重設每日上限」做成**只有測試模式才存在的端點**，閘門是
`if os.getenv("MOTRIX_TENDER_RADAR") == "1":` 包住 `@router.post(...)` ——
所以沒設環境變數時**路由根本沒有被註冊**，不是「註冊了但拒絕」。

## ⚠️ 這四題全部要在子行程裡跑，理由不是「比較保險」

閘門在 **import 時**判定，而 `MOTRIX_TENDER_RADAR` 是**機器的**環境變數。
在行程內驗的話，驗到的是**跑測試那台機器怎麼設定**，不是產品的行為：
- 開發機沒設 → 綠
- 實測機設了 → **紅，而且是在一台設定完全正確的機器上紅**

🔑 那正是今天 `test_08c` 差點掉進去的坑。⇒ 子行程裡**明確地**設或刪那個變數，
結果就與這台機器無關。

## 🔴 斷言不是「回 404」，是「**跟一個確定不存在的端點長得一模一樣**」

第一版我照 §3 寫成 `assert STATUS == 404`，**實跑是 405**。
原因是前端 SPA 有一條 catch-all 路由（`GET /{full_path:path}`）——
那個路徑對 GET 是匹配得上的，所以 POST 回的是 405 Method Not Allowed。

⚠️ 但 A 要的那個性質**沒有變**，只是它不等於「404」這個數字：
catch-all 讓**每一個**不存在的路徑都回 405 ⇒ 回應仍然什麼都沒說。
⇒ 所以斷言改成跟一個**確定不存在**的端點（`/api/tender-radar/this-endpoint-does-not-exist`）
逐一比對。**兩者一樣＝什麼都沒洩漏**，而這個寫法不綁死狀態碼、
也不會在哪天 catch-all 改掉時假紅。

🔑 **釘住「這個東西看起來要跟什麼一樣」，比釘住「它應該是哪個數字」耐用** ——
數字是那個性質今天的長相，不是那個性質本身。

## ⚠️ 斷言不可以用「有沒有 401」

`main.py:325` 的中介層是 `if not path.startswith("/api/") or path in _PUBLIC_API_PATHS`
⇒ **所有非公開的 `/api/` 路徑在路由之前就要求認證**。
所以未登入去打一個**不存在**的 `/api/` 路徑，拿到的是 **401 不是 404**。
⇒ 必須先登入再打，否則「端點不存在」與「我沒帶 token」長得一模一樣。
（我原本打算用 401/404 的差別當觀測點，讀了中介層那一行才發現不行。）

## 📌 E1 與 E4 現在必然是綠的 —— 它們仍然有用

判準不是「現在紅不紅」，是**什麼改動會讓它紅**：
- **E1** 有人把 `@router.post` 從那個 `if` 裡搬出去、無條件註冊 ⇒ 紅
- **E4** 有人把閘門從環境變數改成 `radar_on()` ⇒ 紅

⚠️ **E4 釘的是一條分界，而那條分界很容易被「讀起來很自然」壓掉**：
「雷達開著才需要重掃」聽起來完全合理，但 `radar_on()` 在**出貨開關被打開**時
也是 True —— 那是一台正常營運的**客戶機器**，它不該拿到一個能重設節流的端點。
🔑 **「雷達開著」與「這台是測試機」是兩件事**；它們在測試機上剛好同時為真，
**所以壓成一件的時候一點感覺都沒有**，差別要等到客戶打開開關那天才出現。

⚠️ 看到必綠的題目請不要當成廢題刪掉 ——
**守門失效時最容易發生的事是把它刪掉，而它其實只是不夠了。**

## E3 在哪裡

E3（`radar_on()` 的語意：沒設→False、`"1"`→True、`"0"`／`"true"`→False）
**已經由 `test_tender_match_2026_09_21.py` 的 08d／08e／08f 涵蓋**，
那三題用 `monkeypatch.delenv/setenv`，同樣與機器設定無關。這裡不重複寫。
"""
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
RESET_PATH = "/api/tender-radar/reset-today"

# ── 子行程腳本 ───────────────────────────────────────────────────────────
#
# ⚠️ `archive` 必須在 `import main` **之前**塞進 `sys.modules`：
#    `main.py:22` 是 `from archive import ...`（事後 patch 打不到），
#    而 `_schedule_daily()` 第一件事就是真的跑一次備份。
#    （這個形狀沿用 S5，見 test_tender_notify_2026_09_21.py。）
_SCRIPT = '''
import json, os, sys, tempfile, types

MODE = sys.argv[1]                      # "off" / "on" / "literal_on"

os.environ["MOTRIX_DISABLE_SCHEDULERS"] = "1"
if MODE == "on":
    os.environ["MOTRIX_TENDER_RADAR"] = "1"
else:
    os.environ.pop("MOTRIX_TENDER_RADAR", None)   # 明確刪掉，不靠這台機器沒設

import db
_tmp = tempfile.mkdtemp()
db.DB_PATH = os.path.join(_tmp, "t.db")
db.DEMO_DB_PATH = os.path.join(_tmp, "d.db")

class _Stub(types.ModuleType):
    def __getattr__(self, name):
        return lambda *a, **kw: None

sys.modules["archive"] = _Stub("archive")
import routers.daily_tasks as _dt
_dt.schedule_overdue_check = lambda *a, **kw: None

if MODE == "literal_on":
    # E4：**出貨開關被打開**（一台正常營運的客戶機器），但這不是測試機。
    import helpers.tender_source as _ts
    _ts.TENDER_RADAR_ENABLED = True

import main
from fastapi.testclient import TestClient
from helpers.auth import _hash_pw

conn = db.get_db()
try:
    conn.execute(
        "INSERT INTO users (username, password_hash, display_name, role, modules, "
        "active, created_at, must_change_password) VALUES (?,?,?,?,?,1,?,0)",
        ("e_admin", _hash_pw("Test-Pass-123"), "e_admin", "superadmin",
         json.dumps(["tender_radar"]), "2026-01-01T00:00:00"))
    conn.commit()
finally:
    conn.close()

c = TestClient(main.app)
r = c.post("/api/auth/login",
           json={"username": "e_admin", "password": "Test-Pass-123"})
assert r.status_code == 200, "登入失敗 %s %s" % (r.status_code, r.text[:300])
tok = r.json()["token"]

resp = c.post("/api/tender-radar/reset-today",
              headers={"Authorization": "Bearer " + tok})
# 對照：一個**確定不存在**的端點。不存在的樣子要長這樣。
ctrl = c.post("/api/tender-radar/this-endpoint-does-not-exist",
              headers={"Authorization": "Bearer " + tok})
print("STATUS=%d" % resp.status_code)
print("CONTROL=%d" % ctrl.status_code)
print("RADAR_ON=%d" % int(__import__("helpers.tender_source", fromlist=["x"]).radar_on()))
print("BODY=%s" % resp.text[:200].replace("\\n", " "))
'''


def _run(mode, timeout=240):
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT, mode],
        cwd=str(BACKEND), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    assert proc.returncode == 0, (
        f"子行程（{mode}）失敗 returncode={proc.returncode}\n{proc.stderr[-2500:]}"
    )
    out = dict(
        line.split("=", 1)
        for line in proc.stdout.splitlines() if "=" in line and line.split("=")[0].isupper()
    )
    assert "STATUS" in out, f"子行程沒印出 STATUS：\n{proc.stdout[-1200:]}"
    return out


def test_e1_endpoint_is_absent_without_the_env_var():
    """🔴 E1：沒有 `MOTRIX_TENDER_RADAR` → **404**。

    ⚠️ 是 **404 不是 403**：403 會說「這裡有東西，只是你不能用」，
    **404 什麼都不說** —— 而這個端點的存在本身就是「這台是測試機」的情報。

    📌 這裡拿到的是 **FastAPI 真正的 404**（路由沒被註冊），
    不是某個處理函式自己 `raise HTTPException(404)`。兩者外觀一樣，
    但後者代表**路由其實註冊了**，只是在執行期拒絕 —— 那道閘門就弱得多。
    """
    out = _run("off")
    assert out["STATUS"] == out["CONTROL"], (
        f"沒有環境變數時 {RESET_PATH} 回 {out['STATUS']}，而一個確定不存在的端點回 "
        f"{out['CONTROL']} —— **兩者不一樣就是洩漏**：回應本身說出了「這個路徑是特別的」。"
        f"（RADAR_ON={out.get('RADAR_ON')}，BODY={out.get('BODY')}）\n"
        "⇒ 有人把 @router.post 從環境變數的 if 裡搬出去了？"
    )
    assert out["STATUS"] != "200", "端點在沒有環境變數時竟然可用"


def test_e2_endpoint_exists_with_the_env_var():
    """E2：子行程設 `MOTRIX_TENDER_RADAR=1` 再 import → 端點**存在且可用**。

    ⚠️ 沒有這一題，一個「這個端點根本沒寫」的狀態會讓 E1／E4 **全綠** ——
    兩題都在驗「不存在」，而不存在是它們的**通過條件**。
    🔑 **先證明量尺有刻度，再拿它去量。**
    """
    out = _run("on")
    assert out["STATUS"] == "200", (
        f"設了環境變數卻拿到 {out['STATUS']}（BODY={out.get('BODY')}）"
    )
    assert out["STATUS"] != out["CONTROL"], (
        "端點存在時的回應跟「不存在」一模一樣 —— 那 E1／E4 什麼都沒證明"
    )
    assert "removed" in out.get("BODY", ""), (
        f"回應裡沒有 removed（清掉幾筆）：{out.get('BODY')!r} —— "
        "呼叫的人要知道這一次到底放寬了什麼"
    )


def test_e4_shipping_switch_alone_does_not_expose_the_endpoint():
    """🔴🔴 E4：`TENDER_RADAR_ENABLED = True` 但**環境變數沒設** → 仍然 404。

    這一題釘的是一條**分界**：
    **「雷達開著」與「這台機器是測試機」是兩件事。**

    ⚠️ 把閘門綁到 `radar_on()` 讀起來非常自然（「雷達開著才需要重掃」），
    而它會讓**每一台把出貨開關打開的客戶機器**都長出一個能重設每日節流的端點。
    每日一次是對政府網站的承諾 —— 它不會因為客戶打開了雷達就放寬。

    🔑 兩個條件在測試機上**剛好同時為真**，所以壓成一件的時候一點感覺都沒有；
    差別要等到「客戶把出貨開關打開」那天才會出現，而那天沒有人在看這段程式碼。

    📌 這一題的來歷：B 問 A「若之後有人寫『`TENDER_RADAR_ENABLED=True` 時端點
    也在』的題目，那題應該是紅的嗎」。**正確答案不是「到時候講」，是現在就把
    反面那一題寫進去** —— 一題把分界釘住的測試，**讓錯的那一題寫不出來**。
    """
    out = _run("literal_on")
    assert out.get("RADAR_ON") == "1", (
        "前提不成立：這一輪 radar_on() 應該是 True（否則這題驗不到分界）"
        f"，實際 RADAR_ON={out.get('RADAR_ON')}"
    )
    assert out["STATUS"] == out["CONTROL"], (
        f"雷達開著就把重掃端點露出來了（{out['STATUS']}，而不存在的端點是 "
        f"{out['CONTROL']}）—— 閘門被綁到 radar_on() 了。"
        "一台正常營運的客戶機器不該拿到這個端點。"
    )
    assert out["STATUS"] != "200", "客戶機器打開雷達之後就能重設每日節流了"
