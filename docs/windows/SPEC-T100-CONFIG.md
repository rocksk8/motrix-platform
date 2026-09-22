# T100 科目代號設定頁 `FN5` —— **施工圖**
> A-2 2026-09-23 02:4x ／ 落點 `docs/windows/SPEC-T100-CONFIG.md` ／ 誰在等：**使用者 → B**
> 🔴 無修訂層。

---
# 一、現況（A-2 實查）
```
端點      accounting_export.py:133  PUT /api/settings/t100-export-config   ✅ 存在
          :125                      GET 同路徑                            ✅ 存在
資料      system_settings 163 筆，**無任何 t100 鍵** ⇒ 從未被設定過
前端      三處引用（cashier.js／case-management.js／inventory.html）**全部只讀**
          ⇒ **沒有任何頁面可以寫它** —— 這就是使用者撞到的那件事
```
## 設定的完整欄位（`_DEFAULT_T100_CONFIG`，八個）
```
bankAccounts              []      [{name, acctCode}]
defaultBankAccountCode    ""      找不到「上次用哪個」時的退路
salesRevenueAccount       ""      銷貨收入
outputTaxAccount          ""      銷項稅額
contractorExpenseAccount  ""      承攬商費用
inventoryExpenseAccounts  {}      {料件分類: 代號}，鍵對應 parts.py::PART_CATEGORIES
departmentCode            ""      選填
voucherCategory           "轉"    有預設值
```

## 🔴 而「已設定完整」的判準漏了一格
```javascript
frontend/js/cashier.js:615-621（逐字）
  coreFilled = salesRevenueAccount && outputTaxAccount && contractorExpenseAccount
  hasBank    = bankAccounts.length > 0 && every(b => b.name && b.acctCode)
  return !!(coreFilled && hasBank)
```
☠️ **`inventoryExpenseAccounts` 不在判準裡。**
```
⇒ 料件分類的科目一個都沒設，畫面照樣顯示「**✓ 科目代號已設定**」
⇒ 而料件／設備進貨的傳票會用到它（accounting_export.py:254「借 料件設備成本」）
⇒ ⇒ **匯出的那幾列科目代號是空的，而畫面說設定完整**
```
📌 `departmentCode`（選填）與 `voucherCategory`（有預設）不在判準裡**是對的**。
⚠️ 而 `defaultBankAccountCode` 不在判準裡 ⇒ **要不要納入，見 §四**。

---
# 二、🔴 代號一律**從科目樹選**，不可自由輸入
```
理由：打錯的代號**不會報錯** —— T100 匯出照樣產生，
      到會計師匯入 T100 那一刻才發現，而那時傳票已經開出去了
```
⚙️ 守門：設定值必須存在於 `account_items.code` ⇒ 不存在 ⇒ **拒絕儲存**

## 選的時候擋什麼（A-2 裁）
```
停用的（is_active=0）    🔴 **擋** —— 停用的科目不該被新設定引用
                            ⚠️ 而**已經設定好的**不因停用而失效（見下）
非 statutory 的          ✅ **不擋** —— 使用者自訂的科目也可能是正確的對應
層級／葉節點             🔴 **裁不了，列為未決**（見 §五）
```
### ⚠️ 「已設定的科目後來被停用」怎麼辦
```
不可以靜默失效 ⇒ 設定頁要**明著顯示「這個科目已停用」**並要求重選
🔑 理由：靜默失效的症狀是「匯出的科目代號突然變空」，而沒有人會知道為什麼
```

---
# 三、🔴 警告文字要帶路徑
```
現在  「⚠ 科目代號尚未設定完整」        ← 沒說去哪設
改成  「⚠ 科目代號尚未設定完整 —— 請到【設定 → T100 匯出設定】完成」
      ＋ 連結（若該頁在同一個 SPA，直接可點）
```
📌 與 `RAISE(ABORT)` 那一條同源：**那句話是使用者唯一看得到的東西**，
   而「看得到」不等於「知道下一步」。

---
# 四、銀行帳戶清單（A-2 裁）
```
新增  ✅ 做
刪除  ⚠️ 做，**而已被 defaultBankAccountCode 引用的不可刪** ——
      要刪先改預設（與「已被引用的科目不可改 code」同一條原則）
排序  ❌ **不做** —— 它沒有語意，而「預設帳戶」已經有自己的欄位
```
## ⇒ 而 `defaultBankAccountCode` 要納入完整性判準
```
理由：它是「找不到上次用哪個」時的退路（accounting_export.py:85 註解）
      ⇒ 它沒設 ⇒ 那個退路不存在 ⇒ **而畫面說設定完整**
⚙️ 判準改成：三個科目 ＋ bankAccounts 非空且每筆完整 ＋ **defaultBankAccountCode 在清單內**
              ＋ **inventoryExpenseAccounts 涵蓋 PART_CATEGORIES 全部的鍵**
```

---
# 五、⚠️ 未決 —— **「哪些科目可以被選」我裁不了**
```
直覺  只能選葉節點（沒有子節點的）
      理由：T100 要掛分錄，而中間節點是彙總
☠️ 而它不成立：**合計列也是葉節點**
   （我今晚量過：L2 的 86「本期稅後淨利」、88「本期綜合損益總額」都沒有子節點）
   ⇒ 而合計列**不該**被掛分錄
🔴 而資料上**分辨不出**「葉節點」與「合計列」—— 官方表沒有那個欄位
```
⇒ **本輪不做層級限制**，而在設定頁**顯示該科目的完整路徑**（1 → 11-12 → 111 → 1111），
  讓使用者自己看得出他選的是不是一個合計項目。
⚠️ **不要自己發明「合計列偵測」** —— 那會是一個猜，而猜錯時它靜默地擋住正確的選擇。

---
# 六、權限
```
superadmin（沿用既有：accounting_export.py:26 註解「由 superadmin 在 … 設定」）
⚠️ **不放寬** —— 科目代號設錯的後果落在會計師那一端，而他不在這個系統裡
```

---
# 七、⚙️ 兩問掃描
| 決定 | 誰決定的 | 副作用列過了嗎 |
|---|---|---|
| 一律從科目樹選 | **A** | ✅ 代價：科目樹沒建好之前設定不了 ⇒ 而 FN1 已落地 |
| 停用的擋、非 statutory 不擋 | **A-2** | ✅ 代價：已設定的科目被停用時要重選（已寫處置） |
| 不做排序 | **A-2** | ✅ 代價：帳戶多時順序固定，而「預設」已有欄位 |
| 判準加 defaultBankAccountCode ＋ inventory | **A-2** | ✅ 代價：**現有設定會從「完整」變「不完整」** ⇒ 而它本來就不完整 |
| 不做層級限制 | **A-2** | ✅ 代價：使用者可能選到合計列 ⇒ 用「顯示完整路徑」緩解，非阻擋 |
| 權限 superadmin | **既有**（accounting_export.py:26） | ✅ |

---
# 八、⚠️ 未查
```
✗ 那三處前端引用是否真的「全部只讀」—— 我採信 A 的實查，未自己驗
✗ PART_CATEGORIES 現在有幾個分類（inventoryExpenseAccounts 要涵蓋它們）
✗ 設定頁要放在哪一個既有頁面底下（設定頁的結構我沒看）
```
