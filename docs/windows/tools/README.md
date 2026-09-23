# 稽核工具（從各視窗的 scratchpad 搶救出來的）

> 2026-09-23：使用者要切換 B／C／D 的模型。scratchpad 是 **session 綁定**的，
> 換 session 就不見 ⇒ 由 A 複製進 repo 保存。
> ⚠️ 這些是**一次性稽核腳本**，不是產品碼，也不在 CI 裡。**它們不保證還能跑**
> （路徑、SHA、資料都會過期）——留著是為了**下一次要量同一件事時不必重寫**。

| 檔 | 做什麼 | 已知限制 |
|---|---|---|
| `port_provenance.ps1` | `BR2` 反查：埠 → 祖先鏈 → 啟動方式 → 推定 commit → 判「間隔」 | 見下 |
| `em4_scan2.py` | `EM4` v2（**被 v4 當模組 import，不要單獨改它**） | L1-L6 |
| `em4_scan4.py` | `EM4` v4（加「值裡有沒有理由」；`exec` 進 v2 用它的函式） | L1-L6 |
| `em7_review.py` | `EM7` 18 處逐一讀 ＋ 函式層 L7 證據 | L7-L10 |
| `em7_negctrl.py` | 收緊「迴圈有在數」的判準（找出那 5 個） | L9 |
| `br3_scan.py` | 模組層 `if`/`try` 包住路由註冊 | L1-L4 |
| `json_layer_scan2.py` | JSON 鍵層「產品能不能寫」（三來源：Python／DB 欄位／前端） | — |
| `em8_scan.py` | `EM8` ①：訊息指路而前端查不到（含正負對照） | L1-L4，見下 |
| `em8_reverse.py` | `EM8` ②：前端有入口、後端沒端點（反向於 `check_endpoint_entrypoints.py`） | L1-L4，見下 |
| `em1_mismatch.py` | `EM1`（第三種形狀）：地方存在但名字對不上（近似比對，人判） | L1-L4，見下 |
| `em8_gap.py` | 觸發詞收斂清單：`請至/在/到` 之外還有哪些「指路」說法兩把尺都收不到 | L1-L3，見下 |
| `px1_scan.py` | `PX1`：權限訊息說的與程式實際檢查的是不是同一件事（走 AST 取角色比較） | L1-L4，見下 |

## 🔴 `port_provenance.ps1` 的五個已知限制
```
L1 「載入版本」是由 **CreationDate 推定**，不是問行程 => **BR1 的 build_info 才是權威**
L2 對**不載入 repo 程式碼**的行程照樣算落後 => 那一欄無意義
L3 祖先鏈斷掉時回「未知」並**保守假設 expect=true** => 偏向多報（8765 就是）
L4 只掃**指定的埠**，不會自己發現「還有哪些行程在跑」
L5 ⚠️ **只寫在這裡，沒進過任何輸出**：它用
   `git rev-list -1 --before=<CreationDate>` **只看當前分支**
   => 若那次啟動的是**別的分支或別的工作樹**，推定會**靜默錯**
```

## ⚙️ `EM4` 的正對照本體**沒有複製**，而它取得回來
```
ctrl_voucher_pdf_old.py = git show a9e1119^:backend/helpers/voucher_pdf.py
```
🔑 **那是刻意的**：檔案會過期，而**那條 git 指令永遠取得到同一份**。

## ☠️ 三個「怎麼判的」，不知道會重踩
```
1. **.ps1 一定要補 BOM** —— Write 工具建的 .ps1 在 PS5.1 下用 cp932 讀 => **整份語法錯**
   修法 [System.IO.File]::WriteAllText(..., New-Object System.Text.UTF8Encoding($true))
   並用 [Parser]::ParseFile() 驗到 0 錯
2. **邏輯不要放進 Bash heredoc** —— `r"[\\/]"` 的反斜線被吃掉一層
   => 排除 tests／tools／snapshots 的過濾器**整個失效，而輸出看起來正常**
   => 所有掃描器都改成**寫成 .py 檔再執行**
3. **db 一律先複製到 scratchpad 再開** —— 直接開會產生 `-wal`／`-shm`，
   而那會**移動別人正在量的數字**（實際發生過：驗包的計數從 38 被推到 94）
   ⚠️ 用完要刪（D 停工時刪了 **39 個副本**，含正式機副本，內含真實個資）
```

