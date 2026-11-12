# Cloudflare 登入限流設定指南（motrix-platform.miactw.com）

> 給使用者自己在 Cloudflare 後台操作的步驟。產出日期 2026-11-12（外網登入強化票）。
> 做不做、做了會不會影響使用，都不影響系統本身的登入防護：程式裡已經有「每個來源 IP 錯 5 次鎖 15 分鐘」與「同一個帳號錯 10 次／30 分鐘鎖外網登入」，
> Cloudflare 這一條是**再多一道、在請求進到我們電腦之前就擋掉**的防線。

## 先講結論

| 項目 | 免費方案能做的（Cloudflare 官方文件，2026-11-12 查證） |
|---|---|
| 可建立的限流規則數 | **1 條**（Pro 2 條、Business 5 條） |
| 計算時間窗（period） | **只有 10 秒**（Pro 最長 1 分鐘、Business 最長 10 分鐘） |
| 用什麼來分辨「同一個人」 | **來源 IP**（免費方案只有這一個選項） |
| 被觸發後的處置時間 | **10 秒**（免費方案不能自己選更長） |
| 動作 | 封鎖（Block）；也可以選「受管質詢（Managed Challenge）」，但質詢型動作不能指定持續時間 |

所以免費方案的限流是「擋瞬間狂打」，不是「擋慢慢猜」——慢慢猜是程式裡的 IP 鎖定／帳號鎖定／兩步驟驗證在擋。
**只有 1 條規則**，因此下面這一條規則把「登入相關的 POST」一次涵蓋。

資料來源：<https://developers.cloudflare.com/waf/rate-limiting-rules/>（Availability 表）與 <https://developers.cloudflare.com/waf/rate-limiting-rules/parameters/>。
Cloudflare 會改版面與方案內容；下面的選單名稱如果和你看到的不同，以「Security（安全性）→ WAF／Security rules → Rate limiting rules（限流規則）」為準，找不到就依畫面上的關鍵字（Rate limiting）。
如果你的方案實際可選的值和這裡寫的不一樣，**以畫面上能選的為準**，原則是「時間窗選最小、次數抓寬鬆」。

## 規則怎麼訂

- 只管：網域 `motrix-platform.miactw.com`、**POST** 方法、路徑以 `/api/auth/login` 或 `/api/auth/webauthn/login` 開頭
  （涵蓋密碼登入 `/api/auth/login`、驗證碼 `/api/auth/login/totp`、手機核准 `/api/auth/login/qr-approve`、Passkey 登入 `/api/auth/webauthn/login/begin|complete`）。
- 為什麼不是整個 `/api/auth/*`：登出（`/api/auth/logout`）、個人設定等也在這底下，正常使用就會常常呼叫；手機掃碼登入時電腦每 2 秒查一次狀態（GET，不在規則內）。
  把範圍縮在「登入」就不會誤傷。如果你仍想涵蓋整個 `/api/auth/*`，把門檻調到 30 次以上即可。
- 門檻：**同一個 IP 在 10 秒內超過 10 次** ⇒ 封鎖 10 秒。
  - 正常使用：一次登入 1～3 個請求（密碼、驗證碼、Passkey 各一個）。
  - 公司辦公室的所有人從外網網址登入時，對 Cloudflare 來說是**同一個 IP**（公司對外 IP）。10 次／10 秒對早上同時有幾個人登入已經很寬鬆；真的被擋也只有 10 秒，重試就好。
- 動作：**Block（封鎖）**。免費方案的 10 秒處置時間固定，選 Block 最單純；選 Managed Challenge 也可以（對真人較友善，但程式化的登入 API 呼叫無法通過質詢，等同擋掉）。

## 操作步驟

1. 用瀏覽器登入 <https://dash.cloudflare.com>，選擇網域 **miactw.com**。
2. 左邊選單：**Security（安全性）→ WAF**（新版畫面可能叫 **Security rules**），切到 **Rate limiting rules（限流規則）** 分頁，按 **Create rule（建立規則）**。
   - 如果畫面要你選規則類型，選 **Rate limiting rule**。
3. **Rule name（規則名稱）**：`MOTRIX 登入限流`。
4. **If incoming requests match…（如果請求符合…）**，用「Edit expression（編輯運算式）」最不容易填錯：按 **Edit expression**，貼上下面整段：

   ```
   (http.host eq "motrix-platform.miactw.com" and http.request.method eq "POST" and (starts_with(http.request.uri.path, "/api/auth/login") or starts_with(http.request.uri.path, "/api/auth/webauthn/login")))
   ```

   想用點選的方式填也可以，三個條件都要用 **And** 連起來：
   - Hostname **equals** `motrix-platform.miactw.com`
   - Request Method **equals** `POST`
   - URI Path **starts with** `/api/auth/login` **Or** URI Path **starts with** `/api/auth/webauthn/login`
5. **With the same characteristics（用什麼特徵分辨同一個人）**：選 **IP**（免費方案只有這個）。
6. **When rate exceeds…（超過多少速率）**：
   - **Requests（請求數）**：`10`
   - **Period（時間窗）**：`10 seconds`（免費方案只有這個選項）
7. **Then take action…（觸發後的動作）**：
   - **Choose action（動作）**：`Block`
   - **Duration（持續時間）**：`10 seconds`（免費方案固定）
   - **Block response（回應）**：維持預設（會回 429，畫面是 Cloudflare 的 1015 頁面）即可。
8. 其他選項保持預設，按 **Deploy（部署）**。規則立即生效（通常幾秒內）。

## 確認有生效、而且沒誤傷

1. 正常登入一次（用你自己的帳號，從外網網址 `https://motrix-platform.miactw.com`），確認可以登入。
2. 在 Cloudflare：**Security（安全性）→ Events（事件）**，篩選「Service = Rate limiting」。部署後如果看到你自己被擋的紀錄，代表門檻太低，回到規則把 `10` 調大（例如 20）。
3. （選做）要親自驗證會擋：用**手機網路（不是公司 Wi-Fi）**，在瀏覽器快速連按登入按鈕 12 次以上，會看到 Cloudflare 的「Error 1015」頁面（不是我們系統的訊息）；10 秒後恢復。
   ⚠ 不要在公司網路做這個測試：程式裡的 IP 鎖定會把公司對外 IP 鎖 15 分鐘（2026-11-12 風險評估測試時就發生過一次），影響同事外網登入。內網登入不受影響。

## 事後怎麼調整／關掉

- 想暫時關閉：Rate limiting rules 清單裡，把這條規則的開關切成 **Disabled（停用）**；不要刪，之後可以再開。
- 被擋住但你確定是正常使用：把 `10` 調大即可（時間窗在免費方案固定 10 秒）。
- 單一帳號被亂試而鎖住：超級管理員可以在系統內（`GET /api/auth/account-locks`、`POST /api/auth/account-locks/unlock`）手動解鎖；
  本人在公司內網成功登入一次也會自動解除。

## 更強的下一步（選擇性，不是這次要做的）

免費方案的限流很粗（10 秒窗），擋不了「慢慢猜」。真正能把外網登入頁整個擋在前面的是 **Cloudflare Access**（Zero Trust，免費方案有人數上限，
可限定特定 Email／一次性驗證碼才看得到登入頁）。要不要做是另一個決策，風險評估報告的建議第 3 點已提過；先把這份限流做好，再評估。
