# LINE 通知設定教學（管理者用）

> 狀態：草稿（2026-11-11，T79 候選票）。畫面名稱以 LINE Developers Console 實際畫面為準；標「待確認」的項目要實際操作後回填。
> 設計與範圍見同目錄 `LINE-NOTIFY-DESIGN.md`（寫完設計後補）。

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
3. **LINE Login** 分頁 → **Callback URL**：填 `https://（正式機對外網址）/api/line/callback`。
   待確認：網址由正式機網路現況決定（固定／動態 IP、是否能用憑證），確定後回填這一行。
4. **Channel status 改成 Published**（頁面最上方，預設是 Developing）。
   Developing 狀態只有 channel 管理者與測試者能登入，一般同仁會被擋。**這是最常漏的一步。**

## 步驟 D：官方帳號本身要檢查的設定

在 LINE Official Account Manager（<https://manager.line.biz/>）：

1. 「回應設定」：關閉「自動回應訊息」與「加入好友的歡迎訊息」，避免同仁加好友時收到行銷罐頭訊息（可依公司需要保留歡迎訊息）。
2. 「Messaging API」：確認已啟用（你建好 channel 時就會是啟用）。
3. **訊息額度**：免費方案每月有則數上限，推播給 N 個人算 N 則。系統設定頁驗證時會顯示本月已用／上限。額度用完時 LINE 會拒收，系統會記錄但不影響信件。

## 同仁如何綁定（系統完成後）

1. 登入系統 → 個人設定 → 「LINE 通知」→ 按「綁定 LINE」。
2. 跳到 LINE 授權畫面 → 同意 → 勾「加入官方帳號好友」→ 回到系統顯示「已綁定」。
3. 之後系統會依管理者勾選的事件，同時用 LINE 通知。想退訂：同一頁按「解除綁定」，或在通知偏好關閉個別事件。

## 檢查清單（出問題時從上往下查）

- [ ] 兩個 channel 在同一個 Provider
- [ ] token 驗證成功（設定頁顯示官方帳號名稱）
- [ ] LINE Login channel 狀態是 **Published**
- [ ] Callback URL 與系統設定的網址**逐字相同**（含 https、結尾有無斜線）
- [ ] 同仁已加官方帳號為好友（沒加、或封鎖了，推播會失敗）
- [ ] 本月額度還有