## 📌 試過而**沒命中**的 pattern（避免重跑）
```
6667 的啟動入口   現役 .bat/.ps1/.py/.vbs/.md 全掃 => **只有** tests/_ports.py 的埠排除清單
                  與視窗文件的「不要碰」=> **查不到任何入口**（不是「沒有」，是查不到）
reset-today 前端  reset-today／reset_today／tender-radar/reset／resetToday **四種全 0**
                  前端實際打的：watches5／tenders2／schedule2／status1／scan1
EM7 其他形狀      模組層 if/try 包 include_router 0／包 import routers 0／
                  條件式 APIRouter() 0／從 app.routes 移除 0
```

## ⚠️ 兩個交集（不處理會讓「總共幾個問題」灌水）
```
licensing.py:598 _stable_machine_id  同時在 EM4(37) 與 EM7 => **已從 EM7 扣掉**
archive.py 的 prune 4 處             EM7 第一級，而 G:\每日備份 實查 62／not-a-date **0**
                                     => 機制成立而尚未發生 => 排序在 ②③ 之後
```

## 🔴 `EM8` ①／②／`EM1` 的已知限制

**`em8_scan.py`（① 訊息指路，前端查不到）**
```
L1 目標詞用正則截取（請至/請在/請到 附近）；截取失敗的進「需要人看」，逐一讀過不丟
L2 前端比對用子字串，換 4 種變體（駝峰/底線/去空白/小寫）再查一次才敢說「查不到」
L3 只掃訊息字面值，不掃 log（log 是給維護者看的）
```

**`em8_reverse.py`（② 前端有入口、後端沒端點）**
```
L1 前端字串串接組出來的路徑（'/api/x/' + id）取不到，只能取到常數字面值那一段
L2 method 猜不到時只比路徑忽略 method（偏寬鬆，避免誤報）
☠️ 兩次自己的洞（都是**先給錯誤結論、被驗證步驟自己抓到**才修）：
   ① 漏了 APIRouter(prefix=...)（account_items／bonus／vouchers 三支）
   ② 漏了 app.include_router(X.router, prefix="/api")（main.py 層級，dev_crm 專用）
   兩個都修完後，剩下的候選**逐一**對路由表比對，最終確認 0 個真的 404
   🔑 「剩下的看起來都一樣」是一個假設，不是一個驗證——16 個全部比對過才敢寫 0
```

**`em1_mismatch.py`（第三種形狀：地方存在而名字對不上）**
```
L1 近似比對（difflib.SequenceMatcher），ratio 只是排序依據，每一條都要人看過
L2 前端標籤目錄只認 <label>／class 含 title|head|label|eyebrow／<h1-4>／<button>／短 <span>
   ⚠️ 不在這些形狀裡的畫面文字不會進目錄（例如「設備清單」精確存在於
   network-plan-form.html 但沒被任何目錄形狀包住，仍被判成「近似不相等」）
L3 相似度低於門檻不代表是第一種形狀（不存在），只代表這把尺沒把握
L4 範圍含 email_notify.py（信件）
☠️ 修過一個會**靜默吃掉下一個標籤**的 bug：巢狀空殼 div（`<div class="ns-card-head">`
   包住 `<div class="ns-card-head-title">文字</div>`）外層先比對、把空白當內容抓走，
   `finditer` 從被吃掉的 `<` 之後續掃 ⇒ **內層真正的標籤永遠比對不到**。
   這正是「Edge 瀏覽器路徑」（正對照）第一次沒亮的成因 —— 改用 `(?=<)` 零寬預查
   ＋ 要求擷取內容至少一個非空白字元才修好。**任何用「裸 `<` 收尾」抓標籤文字的
   正則都會中這個病**，下次寫類似掃描器先想到這個。
```

