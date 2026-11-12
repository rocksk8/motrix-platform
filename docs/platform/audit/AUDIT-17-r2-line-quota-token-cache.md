# 獨立稽核 r2（delta）：LINE 額度快取綁 token 指紋（commit `0bbce3c73`）（獨立稽核者，MOTRIX-ERP 派工，2026-11-12）

> 稽核對象：`0bbce3c73`（parent `ba0336c79`；已在 `train/t80-int` 的 `e27fbf6eb` 裡）。只看這個 commit，不重跑 [AUDIT-17](AUDIT-17-heartbeat-line.md)。行號以 `e27fbf6eb` 為準。
> 範圍：`backend/helpers/line_quota.py`（+19/−5）、`tests/test_line_quota_2026_11_12.py`（+28/−2）、`tests/test_e2e_line_recipients_quota_2026_11_12.py`（+3）。
> 方法：讀碼＋跑單元測試＋**變異檢查 9 個**＋探針 P8–P11（存成 `AUDIT-17-r2-probe.py.txt`，用法見 §5）。**沒有跑 e2e**（見 §4）。沒有改任何產品程式碼；變異與探針都跑在我的 worktree，跑完已還原／刪除。

## 0. 結論

- **必修 0、建議 2、觀察 3。** 修法對根因：快取 entry 帶 token 指紋、讀之前先取指紋、`snapshot`／`after_push` 指紋不符就不採信，方向安全（讀到一半換 token ⇒ 寧可多讀一次，不會把舊結果當新 token 的快取）。
- 變異檢查：**核心防護有被守住（7/9 被殺）**，沒被守住的兩個都在「次要路徑」：`after_push` 的指紋判斷（M2）和「先取指紋再讀」的順序（M5）。
- 修法只管**行程記憶體快取**；**持久化的 `line_quota_state`（`alerted` 旗標）沒有綁 token**，換成另一個官方帳號後，舊帳號的已警示旗標會吃掉新帳號的首次告警（S-1，探針 P8 實測）。這不是這個 commit 引入的，但 commit 訊息把「換 token」當成要處理的情境，這一塊同一情境沒蓋到。

## 1. 實測

| 項目 | 驗證 | 結果 |
|---|---|---|
| 基準 | `test_line_quota_2026_11_12.py` 在 `e27fbf6eb`：**80 過 0 紅** | 成立 |
| 變異檢查 | 見 §2 表（9 個） | 7 殺、2 活 |
| 換 token 後的持久化狀態 | 探針 P8、P9 | **P8 紅（S-1）**；P9 紅但 UI 不呈現（O-1） |
| 讀途中換 token／換 token 後 `after_push` 延遲 | 探針 P10（現行碼綠）、P11（現行碼綠）；各自對應變異 M2、M5 時轉紅 | 現行碼正確，**但既有測試沒守** |
| `_fp` 是 private、沒動 L1 | commit 只動 3 個檔，`_fp` 無外部呼叫端（`grep _fp\(` 只在 `line_quota.py:139,177,262`） | 成立 |

## 2. 變異檢查（`test_line_quota_2026_11_12.py`，逐一改 `line_quota.py` 後跑、跑完還原）

| # | 變異（`line_quota.py`） | 結果 | 被誰殺 |
|---|---|---|---|
| M1 | `:177` snapshot 指紋判斷拿掉 | **殺** | `test_negative_cache_is_dropped_when_the_token_changes` |
| M1a | `:178` 只清 `failed_at`（不清 `at`） | **殺** | `test_positive_cache_is_dropped_when_the_token_changes` |
| M1b | `:178` 只清 `at`（不清 `failed_at`） | **殺** | `test_negative_cache_is_dropped_…` |
| M2 | `:262` `after_push` 的指紋判斷拿掉 | **活** | 無（80 過） |
| M3 | `:146` 失敗分支不寫 `fp` | **殺** | `test_failed_read_is_negatively_cached_for_a_minute_and_force_bypasses` |
| M4 | `:160` 成功分支不寫 `fp` | **殺** | `test_snapshot_uses_cache_within_max_age_and_refreshes_after` |
| M5 | `:139` 改成讀完才取指紋 | **活** | 無（80 過） |
| M6 | `_fp` 回常數 | **殺** | `test_negative_cache_is_dropped_…` |
| M7 | `_fp` 只分「有／沒有 token」 | **殺** | `test_positive_cache_is_dropped_…`（兩個新測試各管一種換法，分工乾淨） |

## 3. 發現

**S-1（建議，低）　持久化的額度狀態沒綁 token：換成另一個官方帳號後，舊帳號的 `alerted` 旗標吃掉新帳號首次告警**
- 位置：`line_quota.py:149-165`（`refresh` 讀 `prev=_state()` 後沿用 `prev["alerted"]`，只在換月或用量回落到「門檻−5 點」以下才清）。
- 重現（探針 P8）：A 帳號 85%（170/200）⇒ 寄 80% 警示、記 `alerted=[80]` ⇒ 換成 B 帳號 token（78%，156/200）⇒ `refresh` 後 `alerted` 仍是 `[80]`（78 ≥ 75，遲滯不清）⇒ B 到 80%（160/200）⇒ `check_and_alert` **不寄**（實測 `mails` 只有 1 封，應該 2 封）。
- 影響：只在「月中換官方帳號、且新帳號用量落在舊旗標的遲滯帶內」才發生；後果是少一封額度警示。範圍窄，所以列建議不列必修。
- 建議修法：state 裡存 `fp`，`refresh` 讀到 `prev.get("fp")` 存在且 ≠ 目前指紋時 `alerted = []`（`cmp_keys` 加 `fp`）；舊資料沒有 `fp` 就不動（避免上線後全部重寄）。⚠️ 這會把「token 的雜湊前 16 碼」寫進 `system_settings`——該表若進每日匯出／備份，請 PM 先決定是否可接受，或改存較短（8 碼）／HMAC。測試：P8 直接轉正式測試即可。

