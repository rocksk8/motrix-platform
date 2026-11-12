# 獨立稽核：T80 心跳監控（heartbeat）＋LINE 通知收件人／額度（獨立稽核者，MOTRIX-ERP 派工，2026-11-12）

> 稽核對象：`train/t80-int` head `ffd4b8a90`（派工時的 head；官方閘門 `not_e2e` 還在 hichan-13 那邊重跑，**最終稽核 commit 另行通知後，本文件的行號要對一次**）。
> 範圍：`backend/heartbeat_job.py`＋`tests/test_heartbeat_watch_2026_11_11.py`（含 BK19 同類模式掃描）；`feat/line-recipient-quota`（`line_recipients.py`、`line_quota.py`、`line_notify.py`、`email_notify.py` 的 LINE 掛點、`routers/system.py` 的 `/api/settings/line-notify/*`／`/api/line/prefs*`、`notification-settings.html`、`change-password.html`）。
> 方法：讀碼＋跑既有測試＋寫臨時探針（探針存成 `AUDIT-17-heartbeat-line-probe.py.txt`，用法見 §5）。**沒有改任何產品程式碼；沒有跑變異檢查**（見 §4 限制）。
> 獨立性聲明：我沒有參與這幾個分支的開發與 K 審。行號以 `ffd4b8a90` 為準。

## 0. 結論

- **必修 0、建議 4、觀察 6。** 沒有發現 LINE 會送給「不該收的人」的路徑：收件人確實只縮不擴（呼叫端清單 ∩ 角色 ∩ 沒退訂 ∩ 已綁定），權限（超管才能改角色／額度／設定、個人只能改自己）與 fail-closed 都成立。
- 值得處理的是兩類「**說的和實際不一樣**」：
  1. **心跳**：`ext_unset`（沒設對外網址）每天只寫一次狀態檔，卻被「狀態檔陳舊」那條當壞狀態判，**2 小時後就升成 ERROR＋寄信，並說「心跳排程可能已停止」**（H-1）。測試的 `seen_at` 預設只差 1 小時，抓不到。
  2. **LINE**：個人頁「我要收的 LINE 通知」顯示勾選＝要收，但實際收不收還要看**有沒有 Email、有沒有退訂同一類 Email、信件收件覆寫**——三者交集的後兩項在畫面上完全看不到（L-1）。
- BK19 同類模式：`heartbeat_job` 同型的另兩支測試本來就先導向 tmp；唯一同型的產品檔是 `backup_job.py`，**目前沒有任何測試 import 它**。這次修補成立，沒有漏網（§1）。

## 1. 實測

| 項目 | 我的驗證 | 結果 |
|---|---|---|
| 既有測試（`ffd4b8a90`，`--basetemp` 在 D:） | `test_heartbeat_watch_2026_11_11`＋`test_heartbeat_https_ping_2026_11_11`＋`test_heartbeat_log_quiet_2026_09_30`＋`test_line_quota_2026_11_12`＋`test_line_recipients_2026_11_12`：**162 過 0 紅** | 成立 |
| BK19 修補（`ffd4b8a90`）本身 | 探針 P7：導向 tmp 後 import 再 pop，root logger 沒掛上該 handler、log 檔可立即刪除（Windows 無殘留 handle）。原因：pytest 下 root 已有 handler，`logging.basicConfig` 是 no-op，`RotatingFileHandler` 建出來就被回收 | 成立 |
| 同類模式掃描（模組層寫檔副作用） | `grep -rnE "^(os\.makedirs\|logging\.basicConfig\|…)"` 非測試碼只有 `backup_job.py:22-33`、`heartbeat_job.py:40-47`、`main.py:106`（只 basicConfig）。**測試端 import `heartbeat_job` 的 3 支（watch／https_ping／log_quiet）全都先 `monkeypatch paths.LOGS_DIR`**；沒有任何測試 import `backup_job` | 無漏網（§3 的建議是防再發） |
| 心跳判斷×寫入頻率 | 探針（§5-b）：`assess()` 對 `ext_unset` 的 `since=seen=3h` ⇒ `level=error alert=True`（H-1） | **發現** |
| LINE 三者交集 | 探針 P1–P6（見 §2 L-1～L-5） | 交集本身正確；顯示面有落差 |
| 寫入鎖 | `line_notify` 設定值只有三個寫入點（`set_event`、`set_event_roles`、`PUT /api/settings/line-notify`），**全部持同一把 `_lock`**；`line_prefs` 只有 `set_muted` 一個寫入點（自己的鎖）；`line_quota_state` 有 `_state_lock` | 成立 |
| 權限 | `/api/settings/line-notify*` 全部 `require_superadmin=True`；`/api/line/prefs*` 只讀寫呼叫者自己（`user["username"]`），沒有 username 參數 | 成立 |