## ✅ `EM8`／`EM1` 確認的缺陷（三種形狀各一例）
```
第一種 地方不存在      dashboard.py:110 gcis_daily_limit（系統沒有任何通用設定編輯介面）
                      inventory.py:614 edit_note（沒有前端按鈕）
第三種 名字對不上      helpers/startup.py:42「Edge 執行檔路徑」vs 畫面實際「Edge 瀏覽器路徑」
                      （相似度 0.70；端點 /api/settings/edge-path 有接，純粹改了名字）
```
📌 「修改連結」（dev_crm.py:551）前端**完全查不到**（連近似都沒有，最近的只有 0.57）
—— 用的是「請透過」不是「請至/請在/請到」，`em8_scan.py` 的正則沒收到，**未分類**，
下一輪要查請把「請透過」也加進 `em8_scan.py` 的觸發詞。

## ✅ `em8_gap.py`：觸發詞收斂清單（產出是清單，不是「又找到幾個缺陷」）

**先印「查得到」母體，再看「查不到」——9 個候選詞裡 6 個本專案真的有這種寫法：**
```
請透過   查得到 0／查不到 4   有效，納入下次
可在     查得到 1／查不到 2   有效，納入下次（但查不到那 2 個都是型錄資料，非訊息）
請於     查得到 0／查不到 5   有效，納入下次
前往     查得到36／查不到 9   有效，納入下次（查不到那 9 個多是信件 CTA 按鈕文字本身，自我指涉）
開啟     查得到 1／查不到 2   有效，納入下次
到…頁面   查得到 2／查不到 1   有效，納入下次
點選／按下／在…設定裡          本專案沒有這種寫法，不必收錄
```
⚙️ 正對照：「修改連結」出現在②（縫）✅。⚙️ 負對照：與 `em8_scan.py` 已收過的目標詞
**零重複** ✅。

### 🔴 「縫」裡逐一看過，撈到**第四種形狀**的一個真實案例

```
訊息  reports.py:874「請於系統設定中配置年度目標後，本頁將自動顯示各指標達成率分析」
實查  「系統設定」（company-profile-settings.html）裡**沒有**年度目標欄位
      真正的設定入口是 **reports.html 本頁自己的按鈕**：
      <button class="btn-set-target" @click="openTargetModal()">立即設定年度目標</button>
      => 存到 /api/settings/operating-targets
```
🔑 **第四種形狀**：「系統設定」這個名字本身是對的（那個分頁真的存在），
**但可以做這件事的地方不在那裡**——跟第三種（名字對不上）不同，這裡是
**名字對，指的卻是錯的區塊**。使用者會先去系統設定頁翻找，翻不到才可能想到
回報表頁找按鈕。

**其餘「查不到」的 22 條逐一看過，都不是缺陷：**
```
請透過（3 條）  描述「正式流程」「解鎖」等抽象程序，不是具名 UI 元素
可在（2 條）    seed 型錄資料，不是使用者訊息
請於（3 條）    期限用語／籠統「系統中」，不是具名元素
前往（9 條）    信件本身就是那顆按鈕的文字（CTA 自我指涉，不需要在別處存在同一字串）
開啟（2 條）    描述動作或「案件頁」泛稱，非具名元素
到…頁面（1 條）  抽取多帶了「系統的」前綴，「標案雷達頁面」本身精確存在（雜訊，非真的）
```

## 已知限制（`em8_gap.py`）
```
L1 每個觸發詞的擷取規則不同、比 em8_scan.py 粗；「前往」「開啟」大量出現在非指路語境，
   擷取後仍需人工過濾，這支不自動下結論
L2 只掃 backend 訊息字面值，範圍同 em8_scan.py
L3 只用子字串判斷「查不到」，不含近似比對；「查不到」不等於「不存在」，
   要接 em1_mismatch.py 再查一次
```

