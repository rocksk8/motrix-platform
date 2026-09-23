# `SPEC-EM2` · 角色名稱不可硬寫在訊息裡

> 座標：`d59f47f`（工作樹：本檔為新增，其餘未動）
> 作者：視窗 A-2 ／ 2026-09-23
> 裁定：A **甲案**（動態解析）。`STATE.md §265`。

---

## §1 這一題的判準翻過一次面，**錯的那一列留著**

### ❌ 原判準（A 初裁，已作廢）

```
「11 條訊息與畫面不一致 => 改成『超級管理員』」
⚙️ 正對照 11 條會亮 ／ 負對照 那 10 條『超級管理員』不可以亮
```

### 🔴 它為什麼不成立

```
backend/routers/system.py:2000  _DEFAULT_ROLE_LABELS = {"superadmin": "超級管理員", ...}
backend/routers/system.py:2039  GET  /api/settings/role-labels   _require_user
backend/routers/system.py:2054  PUT  /api/settings/role-labels   require_superadmin=True
frontend/pages/users.html:266   <input x-model="rlForm.superadmin" placeholder="超級管理員">
```

🔑 **「超級管理員」是預設值，不是畫面的固定用詞。**
客戶按一次 PUT 把 superadmin 改名成「總經理」，**29 句訊息一起錯**——
**包含原判準指定當負對照的那一批**。

☠️ 絕對化藏在「畫面」兩個字裡：**畫面上那個詞本身是資料。**

📌 而「與畫面一致」問的是**哪一個畫面**——`sidebar.js` 與 `users.html` 今天就對不上（見 §2b）。

---

## §2 母體：**29 條後端 ＋ 5 份前端對照表**

### §2a 後端 `HTTPException` 的 `detail` 裡硬寫 superadmin 名稱 = **29 條**

（AST 取 `HTTPException` 的 `detail` 字面值，掃 `backend/**/*.py`，排除 `rollback_snapshots/` 與 `tests/`）

```
最高管理者  9   daily_tasks.py:419,472,552
                dev_crm.py:463,660
                quotations.py:1865,2420,2463,3372
最高管理員  3   approval_delegates.py:66,116
                quotations.py:477
超級管理員 17   auth.py:228,230,1550,1584,1643,1692
                quotations.py:1401,1571,1905,3462,4308,4465
                completion_notes.py:486 ／ contractor_vouchers.py:494
                invoice_vouchers.py:532 ／ payment_requests.py:689
                shipping_notes.py:391
```

### ⚠️ 上一份回報寫「11 條」，那是錯的母體——**這一列留著**

```
我上一則報 8／3／10 = 21，那是 `EM1` 的 **11~25 字視窗**撈到的，
而我**沒有講這個限定**。全長重掃才是 29。
🔑 〈判準的寬窄都會騙人〉：太窄的判準給的是**假陰性**，
   而我拿它去做了一個「只有 11 條」的裁定建議。
```

### §2b 前端 **5 份各自硬寫**的對照表（**沒有一份讀 `/api/settings/role-labels`**）

```
frontend/pages/approval-queue.html   :1402  superadmin: '最高管理者'
frontend/pages/online-stats.html     :368   superadmin: '最高管理者'
frontend/static/sidebar.js           :296   superadmin: '最高管理者'
frontend/pages/daily-tasks.html      :2999  superadmin: '超管'
frontend/pages/approval-settings.html:900   superadmin: '超級管理員'
──
frontend/pages/users.html            :771 / :773   （Alpine 初值＋表單初值，
                                                    是合理的 fallback，不在母體）
```

☠️ **第四個詞「超管」**——最初的三詞掃描（`最高管理者`／`最高管理員`／`超級管理員`）
**完全沒有看到它**。
🔑 它證明「有三種說法」這個數字本身**是沒查完的**。

### §2c 使用者自己也混用 ⇒ **這一題沒有裁示可依**

```
STATE.md 使用者原話   最高管理者 23 ／ 最高管理員 5 ／ 超級管理員 20
```
📌 而**甲案不需要那個裁示**——它讀設定，而設定是客戶自己填的。

---

## §3 處置（甲）

### §3a 後端：新增 `backend/helpers/role_labels.py`

```python
"""角色顯示名稱：**唯一的解析點**。

☠️ 不要在訊息裡寫死角色名稱 —— 它是客戶可改的設定
   （PUT /api/settings/role-labels），寫死的那天客戶改名就全錯。
"""
from helpers.settings import _get_setting

DEFAULTS = {
    "superadmin": "超級管理員",
    "admin":      "管理員",
    "sales":      "業務",
    "engineer":   "工程師",
    "viewer":     "檢視者",
}

_CACHE: dict = {"v": None}


def role_labels() -> dict:
    """五個角色的顯示名稱。行程內快取，PUT 之後由 invalidate() 清掉。"""
    if _CACHE["v"] is None:
        _CACHE["v"] = {**DEFAULTS, **(_get_setting("role_labels") or {})}
    return _CACHE["v"]


def role_label(key: str) -> str:
    return role_labels().get(key, key)


def invalidate() -> None:
    """PUT /api/settings/role-labels 成功之後**必須**呼叫。"""
    _CACHE["v"] = None
```

#### ⚠️ 為什麼是**新檔**而不是改 `helpers/settings.py`（與 A 的界線 ④ 不同）

```
A 的界線 ④：helpers/settings.py 是共用檔 => 動前宣告
我的建議  ：開新檔 helpers/role_labels.py，**settings.py 一行都不動**
理由      ：省掉共用檔的宣告與碰撞，而能力一樣
📌 若 A 仍要放進 settings.py，本節照搬即可，其餘不變。
```