## 2. 發現

**H-1（建議，應修）　`ext_unset` 被「狀態檔陳舊」誤判成排程停了，繞過 `EXT_UNSET_ALERT_HOURS`**
- `heartbeat_job.py:67-80`：`ok`／`ext_unset` 同屬「正常」，**同一天只寫第一筆**（狀態檔 `seen_at` 最多隔 24 小時）。
- `helpers/heartbeat_status.py:135`：`if status != "ok" and (now - seen) > max(BAD_GRACE_MINUTES*60, 2*3600)` ⇒ ERROR＋alert。`ext_unset` 不是 `ok`，所以**寫完 2 小時後就被當成壞狀態**，訊息是「心跳狀態檔已 N 小時沒有更新：心跳排程可能已停止執行」。
- 影響：沒設 `ping_url` 的機器（新安裝、未交付前、刻意不對外打卡），設定頁的「心跳監控狀態」卡片整天顯示「異常」；每日 08:00 檢查（`system_checks.py:327-361`）會寄「排程停了」的信給最高管理者——訊息是錯的（排程好好的），而且 24 小時門檻（`EXT_UNSET_ALERT_HOURS`）形同虛設。`local_down`／`ext_fail` 每小時寫一次，不受影響；`ok` 有自己的 26 小時門檻，也不受影響。
- 為何測試沒抓到：`test_heartbeat_watch_2026_11_11.py:95-99` 的 `_st("ext_unset", since_ago=3h)` 用預設 `seen_ago=1h`（:33），`since` 與 `seen_at` 被拆開；真實的 job 寫出來的是兩者相同。
- 重現：§5-b。建議：第 135 行條件改為 `status in ("local_down", "ext_fail")`（`ext_unset` 比照 `ok` 用 `OK_STALE_HOURS`）；補一題「`ext_unset` 且 `seen_at==since`＝8 小時前 ⇒ `alert False`、`level warn`」。

**L-1（建議）　個人頁「要收」≠ 真的會收：交集裡有兩項畫面看不到**
- 收件人來源是信件的收件漏斗（`email_notify.py:246-254`）：`active=1 AND email 非空` 且 `_pref_enabled(notification_muted, event)`；`send_registered` 取最終寄出信箱對應的帳號當 LINE 對象（`:999-1011`）。`line_recipients` 之後再縮一次。
- 探針實測（`approval_review_edit`，皆已綁定 LINE、角色被允許、沒在 LINE 退訂）：
  - **P1**：綁了 LINE 但**沒填 Email** ⇒ 永遠收不到 LINE（`GET /api/line/binding` 照樣顯示已綁定、`prefs` 照樣列出該類型）。
  - **P2**：在「通知偏好」退訂了**同一類 Email** ⇒ LINE 也停；`prefs_view()` 仍回 `enabled: True`（`line_recipients.py:114-122` 只看 `line_prefs`）。畫面上勾著、實際不來。
  - **P4**：超管把該類型的收件覆寫成 `superadmin_only` ⇒ 工程師實際不會收，但他的「我要收的 LINE 通知」仍列出該項。
- 這是 `line_recipients.py` 檔頭不變式①寫明的「只縮不擴」，**設計沒錯**；問題在畫面對使用者說了一半。`change-password.html:243` 的提示只說「Email 不受影響」，沒說反過來「Email 退訂會連 LINE 一起停」。
- 建議（擇一，由 PM 決定，不擋車）：(a) 個人頁加一行說明三個前提（有 Email、沒退訂同類 Email、在公司收件名單內）；(b) `prefs_view` 加 `emailMuted`／`hasEmail` 旗標，畫面對應灰顯並說原因。**不建議**改成「LINE 不看信件收件」——那會擴大收件人。

**L-2（建議）　警示：全部角色取消勾選＝事件靜默死亡，畫面沒有任何提示（P6）**
- `notification-settings.html:613-617`：最後一個角色被取消時送出 `roles: []`；`line_notify.event_enabled()` 仍是 `True`、類型勾選仍打勾、`set_event_roles` 回 ok。實際推播 0 則（探針 P6：`pushes: 0, event_enabled: True`）。
- 這是明文語意（`[]`＝沒有任何角色），也和「壞值 fail-closed」同一個結果，所以不算缺陷；但**使用者看不出來事件已等於關閉**。建議：全取消時顯示「沒有角色可收，這類 LINE 不會發出」，或直接禁止取消最後一個。