## 🔴 `px1_scan.py`（`PX1`：權限訊息 vs 實際檢查）—— 修過一次分類邏輯

☠️ **原始版本把 176 處全部標成「不一致」，而那全部是假陽性**：
```
把 `role not in ('superadmin','admin')`（admin 以上皆可過）
跟 `role != 'superadmin'`（只有 superadmin 能過）當成**同一類**
—— 因為判準只看 cond_src 字串裡有沒有出現 "superadmin"，沒看比較到的**集合**
```
修法：改用 AST 直接取 `role != 'x'` / `role not in (a,b,...)` 比較到的**字串集合**，
回「通過此條件所需的最小角色集合」，不猜語意（見檔內 `classify_guard()`）。

**結果（HEAD `ce56988`）：**
```
掃 101 支 .py，raise HTTPException(401/403, 字面 detail) 共 176 處
role_guard 判得出來的 75（字面角色比較）／判不出來（守衛條件不明）101
  ✅ 一致 75
  🔴🔴 訊息說得比實際嚴 0
  🔴 訊息說得比實際鬆 0
```

**⚠️ 正對照：找不到，照 A 的指示明著寫「這把尺這次沒有正對照」，不湊一個。**
已查證的範圍（不是「沒查」，是查過而沒發現）：
```
① 自動掃描 75 個字面角色比較點 => 0 個不一致
② 使用者點名的角色名稱三種說法（超級管理員10／最高管理者8／最高管理員3，共 9 個
   raise 點）逐一打開，**全部**檢查 role=='superadmin'，訊息也都是「僅 X 可執行」
   => 0 個不一致（三種說法只是中文措辭差異，屬於 EM2 範圍不是 PX1）
③ 8 支重複貼上的 _require_admin（completion_notes／contractor_vouchers／inventory／
   invoice_vouchers／module_versions／payment_requests／shipping_notes／
   vendor_contractors）逐一比對——module_versions.py 用 `_ROLE_RANK` 数值比較
   （寫法不同），但 `rank<2` 擋掉的集合與其他 7 支的 tuple 比較**語意相同**
   （允許 {admin, superadmin}），不是不一致
④ 3 支重複貼上的 _guard_voucher（contractor_vouchers／invoice_vouchers／
   payment_requests）逐一比對 => 邏輯與訊息一致，只有傳給 require_any_module()
   的顯示名稱不同（「承攬商付款」／「開票憑證」／「請款單」，那是各自的單據名稱，正確）
⑤ can_see_financial() 的訊息「需要『財務金額可視』模組」**檢查過是不是不完整**——
   它同時允許 role in (superadmin,admin,sales)。**判斷：不是缺陷。**
   會看到這句訊息的人，定義上已經不具備那三種角色**也不是文件的簽核人**，
   對這個人來說「申請財務金額可視模組」確實是唯一能做的事，訊息沒有說謊。
```
⇒ **101 個「守衛條件不明」還沒有人工逐條看過**（只抽樣看了上面 ①-⑤ 涵蓋到的約
20 條），那裡才是下一輪如果要繼續查 `PX1` 該去的地方——特別是巢狀 `if` 與
跨函式呼叫（`_guard_case`／`guard_case_access`／`_can_access_case` 這類還沒讀）。

## 已知限制（`px1_scan.py`）
```
L1 「守衛條件」用**同一函式內、raise 往上最近的 if**近似抓，多層巢狀 if 可能抓錯層
   ——這類進「守衛條件不明」，不下結論
L2 只認字面角色比較與 `_require_user(require_superadmin=,module=)`／已知具名 helper。
   **中介層**（main.py 的 auth middleware）與**動態組出來的角色判斷**看不到，
   這支完全沒有掃到它們，不是「掃過沒發現」
L3 401 與 403 混掃；401 幾乎都是「未登入」固定文字，很少出現字面不一致（預期中）
L4 module 中文名是否與 detail 一致只做存在性檢查，不驗證翻譯——那是 EM2 的範圍
```

