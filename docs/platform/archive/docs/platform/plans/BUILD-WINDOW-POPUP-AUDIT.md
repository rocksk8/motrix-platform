
## 5. 更新（2026-10-02 晚；wip/t33-nowindow-d7）：機制已重現、修法已做
- **重現（確定性）**：父行程用 `DETACHED_PROCESS` 啟動（＝沒有主控台，等同排程／某些背景啟動方式），其下的 python 子行程 `GetConsoleWindow()`＝5839050 且 `IsWindowVisible`＝True（**一個可見的主控台視窗**），連跑 3 次皆同；在父行程裡先 `nowindow.install()` 後 3 次皆為 0（無主控台視窗）。這就是「背景測試一直跳視窗」的機制。
- `window_probe` 的限制：git 之類只活幾十毫秒的子行程視窗輪詢常抓不到（本機實測 20 ms 間隔也只記到 1 個無關視窗），所以前後比較改用上面的確定性法；probe 仍適合抓「活得久」的視窗（Edge、測試中的瀏覽器、drill 的伺服器）。已加 `--interval`。
- 修法（與 a3 的 `tools/platform/nowindow.py` 共用一份，未另寫）：`backend/conftest.py` 安裝（pytest 與 xdist worker 全涵蓋）；`flaky_retry`、`build_test_reuse`、`modtest`、`build_preflight`、`core_only_rc`、`fail_stream` 與其餘 19 個 `tools/platform` CLI 入口安裝；`failfast` 是 pytest 外掛（在已安裝的行程內）列為豁免；Edge PDF 子行程補 `CREATE_NO_WINDOW`（`test_approval_no_freeze` 同步改）。
- 守門：`test_no_window_guard_2026_10_03.py`（AST 掃描＋正對照；拿掉任一工具入口的 install、或拿掉 conftest 的 install 都會紅——已做突變）＋機制題（DETACHED 父行程下子行程無主控台視窗）。
- 已單檔跑：failfast 10、fail_stream 15、build_stage_reuse 12、build_opt 46、env_and_load_guards 62、apply_plan 52、deploy_dashboard_health_facts 4、scope_gate 103、nowindow 4、no_window_guard 5、approval_no_freeze 14，全綠。未跑全量。
- 注意：安裝是「本行程之後的所有 Popen」；子行程再起的行程由該程式自己負責（apply_*.ps1 已 `-WindowStyle Hidden`）。要看視窗除錯：`MOTRIX_SHOW_WINDOWS=1`。