**S-2（建議，測試）　兩條次要路徑沒有測試守住：`after_push` 的指紋判斷（M2）、讀途中換 token 的順序（M5）**
- M2：換 token 後 `after_push` 若不看指紋，會沿用舊 token 的 `checked_at` 算延遲（最長多等 `CACHE_SECONDS`=300 秒才做推播後額度檢查）。只是延遲，不會讀到錯資料（`_run_after_push` 用 `force=True`），所以影響小，但這是 commit 明講「`snapshot`/`after_push` 都要認」的一半，現在沒有任何測試。
- M5：`:139` 的註解寫「讀之前先取指紋」是刻意的安全順序，順序反過來（讀完才取）會把舊 token 的結果標成新 token 的指紋 ⇒ 吃到過期快取。沒有測試守這個順序。
- 建議：把探針 P10（`after_push` 延遲＝`_SETTLE_SECONDS`）、P11（`_http` 第一個 GET 途中換 token ⇒ 下一次 `snapshot` 必須重讀）收進 `test_line_quota_2026_11_12.py`；實測 P10 殺 M2、P11 殺 M5。

**O-1（觀察）　讀不到新帳號用量時，API 回的 view 仍帶舊帳號的 `used`／`limit`（`ok=false`）**
- 位置：`line_quota.py:147`、`:183`（`_view(_state(), …, ok=False, …)`）。探針 P9：A 160/200 ⇒ 換 token ⇒ 新 token 讀失敗（401）⇒ view `ok=False` 但 `used=160 limit=200 percent=80.0 level=warn`。
- 現況：UI 在 `ok=false` 時只顯示錯誤文字、不畫用量條（`notification-settings.html:361`、`:368`），所以使用者看不到；只有直接打 `GET /api/settings/line-notify/quota` 的人看得到（需超管）。同 token 的失敗回「最後已知值」本來就是設計，這裡只是換 token 後語意變成別的帳號的數字。若採 S-1 的 `fp`，順手讓失敗時 `fp` 不符就回空 state 即可。

**O-2（觀察）　e2e 的 `_configure` 現在會重設行程內快取：e2e 綠燈不再證明這個修復**
- 位置：`test_e2e_line_recipients_quota_2026_11_12.py:39-41`。把快取清掉能讓 e2e 穩定，但閘門當時抓到的「負快取不認 token」就不再由 e2e 驗；修復是否有效完全靠 §2 那兩個單元測試（它們有守住，見 M1/M6/M7）。可以接受；建議放個 conftest 層級的 autouse 重設（同時涵蓋別的 e2e 檔），之後新增 e2e 就不用每檔各補一行。

**O-3（觀察）　`_fp()` 吞掉所有例外並回 `""`；`snapshot`／`after_push` 每次多一次 `system_settings` SELECT**
- `:54-55`：`_cfg()` 若丟例外 ⇒ `""` ⇒ 與「沒設 token」指紋相同。但那種情況 `line_notify.quota()`（`line_notify.py:488`）讀同一個 `_cfg()` 也會失敗，不會讀到舊帳號資料，所以不是洞。成本：`_get_setting`（`settings.py:19-33`）每次開 DB 連線；`snapshot` 本來就已讀 `_state()`＋`thresholds()` 兩次，多一次不改變量級。

## 4. 限制

- **沒跑 e2e**：`test_e2e_line_recipients_quota_2026_11_12.py` 要起伺服器＋瀏覽器，這次只讀碼（+3 行只是重設快取），沒驗證「閘門紅燈的原案例現在綠」；作者與 gate 已回報 231 過，我沒有獨立重現那個數字。
- 變異只做 `line_quota.py` 上與本 commit 直接相關的 9 個；沒對 `line_notify.py` 動手。
- P8 的「少一封警示」是在 mock 的 email 掛點上驗的（`notify_line_quota_warning` 被換掉），沒有實際寄信。

## 5. 重現

```bash
# worktree：D:\Claude-pm\audit-t80-notify（detached @ e27fbf6eb）；TEMP/TMP 要在 D:，--basetemp 必填（BK19）
cp docs/platform/audit/AUDIT-17-r2-probe.py.txt backend/tests/test_zz_audit17r2_probe.py
cd backend && TEMP='D:\Claude-pm\<tmp>' TMP='D:\Claude-pm\<tmp>' PYTHONUTF8=1 MOTRIX_TRAIN=1 \
  python -m pytest --basetemp='D:\Claude-pm\<tmp>\bt' -p no:cacheprovider -s tests/test_zz_audit17r2_probe.py
rm tests/test_zz_audit17r2_probe.py        # 探針洩漏守門：留著會讓下一次跑紅
# 預期（現行碼）：P8 紅、P9 紅（見 S-1／O-1）；P10、P11 綠
# 變異：把 §2 表的改動套到 helpers/line_quota.py，跑 tests/test_line_quota_2026_11_12.py，M2／M5 仍 80 過；
#       套 M2 後跑 P10 轉紅、套 M5 後跑 P11 轉紅
```

## 6. 處置建議

| 項 | 級別 | 建議 |
|---|---|---|
| S-1 | 建議（低） | r2 可順手修（state 存 fp、不符清 `alerted`），P8 轉正式測試；PM 先確認 fp 寫進 `system_settings` 可否接受 |
| S-2 | 建議（測試） | 收 P10、P11 進單元測試 |
| O-1～O-3 | 觀察 | 記錄即可（O-2 若要做，conftest 一處） |
