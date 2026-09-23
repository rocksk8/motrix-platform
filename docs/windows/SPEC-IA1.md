# `SPEC-IA1` · 出貨的安裝裡有我們自己的帳號

> 座標：`20a9227`（工作樹：本檔為新增）
> 作者：視窗 A-2 ／ 2026-09-23
> 🔴 **出貨阻擋**（A 發編號並直接進 `SCOPE THIS`）

---

## §1 ✅ A 的事實我複驗過，而**多一格他沒提**

```python
# helpers/startup.py:102  init_default_admin()   ← **每次啟動都跑，不是 migration**
if not …WHERE username='jeff'…:
    INSERT INTO users (…) VALUES ('jeff', ?, '黃玉龍', 'superadmin', 'jeff@miactw.com', …)
else:
    UPDATE users SET display_name='黃玉龍' WHERE username='jeff'
      AND display_name IN ('Jeff 管理員','Jeff','jeff','jeff超級管理員',**''**)
    UPDATE users SET email='jeff@miactw.com' WHERE username='jeff'
      AND (email='' OR email IS NULL)
```

### ✅ A 對 D 的更正**成立**

```
❌ D 寫「else 分支每次啟動都會重新校正」=> **不對**，兩句 UPDATE 都有 WHERE 守衛
✅ 客戶改成自己的名字之後，**不會被改回去**
```

### 🔴 而 A 只講了 email 那一格 —— **`display_name` 的清單裡也有 `''`**

```
`display_name IN (…, **''**)`
=> 客戶把顯示名**清空**，下次啟動會被改成「黃玉龍」
=> 🔑 與 email 那一格**同一種窄面**，而它少被講到
```

> ### ⇒ 兩個窄面：**清空 email ⇒ 變成 `jeff@miactw.com`；清空顯示名 ⇒ 變成「黃玉龍」。**

### ⚙️ 而 `IA1` 為什麼直接進 `THIS` 而 `MG5` 留 `NEXT`（A 的理由，成立）

```
MG5（`_m008`）  一次性歷史 migration，全新安裝時三句 UPDATE 都是 0 列（D 已驗）
IA1             **活碼**，每次啟動執行，**100% 發生，不依賴任何巧合**
=> 「migration 是凍結的歷史」這個理由**對 IA1 不成立**
```

---

## §2 🔴🔴 而 `init_demo_account()` **是同一題，而且更嚴重**

> A 給的判準：「**它會不會出現在客戶手上？** 答『會』就同一題。」

```python
# helpers/startup.py:138   main.py:528 **無條件呼叫**
INSERT INTO users (…) VALUES ('demo', ?, '展示帳號', '**superadmin**', ?, 1, ?, **0**)
_hash_pw("**60575481**")
```

```
🔴 role      = superadmin
🔴 密碼      = **60575481** —— 而那是**公司的統一編號**
              （`reports.py:74` 與 `network_plan_export.py:369` 都印著「統一編號 60575481」，
                **印在客戶自己匯出的 PDF 頁尾上**）
🔴 must_change_password = **0**  <= **不強制改密碼**
```

⚙️ 而我查了三件，**三件都空**：
```
① 有沒有開關可以關掉它      => **沒有**（grep `DEMO_ENABLED`／`ENABLE_DEMO` 等 = 0）
② 登入頁看不看得到 demo     => **看不到**（客戶不知道它存在）
③ 授權底座有沒有處理它      => **沒有**（`licensing.py` 提到 demo = 0 處）
```

> ### ☠️ **每一個賣出去的安裝都有一個 `demo` superadmin，
> ### 密碼是一個印在他們自己 PDF 上的數字，而沒有辦法關掉。**

### ✅ 而**資料隔離是真的** —— 嚴重度要往下修

```
⚙️ `routers/auth.py:394` 實讀：username == 'demo' =>
   `reset_demo_db()` ＋ token 帶 `DEMO_TOKEN_PREFIX`
   => middleware 把**每一個後續請求**（含 `_require_user()`／`_audit()`）路由到隔離的 demo DB
   docstring 逐字：「**never touches real data**」
```

