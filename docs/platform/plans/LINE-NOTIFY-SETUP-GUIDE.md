# LINE 通知設定教學（管理者用）

> 狀態：2026-11-11（T79 候選票）。畫面名稱以 LINE Developers Console 實際畫面為準；標「待確認」的項目要實際操作後回填。
> 對外網址已定：**`https://line.miactw.com`**（Cloudflare Tunnel；只開 `/api/line/callback` 這一條路徑）。

## 先講結論：要準備 3 樣東西，貼進系統設定頁

| 要貼的值 | 來自哪個 channel | 用途 |
|---|---|---|
| Channel access token（長效） | **Messaging API** channel（你已建好） | 系統用官方帳號的名義發訊息 |
| Channel ID | **LINE Login** channel（要新建） | 讓同仁按「綁定 LINE」登入授權 |
| Channel secret | **LINE Login** channel（要新建） | 系統向 LINE 換取使用者身分 |

為什麼要兩個 channel：Messaging API 只能「發訊息」，不知道某個同仁是誰；LINE Login 讓同仁自己授權一次，系統才會拿到「這個 LINE 帳號＝這位同仁」。

## ⚠️ 開始前最重要的一件事：Provider 必須是同一個

兩個 channel 必須放在**同一個 Provider** 底下，否則同一個人在兩邊的 userId 不一樣，發不出訊息。
**channel 建好之後不能搬 Provider**，建錯只能刪掉重建。

1. 開 <https://developers.line.biz/console/>，用建立官方帳號的 LINE 帳號登入。
2. 左側列出所有 Provider。點進**已經有 Messaging API channel 的那個 Provider**（裡面能看到你建好的 channel）。
3. 記住這個 Provider 名稱，下面新建 LINE Login channel 時一定要在**這個 Provider 裡**建。

## 步驟 A：取得 Messaging API 的 channel access token

1. 在該 Provider 裡點開 Messaging API channel。
2. 切到「Messaging API」分頁，拉到最下面的 **Channel access token (long-lived)** → 按「Issue」。
3. 複製那串字（很長）。**這串等於官方帳號的鑰匙，不要貼在群組或寄信**。直接貼到系統「通知設定 → LINE」的 token 欄位。
4. 按系統設定頁的「驗證」，看到官方帳號名稱就是對的。

## 步驟 B：建立 LINE Login channel

1. 同一個 Provider 頁面 → **Create a new channel** → 選 **LINE Login**。
2. 填寫：
   - Region：Taiwan
   - Channel name：例如「MOTRIX 通知綁定」（同仁授權時會看到這個名稱）
   - Channel description：例如「公司系統通知綁定」
   - App types：勾 **Web app**（不要勾 Mobile app）
   - Email address：填你的 email
3. 勾同意條款 → Create。

## 步驟 C：設定 LINE Login channel

1. **Basic settings** 分頁：複製 **Channel ID**、**Channel secret**，貼到系統設定頁。
2. 同一頁找 **Linked LINE Official Account**（待確認：位置在 Basic settings 或 LINE Login 分頁）→ 選你的官方帳號。這樣同仁授權時，LINE 會順便問「要不要加官方帳號為好友」。
   沒加好友就收不到通知，所以這步不要省。
3. **LINE Login** 分頁 → **Callback URL**：填 `https://line.miactw.com/api/line/callback`（**逐字相同**，不要多斜線、不要改路徑）。
   這個網址也會顯示在系統「通知設定 → LINE 通知」卡片的「對外網址」欄位下方，可直接複製。
   ⚠️ 路徑不能改：正式機 Tunnel 的 ingress 是精確比對 `/api/line/callback`，要改必須同步改正式機設定並重啟服務。
4. **Channel status 改成 Published**（頁面最上方，預設是 Developing）。
   Developing 狀態只有 channel 管理者與測試者能登入，一般同仁會被擋。**這是最常漏的一步。**

