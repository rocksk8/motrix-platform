# 抽查：B 的 O11——建立端逾時附請求時間線（wip/b-o11 55df4ed8）（D，2026-09-26 18:58）

> §G4 抽查，只加診斷。主持要求確認兩點：時間線附加段沒有外洩（比照 S2-S1）；診斷題的突變會紅。

## 0. 結論

- **必修 0、建議 1**。
- 注意本包的基底（origin/platform）**還沒有** S2-S1 的 `redact`（conftest 裡 `def redact` 0 處）。

## 1. 外洩（主持第 1 點）

D 把 `_create_diag` 原樣抽出來，餵含秘密的輸入：

| 段落 | 輸入 | 輸出 |
|---|---|---|
| 送出沒有回應的請求 | `uploads/a.jpg?pt=SECRETQ` | `GET /api/uploads/a.jpg`：**已去 query** |
| 存檔相關回應 | 本文 `{"token":"SECRETR","customer_name":"王小明"}` | **原樣印出前 120 字**（token 值與客戶名都在） |
| console（最後 10 筆） | `[log] Bearer SECRETC fetch /api/x?pt=SECRETC` | **原樣印出** |

- 結論：只有時間線本身做了遮蔽；回應本文與 console 沒有遮。
- 這一題有 `@pytest.mark.e2e`，所以**等 b-o5-s2-2（fd5af159）合回之後**，makereport 的 `redact` 會遮到 Bearer、`?pt=`、`"token":"…"` 這幾種已知形狀；但客戶名這類裸值仍會留下（同 O5S2-O3）。
- **建議 O11-S1**：
  - (a) 列車讓 b-o5-s2-2 先於或與本包同班合回；本包單獨先合的話，這段附加文字沒有任何遮蔽。
  - (b) 回應本文只取狀態碼與單號（例如 `quoteNo`），不要印本文前 120 字；console 行經過 `safe_url` 或 `redact` 再印。
  - (c) 診斷題補「query 值不可以出現」的斷言，見 §2 的 O11b。

## 2. 突變（主持第 2 點）

| # | 突變 | 結果 |
|---|---|---|
| O11a | `_create_diag` 回空字串 | 紅（`test_o11_create_diag_names_the_pending_request_and_the_post_result`） |
| O11b | 拿掉時間線的去 query（`u.split("?")[0]` ⇒ `u`） | **存活**：題目的輸入沒有帶 query |

⇒ 通過；建議 O11-S1。

## 3. O11-S1 複核：wip/b-o11-2 4bcde01b（主持升必修；D 19:16）

- 本包已疊在 b-o5-s2-2（fd5af159）上，帶進了 `redact`，建議 (a) 的合回順序問題解決。
- 修法：
  - 回應只印狀態碼＋單號（`MQ-\d{6}-\d+`）。
  - 網址只印路徑（去掉 query 與 fragment）。
  - console 與對話框先經過 `conftest.redact`。
  - 診斷題改用含 `?pt=`、`?q=`、Bearer、token、客戶名的輸入，斷言這些都不出現。
- D 用 §1 的同一組秘密輸入重測：SECRETQ、SECRETR、SECRETC、王小明 **全部 ok**。console 輸出變成 `Bearer *** fetch /api/x?pt=***`；回應只剩 `POST /api/quotations ⇒ 200`。
- 突變 3/3 紅（都是 `test_o11_create_diag_…`）：
  - O11c：不去 query（原本存活的 O11b 現在有題守）
  - O11d：console 不過 redact
  - O11e：改回印回應本文
- 限制（同 O5S2-O3）：對話框或 console 裡沒有鍵名的裸值（例如客戶名）`redact` 認不出來；本題的斷言也刻意沒有把對話框裡的「客戶丁」列入。

⇒ **O11-S1 關閉（4bcde01b）**。
