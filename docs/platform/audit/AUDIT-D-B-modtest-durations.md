# 抽查：B 的 modtest --full 記最慢 30 題（wip/b-modtest-durations 5cbcd9b9）（D，2026-09-26 18:25）

| 項目 | 結果 |
|---|---|
| diff | `parse_durations` 解析 pytest 的 `--durations` 段；`slowest` 把兩段合併、由大到小取前 30，帶上段別；寫進 `full_results/<commit>.json` |
| `test_env_and_load_guards` | 51 過 |
| 突變 DU1：由大到小改成由小到大 | 紅（`test_run_full_records_the_slowest_with_stage`） |

⇒ 通過、必修 0。