## 步驟 C2：把值貼進系統（最高管理者）

「通知設定 → LINE 通知」卡片：

1. Channel access token → 貼步驟 A 的值。
2. 對外網址 → `https://line.miactw.com`（只填網域，不含路徑）。
3. LINE Login 的 Channel ID／Channel secret → 貼步驟 C 的值。secret 存檔後只顯示圓點，不會再顯示原文，也不會出現在每日備份的 JSON。
4. 「LINE 訊息帶連結」**維持關閉**：它與「對外網址」是兩個獨立的開關。對外網址只是讓綁定時 LINE 能導回系統；訊息預設不帶任何連結。
5. 儲存 → 按「驗證 token」，看到官方帳號名稱與本月額度。
6. 勾選要同時發 LINE 的通知（預設全不發）。

> 開發機注意：開發機標記（`MOTRIX_EMAIL_SEND=off` 或 `.no_email_send`）會同時擋信件與 **LINE 推播**。「驗證 token」與額度查詢是唯讀（不發訊息、不耗額度），**刻意**不受開發機標記影響，讓部署前能先確認 token 對不對；不是漏掉。

## 步驟 D：官方帳號本身要檢查的設定

在 LINE Official Account Manager（<https://manager.line.biz/>）：

1. 「回應設定」：關閉「自動回應訊息」與「加入好友的歡迎訊息」，避免同仁加好友時收到行銷罐頭訊息（可依公司需要保留歡迎訊息）。
2. 「Messaging API」：確認已啟用（你建好 channel 時就會是啟用）。
3. **訊息額度**：免費方案每月有則數上限，推播給 N 個人算 N 則。系統設定頁驗證時會顯示本月已用／上限。額度用完時 LINE 會拒收，系統會記錄但不影響信件。

## 同仁如何綁定（電腦發起、手機授權）

1. 在**電腦**登入系統 → 「帳號安全」頁（改密碼那一頁）→ 「LINE 通知」卡片 → 按「綁定 LINE」。（管理者還沒設好 LINE Login 時，這張卡片不會出現。）
2. 電腦會顯示一個 QR。用**手機**的相機或 LINE 掃它 → LINE 授權畫面 → 同意 → 接著選「加入官方帳號為好友」。
3. 手機會顯示「綁定完成」；電腦上的卡片幾秒內自動變成「已綁定」，同時手機 LINE 會收到一則「通知已綁定完成」。
   - 電腦卡片若顯示紅字「已綁定，但測試訊息沒有送達」：多半是兩個 channel 不在同一個 Provider（見上方），請通知管理者。
4. QR 10 分鐘內有效、只能用一次；掃的人不需要登入系統——綁定的是**按下「綁定」那台電腦上登入的帳號**。電腦在授權完成前登出，綁定會失敗，重按一次即可。
5. 之後系統會依管理者勾選的事件，同時用 LINE 通知（收件人規則與 Email 完全相同，包含個人退訂）。想停止：同一張卡片按「解除綁定」。最高管理者可以替別人解除（例如換手機、離職）。刪除帳號時會一併解除。

系統只取得「這個 LINE 帳號的識別碼」，不取暱稱、頭像。

## 檢查清單（出問題時從上往下查）

- [ ] 兩個 channel 在同一個 Provider
- [ ] token 驗證成功（設定頁顯示官方帳號名稱）
- [ ] LINE Login channel 狀態是 **Published**
- [ ] Callback URL 與系統設定的網址**逐字相同**（`https://line.miactw.com/api/line/callback`，含 https、結尾有無斜線）
- [ ] 手機掃 QR 後卡在 LINE 的錯誤頁（redirect_uri 不符）⇒ 上一條沒對上；掃到系統的「連結無效／已逾時」⇒ 回電腦重按「綁定 LINE」
- [ ] 同仁已加官方帳號為好友（沒加、或封鎖了，推播會失敗）
- [ ] 本月額度還有