#### ⚠️ 快取失效的**邊界條件**（寫下來，因為它不會自己提醒你）

```
今天成立：三支啟動指令都**沒有 --workers**
          backend/start.bat:27 ／ restart.bat:40 ／ autostart.bat:31
          => 單一 uvicorn process => 行程內快取清得掉
🔴 日後若加 --workers N，**另外 N-1 個 process 的快取不會失效**
   => 改完名字，有些請求還是舊的，而**它與「沒生效」長得一樣**
   ⇒ 那一天要改成不快取，或改成帶版本號的 settings 讀取
```

### §3b 後端：29 條改成組出來

```python
# 改前
raise HTTPException(403, "僅超級管理員可執行此操作")
# 改後
raise HTTPException(403, f"僅{role_label('superadmin')}可執行此操作")
```

⚠️ **逐條改，不要 sed** ——29 條的句型不只一種，其中三條不是「僅 X 可…」：

```
approval_delegates.py:66   「…如需代替他人設定請聯絡最高管理員」
quotations.py:477          「…或聯繫最高管理員」
quotations.py:1905         「案件已結案，僅超級管理員可變更案件進度」
```

### §3c `put_role_labels` 收尾要清快取

```
backend/routers/system.py:2061  _set_setting("role_labels", labels)
                                + invalidate()          <= 新增這一行
```
🔑 驗收：**改完名字重整頁面就生效，不必重啟 server**。

### §3d 前端 5 份對照表改讀端點（**這一包的範圍，不是後續**）

```
approval-queue.html:1402 ／ online-stats.html:368 ／ sidebar.js:296
daily-tasks.html:2999    ／ approval-settings.html:900
```

☠️ **只改後端的話「看起來像修好了」而畫面還是不一致。**

建議做法：`sidebar.js` 本來就每頁載入 ⇒ 由它取一次放進 `window.__roleLabels`，
其餘四處改讀它；取不到時回落 `DEFAULTS`。
⚠️ 回落**不可以是空字串**——取不到要顯示預設中文，不是顯示 `superadmin`。

---

## §4 `EM2` **不使 `PX1` 變得不必要**

```
EM2   訊息**組出**角色名   => 與**設定**一致
PX1   訊息說的角色  vs  **程式實際檢查的**   => 與**程式**一致
```

⚠️ 一句組出來的「需要超級管理員」，若程式檢查的是 `role in ("superadmin","admin")`，
**它仍然是說謊，只是說得比較一致。**
📌 `EM2` 全綠**不構成** `PX1` 的任何證據。

---

## §5 守門

### ✅ 要釘的不變量

> **後端 `HTTPException` 的 `detail` 字面值裡，不出現任何硬寫的角色名稱。**

### 🔴 不可以釘的

```
❌ 「超級管理員是對的」          <= 把預設值當成不變量，正是本題的錯
❌ 「29 條」這個數字             <= 計數會過期；新寫的第 30 條擋不到
```

### ⚙️ 對照組（缺一不可）

```
正對照  §2a 那 29 條 —— **改之前全部要亮**
        🔑 先跑一次看它亮 29 個，再去改；不亮就是掃描器壞了
負對照  backend/helpers/role_labels.py 的 DEFAULTS 那一支定義 **不可以亮**
        （它是名字的來源，不是訊息）
        ⚠️ 排除方式要釘在**檔名＋變數名**，不要用「含有 DEFAULTS 的行」
           —— 後者會把別人的字典一起放行
誘餌    刻意留一條測試用的假訊息（合成的，不要用真缺陷當誘餌），
        確認守門會抓到「新寫的」而不只是「清單裡的」
```

⚠️ **反向控制**：守門若有排除清單，要有一題驗「清單長度沒有變長」——
否則可以靠把 29 條全寫進排除清單變綠。

---

## §6 驗收（`AC1`：後端＋前端＋頁面三者皆備）

```
① 後端  29 條全部組出；role_labels.py 存在；put 之後 invalidate()
② 前端  5 份對照表改讀端點；回落是預設中文不是 role key
③ 頁面  users.html 改名 superadmin -> 「總經理」後：
        ⓐ 側邊欄在線成員顯示「總經理」
        ⓑ 簽核佇列顯示「總經理」
        ⓒ 打一支 403 端點，detail 回「僅總經理可執行此操作」
        🔑 ⓒ **不重啟 server** —— 那是 invalidate() 的驗收
```

### 💰 已量過的成本

```
現有測試會紅的 = **0 支**
  （AST 掃 254 支測試的 Assert 節點，角色名稱只出現 13 處，
    **13 處全是 assert 的失敗訊息**，沒有一支斷言那 29 句的字面值）
```

---

## §7 我沒查什麼

```
① 其餘四個角色（admin／sales／engineer／viewer）的硬寫數量 —— **只查了 superadmin**
   ⚠️ 「管理員」是「超級管理員」「最高管理員」的子字串，
      「業務」在「業務確認」「業務主管」裡大量出現 => 直接數會過報
   ⇒ 那是另一次量測，不要從這 29 條推它的規模
② 前端**非對照表**形式的硬寫（例如 bonus.html:150 的
   「新增獎金項目只有<strong>最高管理員（superadmin）</strong>做得到」）
   —— 那是散文不是對照表，這一份規格**沒有涵蓋它**
③ PDF／信件範本裡的角色名稱
```
