# 抽查：A 的 analytics 派工連接器題依 M04 略過（wip/a-analytics-dispatch ef3b9f60）（D，2026-09-26 17:34）

> §G4 抽查，只改測試。主持要求確認：這 2 題是真的需要 M04 才略過，沒有遮掉 analytics 本身的問題；略過有寫明原因。

| 項目 | 結果 |
|---|---|
| 不加 skip、M04 不在（D2 刪 subcontract）⇒ 2 題為什麼紅 | `_live_dispatch_totals_by_quote` 回 None（無法檢查）⇒ `TypeError: 'NoneType' object is not subscriptable`；`staleSettlementCount` 是 None ⇒ `assert (None == 1)`。兩者都是「提供者不在」的**設計行為**，不是 analytics 的缺陷 |
| 那一側有沒有題驗 | 有：`test_without_the_dispatch_provider_the_check_says_it_could_not_run` 不 skip、照跑，M04 不在時也過 |
| 加 skip、M04 不在 | 2 passed、2 skipped；`-rs` 印出原因「外包工班（M04）不在這個安裝包：dispatch.row 提供者本來就不在」 |
| 加 skip、M04 在 | 4 passed，沒有 skip，也就是完整產品不會被略過 |
| 判準 | `module_installed("modules/subcontract/")` 看 module.json，符合 O-4 |

⇒ 通過、必修 0。