> ### ⇒ ❌ **不是「客戶資料會外洩」** —— 那個說法不成立。
> ### ✅ 是「**客戶的系統裡有一個他不知道的 superadmin，而它的密碼是一個公開數字**」。

```
⚠️ 而它做得到的事：任何知道 `60575481` 的人可以**隨時 wipe demo DB**
   （`reset_demo_db()` 在每一次 demo 登入時執行）
   => 影響的只有展示資料，**而那對客戶本來就沒有用**
🔑 ⇒ 真正的問題不是它能做什麼，是**它不該在那裡**
```

📌 ⇒ 兩半的**處置不同**：
```
`init_default_admin`  => 改成**通用身分**（那個帳號客戶要用）
`init_demo_account`   => 🔴 **不該在客戶的安裝裡跑**（它對客戶零用途）
```

---

## §3 ⚠️ 而「產品碼裡不存在 `miactw.com`」這個不變量**會誤傷** —— 母體要先切開

⚙️ 實數（排除 `tests/`／`rollback_snapshots/`／`deploy_packages/`／`db_backups/`）：
```
`miactw`  = **15 處**
`黃玉龍`   = **4 處**
```

### 🔴 而它們是**四種東西**

```
① 🔴 **身分帳號**（本規格的主體）= 3 處
   startup.py:112（INSERT）／:126（display_name）／:130（email）

② 🟡 **公司抬頭／頁尾** = 7 處  <= **另一件事，不要一起改**
   db.py:711（contact_info 預設值）／company_identity.py:43（email）
   network_plan_export.py:369 :380 ／ reports.py:74（`_COMPANY2`）
   quotation-form.html:2030 :2143
   📌 那是「公司抬頭寫死」那一族 —— `company_profile` 設定已經存在，
      而**只有銀行欄位被 PDF 讀**（另一個編號）

③ ✅ **說明文字／placeholder**（不是資料）= 4 處
   main.py:59（環境變數註解的範例）／system.py:1393（「例如 erp.miactw.local」）
   company-profile-settings.html:131 ／ users.html:456（兩個都是 placeholder）
   🔑 ⇒ 守門要**剝註解**，而 placeholder 要明著排除

④ 🟡 **migration／一次性工具** = 3 處
   db.py:958 :985（`_m008` = `MG5`）／tools/sync_pending_data_20260817.py:21
⚙️ 加總 3 + 7 + 4 + 3 = **17**（含 `黃玉龍` 那幾處與 `miactw` 重疊的）
```

> ### 🔑 ⇒ **A 說的「產品碼裡不存在 `miactw.com`」直接釘的話，②③④ 全部會紅** ——
> ### ☠️ 而最省力的反應是**把它們全部加進排除清單**，那就等於沒守。

---

## §4 處置

### ① `init_default_admin`：**身分三個值換成通用的**

```python
VALUES ('admin', ?, '系統管理員', 'superadmin', '', …)
```
```
✅ 而**不要動安裝流程的其餘部分**：
   `secrets.token_urlsafe(14)` 隨機臨時密碼 ／ `_write_initial_credentials()` ／
   `must_change_password=1`  —— 那三件是對的
🔑 要改的只有**身分那三個值**
```

⚠️ 而 `else` 分支那兩句 UPDATE：
```
🔴 **整段拿掉** —— 它的用途是修 2026 年初的舊資料（那五個 display_name 變體）
=> 對一個**新客戶**它只會做一件事：把空的顯示名／email 填成我們的
☠️ 而留著它並「改成通用值」更糟：客戶清空 email ⇒ 被填成 `''`⇒ 看起來像沒發生
```

### ② `init_demo_account`：**預設不跑**

```
✅ 環境變數開關（預設 **關**）：`MOTRIX_DEMO_ACCOUNT=1` 才建立
🔑 判準：**它對客戶零用途** => 預設不存在，而我們展示時自己開
⚠️ 而**已經建立的怎麼辦**（升級既有安裝）——
   🔴 不可以「開關關著就刪掉它」：那會在有人正在用展示時把帳號刪掉
   ⇒ 開關只管**建立**；既有的由 `IA1` 的 migration 停用（`active=0`）
   ☠️ 而**不要刪列** —— 刪了之後 audit_log 的外鍵與歷史對不上
```

