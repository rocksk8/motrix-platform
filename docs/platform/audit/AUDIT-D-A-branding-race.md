# 抽查：設定頁品牌圖初次載入競態（wip/a-branding-race 28cc1854，基底 f04a245a）（D，2026-09-28）

- **結論：放行，無必修。**
- 修法：`company-profile-settings.html` 以代數 `brandGen` 判斷先後——上傳／恢復預設套用回應時 +1；`loadBranding` 送出時記下代數，回應到時代數已變就丟掉，不把預覽蓋回舊狀態（〈先渲染再非同步載入＝競態〉的標準做法）
- 新題以 init script 扣住初次 GET、等 PUT 完成後才放行（不靠時間），決定性重現
- D 在拋棄式 worktree 跑 `test_e2e_branding_2026_09_27.py`：3 過；突變 2 個全紅：
  - B1 拿掉代數比對 ⇒ 新題紅
  - B2 套用回應時不加代數 ⇒ 新題與原本偶發紅的 `test_settings_page_upload_and_reset` 都紅（等於退回原本的競態）
- 與 E4 段②同檔（設定頁）：A 回報 merge-tree 無衝突；合流時兩邊的 e2e 都要跑