**L-3（觀察）　快速路徑與限制路徑對「停用帳號」不一致（P3）**
- `line_recipients.py:98-99`：沒有角色限制且沒人退訂 ⇒ 原樣回傳呼叫端清單（含停用者）；一旦有角色限制，`_role_of` 帶 `active=1`（:82）把停用者濾掉。同一個停用帳號，是否被濾取決於「有沒有人設了別的限制」。
- 目前**走不到**：唯一呼叫端 `send_registered` 的清單來自 `active=1` 的信件漏斗；檔頭不變式⑤也寫明了。列觀察，因為它是「靠呼叫端自律」的契約，之後若有第二個 `notify_users` 呼叫端（直接丟帳號）就會漏。
- 附帶：`routers/auth.py:1742-1762` `toggle_user_active` 停用帳號**不解除 LINE 綁定**（刪除帳號才會，`:1717-1722`）。停用者的 `line_links` 留著，重新啟用就自動恢復收 LINE——可能是想要的行為，但沒有文件記載。

**L-4（觀察）　刪帳號只清綁定，不清個人退訂；同名新帳號繼承舊退訂（P5）**
- `auth.py:1717-1722` 只呼叫 `unlink_user`；`line_prefs` 照 `line_recipients.py` 不變式⑥刻意不清。同名新帳號會繼承舊人的退訂（只會**少收**，不會多收，沒有安全影響）；新人的個人頁會看到某些類型是取消勾選且不知為何。
- 與綁定的處理（刪除即解除、理由寫在 `auth.py:1717` 註解「否則同名新帳號會繼承舊綁定」）不對稱。建議 `delete_user` 順手 `set_muted` 清空（量極小，一行）。

**L-5（觀察）　LINE Login 設定被移除後，已綁定者無法在個人頁退訂**
- `change-password.html:789`：`if (this.available) await this.loadPrefs()`；`available` 來自 `routers/system.py:2887`（要 LINE Login ID／secret／對外網址都在）。管理者之後清掉 LINE Login 設定，**已綁定者**仍收 LINE（只要 token 還在），個人頁卻不再載入／顯示勾選區（`:235` 還要 `prefs.length`）。
- 讀碼判斷，**未實際開瀏覽器驗證**。

**L-6（觀察）　舊入口 `notify_warranty_expiry` 沒有 LINE 掛點**
- `email_notify.py:1706-1723` 走 `_async_send`，不經 `send_registered`，所以即使 `warranty_expiry` 已列入 `WIRED_EVENTS`，走這個入口就不會發 LINE。現行每日檢查已改走 `_send_warranty_expiry`（:1726），而 `system_checks.py:21`、`case_deadlines.py:20`、`daily_tasks/api.py:25` 只是 import 沒呼叫（我 grep 不到呼叫處）。
- 建議在舊入口 docstring 補一句「不發 LINE」，或把舊入口刪掉（若確認沒人呼叫）。

**觀察（不編號）**
- **O-1** `line_links`（含 LINE userId）會進每日 JSON 匯出並鏡像到雲端（`archive.py:2249` 只挖 token 與 secret）。userId 單獨沒有用處（要搭 token 才能推），屬 T79 範圍、非本票；列出供 PM 知悉。
- **O-2** `line_quota.check_and_alert` 持 `_lock` 呼叫 `snapshot`（內含兩支各最多 10 秒的 LINE GET）；推播後的背景執行緒與每日備援同時進來時會互相等，不會死鎖（鎖序固定，檔頭⑨），只是備援最壞多等 20 秒。無需處理。

## 3. 心跳 BK19 與測試品質（`test_heartbeat_watch_2026_11_11.py`）

- **建議 4（防再發，低）**　三種寫法並存：本檔 `:283-304` 兩題內聯 `monkeypatch` 再 `sys.modules.pop`、`:343-351` 的 `_job()` 輔助函式，另兩支同型測試用 `yield` 的 `hb` fixture（`test_heartbeat_https_ping_2026_11_11.py:28-40`、`test_heartbeat_log_quiet_2026_09_30.py:15-29`）。本檔的 `sys.modules.pop("heartbeat_job", None)` 都在**題尾、不在 finally**（`:293、304、360、371、388、417`）：斷言失敗時模組（指著已刪除的 tmp 路徑）會留在 `sys.modules`；目前每題開頭都會先 pop，所以現在無害，但下一個忘了 pop 的人會吃到。建議把本檔也收成 `hb` fixture（`yield` 後 pop），三份寫法歸一。
- 若要鎖住「測試 import 會寫檔的 job 腳本前必須先導向 tmp」這條規則：可加一個掃描題（搜尋 tests 內 `import heartbeat_job`／`import backup_job`／`import_module("heartbeat_job"|"backup_job")`，該檔必須含 `LOGS_DIR`）。`backup_job.py` 目前無測試 import，鎖的是未來。