## 🔴 `PX1` 第二輪：跨函式共用守衛（人工逐一讀，非自動掃描）

L1／L2 標過「跨函式的守衛完全看不到」——這輪手動把那幾支共用守衛函式與呼叫端
的 detail 逐一比對。**結果同樣是 0，⚠️ 正對照同樣找不到**，明著寫不湊。

**讀過的共用守衛（全部）：**
```
guard_case_access()   helpers/quotations.py    7 支 router 共用（13 個呼叫點）
_guard_case()  ×2      case_extra_expenses.py（簡化版，僅擁有者）
                       quotations.py（含 allow_module／allow_approver／
                       skip_if_semi_unlocked，**同名不同檔**，逐一比對過不是誤植）
_check_quotation_owner()  上面兩支共用的核心，唯一真正拋出 403 的地方
_guard_action_item_case()  case_action_items.py（主管簽核例外 + 委派 guard_case_access）
_can_access_case()     dev_crm.py（6 個呼叫點：查看/修改/新增記錄各自訊息）
_guard_queue_detail()／_can_see_queue_money()  quotations.py（簽核佇列詳情）
```

**判準（沿用 ⑤ 的推論，這次用在更大範圍上）：**
```
guard_case_access() 失敗時**重新拋出** _check_quotation_owner() 的原始例外
（bare `raise`，不是包一層新訊息）——detail 永遠是「無權限存取其他業務的報價單」。
這句話只描述「擁有者」這一道，沒提 allow_module／allow_approver 兩個額外放行路徑。
🔑 但**能看到這句話的人，定義上已經同時不符合那兩個額外路徑**（guard_case_access
先試 module／approver，都不行才重新拋出原始例外）=> 訊息對「這個人」是準確的，
跟 ⑤（can_see_financial）同一個理由，不是缺陷。
```
✅ 13 個呼叫點（`allow_module` 各自傳不同模組：`case_manage` 共 11 處、
無 module 的 2 處）逐一核對過模組鍵確實存在於系統模組清單，沒有打錯字的那種。

**⚠️ 而這輪帶回一個新觀察，寫下來但不算 PX1 缺陷：**
```
_can_access_case() 的三種 detail（查看/修改/新增記錄）**都不提角色**，只講
「這張案件」—— 這種寫法反而**沒有 PX1 這類風險**（不會說錯角色，因為它沒說角色）。
🔑 對比 guard_case_access 那句「無權限存取其他業務的報價單」會暗示原因是
「你不是這個業務」——這在 90% 情況下是對的（純擁有者規則），但當使用者其實
是因為**缺了 case_manage 模組**才被擋（且不是任何業務的協作者）時，這句話會讓他
去找「業務歸屬」而不是去申請模組。**不算 PX1**（訊息沒有錯，守衛也沒有錯），
但值得記：**同一句 detail 服務兩種完全不同的失敗原因，會讓使用者去錯地方**。
這比較接近 EM8 第四種形狀（名字對但指向的協助路徑不對），不是這次的範圍，
只記錄不處理。
```

## ⇒ 兩輪都沒有正對照——給下一個人的建議

```
已排除的範圍：字面角色比較（75 處）／9 個角色名稱變體／8 支重複 _require_admin／
3 支重複 _guard_voucher／可 see_financial 家族／全部跨函式共用守衛（本輪）
還沒查的：101 個「守衛條件不明」裡，扣掉本輪讀過的共用守衛，剩下多半是
  ⓐ 401 登入態訊息（低機率，見 L3）
  ⓑ 業務邏輯條件式（例如 `stage == 1`、`old_tag == '已結案'`）包住的權限判斷，
    這類不是角色比較，是**狀態機**跟權限混在同一個 if 裡，要另一種判準才拆得開
```
若還要繼續查 `PX1`，ⓑ 是唯一還沒被這兩輪方法論覆蓋到的類別。