### ③ 🔴 而密碼 `60575481` **不可以只換成另一個寫死的**

```
☠️ 換成 'demo1234' => 同一個問題，換一個數字
✅ 開關開啟時**產生隨機密碼並寫進 `_write_initial_credentials()`**
   —— 與 `init_default_admin` 同一條路
```

---

## §5 驗收（`AC1`）

```
① 後端  init_default_admin 的三個值改成通用；else 分支整段拿掉
        init_demo_account 預設不跑；既有的由 migration 停用
        demo 開關開啟時用隨機密碼
② 前端  無異動
③ 頁面  ⓐ **全新安裝** -> `users` 表裡：
           `admin` 一個（`must_change_password=1`）、**沒有 `demo`**
           🔑 ⓐ 是核心
        ⓑ 把 `admin` 的顯示名與 email **清空** -> 重新啟動
           => 🔴 **仍然是空的**（不可以被填回任何值）
           ☠️ 少了 ⓑ，「只改 INSERT 而 else 分支留著」會綠
        ⓒ `MOTRIX_DEMO_ACCOUNT=1` -> 重啟 => demo 建立，**而密碼是隨機的**
           且憑證檔裡查得到
        ⓓ 既有安裝（已經有 demo）升級 -> demo 變成 `active=0`，**而那一列還在**
           🔑 ⓓ 驗的是「停用不是刪除」
        ⓔ 🔴 負對照：升級之後**登入頁與使用者管理頁沒有壞掉**
           （停用一個 superadmin 不可以讓任何頁面 500）
```

### 🔴 而**不變量的驗收要先數例外**（A 交代）

```
✅ 釘：`backend/helpers/startup.py` 裡不存在 `miactw`／`黃玉龍`／`60575481`
   🔑 **範圍縮到那一支檔**，不是整個產品碼 ——
      ☠️ 釘整個產品碼會撞到 §3 的 ②③④ 共 14 處
⚙️ 而那一支檔今天的命中 = **4 處**（:112 ×2、:126、:130）＋ demo 的 `60575481`
   => 改完應該是 **0**
✅ 而 §3 ②④ 各自有自己的編號，**不在這一件裡**
⚠️ ③（placeholder／註解）**永遠不會是 0**，而它不在這支檔裡 => 不受影響
```

---

## §6 守門

```
✅ 釘：`helpers/startup.py` 裡沒有公司識別字串
   ⚙️ 母體判準：`ast` 取該檔所有**字串常數**（排除 docstring）
      比對 {`miactw`, `黃玉龍`, `60575481`}
   🔑 用 `ast` 不用 grep —— 而這一次的理由不是幽靈，是
      ☠️ **`grep` 的 `\b`／`-w` 對全形標點失效**（今天實測，中文專案一律不可信）

⚙️ 誘餌（合成）：
   A  一段假的 `INSERT … VALUES ('x', '黃玉龍', …)`  => **必須亮**
   B  docstring 裡提到 `miactw`                      => **不可以亮**（ast 排除 docstring）
   C  改成通用值的正確版本                            => **不可以亮**
   D  🔴 `_hash_pw("60575481")`                       => **必須亮**
      🔑 D 是關鍵 —— 它不是「公司名稱」而是**統編當密碼**，
         而一個只掃 `miactw`／`黃玉龍` 的守門會漏掉它
```

---

## §7 ⏳ 待使用者回來確認