## 4. 限制

- **沒有做變異檢查**：交集邏輯的測試（`test_line_recipients_2026_11_12.py` 317 行、`test_line_quota_2026_11_12.py` 423 行）我只跑、沒有改壞程式碼看會不會紅；它們全綠不等於每條都有牙齒。H-1 就是一個「測試綠、但條件沒被問到」的例子。
- L-5 與 L-1 的畫面描述來自讀碼＋後端探針，沒有開瀏覽器。
- 探針對外呼叫一律換掉 `line_notify._http`／`email_notify._async_send`；沒有碰真實 LINE 或 SMTP。
- 稽核基準是 `ffd4b8a90`；`train/t80-int` 之後若再動這幾個檔，行號會位移。

## 5. 重現

**a. 既有測試（162 過）**

    cd <worktree>\backend
    $env:TEMP="D:\Claude-pm\<自己的暫存>"; $env:TMP=$env:TEMP; $env:PYTHONUTF8="1"
    <venv>\python.exe -m pytest tests/test_heartbeat_watch_2026_11_11.py tests/test_heartbeat_https_ping_2026_11_11.py tests/test_heartbeat_log_quiet_2026_09_30.py tests/test_line_quota_2026_11_12.py tests/test_line_recipients_2026_11_12.py -q -p no:cacheprovider --basetemp=$env:TEMP\motrix-pytest-audit-adhoc

（`TEMP` 要設在 D:，BK19 只放行 `tempfile.gettempdir()`；`--basetemp` 是本 repo 協定 §5-3 強制。）

**b. H-1（純 Python，不需 pytest）**

    cd <worktree>\backend
    python - <<'EOF'
    import sys; sys.path.insert(0, ".")
    from datetime import datetime, timedelta
    from helpers import heartbeat_status as hs
    N = datetime(2026, 11, 12, 8, 0, 0)
    f = lambda h: (N - timedelta(hours=h)).isoformat(timespec="seconds")
    for h in (1, 3, 8, 20):
        r = hs.assess(N, {"status": "ext_unset", "since": f(h), "seen_at": f(h), "scheme": "https", "local_ok_at": f(h), "ext_ok_at": ""})
        print(h, r["level"], r["alert"])
    EOF

實測輸出：`1 warn False`／`3 error True`／`8 error True`／`20 error True`。預期（修後）：四列都是 `warn False`（24 小時內）。

**c. L-1／L-2／L-3／L-4（探針 P1–P6）與 P7（BK19）**

    copy docs\platform\audit\AUDIT-17-heartbeat-line-probe.py.txt backend\tests\test_zz_audit17_probe.py
    <同 a 的環境> -m pytest tests/test_zz_audit17_probe.py -q -s -p no:cacheprovider --basetemp=...
    del backend\tests\test_zz_audit17_probe.py        # 探針會被 probe-leak 守門判紅，跑完要刪

實測輸出（節錄）：

    P1 targets: [U…01]  noemail uid: U…02                        ← 沒 Email 的綁定者沒收到
    P2 targets: [U…01]  prefs_view(muted): {'approval_review_edit': True}   ← 實際沒收、畫面仍「要收」
    P3 unrestricted: ['amy','eng']  restricted: ['eng']  still_linked: True
    P4 targets: [U…05]  eng prefs_view: ['approval_review_edit']  ← 只有超管收；工程師畫面仍列出
    P5 line_prefs after unlink: {'amy': ['approval_review_edit']}
    P6 pushes: 0  event_enabled: True
    P7 attached_to_root: 0  removable: True
    7 passed

## 6. 建議處置

| 項目 | 等級 | 建議 | 擋車？ |
|---|---|---|---|
| H-1 `ext_unset` 誤判 | 建議（應修，1 行＋1 題） | 改 `heartbeat_status.py:135` 條件並補題 | 否（只影響沒設 ping_url 的機器） |
| L-1 顯示面落差 | 建議 | 個人頁加說明或旗標灰顯（PM 決定） | 否 |
| L-2 全取消角色 | 建議 | 提示或禁止取消最後一個 | 否 |
| 測試歸一（§3） | 建議（低） | 收成 `hb` fixture＋try/finally | 否 |
| L-3～L-6、O-1、O-2 | 觀察 | 記錄；L-4 一行可順手 | 否 |