```
① ⏳ **出廠帳號叫什麼**
   我裁（沿用 A）：**通用身分** —— `admin`／「系統管理員」／email 留空
   依據：帳號、顯示名、email **三個都是公司資料**，而客戶拿到的應該是他自己的
   ⇒ **若他要保留 `jeff` 當出廠帳號**（為了遠端支援）：
      🔴 email 與顯示名**仍然要拿掉**，且 `DEPLOY.md` 要**明寫**
         「出貨後第一件事是改掉它」
      ⚠️ 而那會讓每個客戶的系統上都有一個叫 `jeff` 的 superadmin ——
         ☠️ 若他同意，要接受「**所有客戶的出廠帳號同名**」這個事實

② 🔴 **demo 帳號預設關掉**
   我裁：**關**（環境變數開啟）
   依據：它對客戶**零用途**（登入後走隔離的 demo DB，看不到他的資料），
        而它是一個 superadmin、密碼是公司統編、且不強制改密碼
   ⚠️ 而它**不是資料外洩** —— 隔離是真的（`auth.py:394` 實讀）
   ⇒ **若他要保留**（例如業務展示要用）：那至少要
      ① 隨機密碼 ② `must_change_password=1` ③ `DEPLOY.md` 寫明它存在

③ ⏳ **既有安裝的 demo 要停用還是留著**
   我裁：**停用（`active=0`）而不刪列**
   依據：刪列會讓 `audit_log` 的歷史對不上；而停用是可逆的
   ⇒ **若他要刪**：要先確認 `audit_log` 裡沒有指向它的列（**我沒查**）
```

---

## §8 我沒查什麼

```
① 🔴 正式機上的 `jeff`／`demo` 帳號現在是什麼狀態 —— **沒查**（不碰正式機）
   ⚠️ 而 `IA1` 改完之後，正式機**不會**受影響（`jeff` 已存在 ⇒ 走 else 分支，
      而 else 分支要拿掉 ⇒ 它就完全不動了）
② `_write_initial_credentials()` 把憑證寫到哪裡、權限是什麼 —— **沒讀**
   🔑 而 §4③ 說「demo 的隨機密碼也寫進去」⇒ 那條路要先確認它是安全的
③ 停用 demo 之後，`reset_demo_db()` 那條路會不會有殘留 —— **沒查**
   ⚠️ demo DB 檔案本身還在（`DEMO_DB_PATH`），而那是另一個問題
④ ✅ **已對**：用完整的公司識別字串集重數 = **13 檔／34 行**
   （`允碩`／`MOTRIX Synergy`／`60575481`／`04-3610-6566`／`info@miactw`）
   ```
   backend/  db.py  helpers/auth.py  helpers/company_identity.py  helpers/startup.py
             network_plan_export.py  pdf_gen.py  routers/reports.py
             tools/sync_pending_data_20260817.py
   frontend/ index.html  pages/company-profile-settings.html  pages/login.html
             pages/quotation-form.html  pages/users.html
   ```
   🔑 我的記憶說「56 行／14 檔」—— **檔數對得起來（13 vs 14），行數差很多**
   ⇒ 差在**關鍵字集不同**，不是有人修過
   ⚠️ 而 §3 的分類是用 `miactw`／`黃玉龍` 兩個字串量的 ⇒ **那一份比較窄**
   ☠️ ⇒ §3 的「② 公司抬頭 7 處」**是低估的**，真實數字要用上面那一組量
   📌 而本規格的範圍**不受影響**（只做 `startup.py`）

⑤ ✅ **而重數時撿到一個我原本會漏掉的檔**：`backend/helpers/auth.py:37`
   ```python
   _LEGACY_WEAK_PASSWORDS = ("rock1125", "**miac@60575481**", "password", …)
   ```
   🔑 ⇒ **那是防護不是缺陷** —— `flag_weak_passwords()` 用它強制那些帳號輪換密碼
   ⚠️ 而它仍然是「公司資料寫死在出貨碼裡」，且它**洩漏了「我們曾經用過這個密碼」**
   ⇒ 嚴重度低（它的存在是為了擋，不是為了用）=> **本規格不動它**，但登記
   ☠️ 而一個只掃 `miactw`／`黃玉龍` 的守門**看不到它**（它是 `miac@` 不是 `miactw`）
      => 📌 那正是 §6 誘餌 D 要防的那一種：**不是公司名稱，而是公司資料**

⑥ `60575481` 在**前端**的處數 —— 已含在 ④ 的 13 檔裡（`index.html:828`）
⑦ 🔴 §3 的 ②（公司抬頭）**有沒有既有編號在追** —— **沒查**，要 A 確認
```
