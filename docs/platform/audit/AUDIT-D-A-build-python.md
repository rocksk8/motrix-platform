# 稽核：建包挑 Python——專案 venv 優先（wip/a-build-python cc1fa03b）（D，2026-09-28 00:06）

> 輕量等級、讀碼優先。

## 0. 結論

- **必修 1（BP-M1）**。

## 1. 逐項

| 項目 | D 的驗證 | 結果 |
|---|---|---|
| 專案 venv 優先 | `Select-MotrixPython`：候選第一位是主工作樹的 `.venv312`（`MOTRIX_PROJECT_VENV` 可換），之後才是 PATH 上的 python／python3 與專案內常見 venv；合格＝import 得到＋`check_py_deps.py` 版本規格。題 `test_dry_run_picks_the_project_venv_first`；突變 BP1「專案 venv 不放進候選第一位」⇒ **紅** | 成立 |
| A 的說法：版本檢查擋不住 hermes venv | requirements 只寫下限，別的工具的 venv 也可能合格 ⇒ 真正修好的是順序。程式在「沒有專案 venv」「專案 venv 不合格」兩種情形都會印黃字提醒可能是別的工具的環境 | 成立 |
| `.venv312` 不存在時的後備 | `Get-ProjectVenvPython` 回 `$null` ⇒ 候選退回原本的清單、照樣逐一檢查；題 `test_dry_run_without_a_project_venv_falls_back_and_says_so`（指定不存在的 venv） | 成立 |
| 選中的路徑有印出 | `[環境] 測試將使用：$pyExe`（綠字），以及 `-WhichPython` 乾跑印 `WHICH_PYTHON=<路徑>` | 成立 |
| **選中的路徑寫進 deploy_manifest** | `deploy_manifest.json` 的 `env` 只有 `phys_cores`、`workers`、`priority`；**沒有 Python 路徑、版本、來源** | **不成立 ⇒ BP-M1** |
| 題 | `test_build_python_selection_2026_09_27.py` 8 過 | 成立 |

## 2. 發現

**BP-M1（必修）　deploy_manifest 沒有記錄建包用的 Python**
- 這次要修的問題就是「建包挑到別的工具的 venv 而沒人發現」。只印在建包畫面上，事後打開安裝包看不到當初用哪一支，正是 manifest 那段註解說的「答案要在產物裡，不在誰的記憶裡」。
- 修法：`env` 加 `python = {path, version, source: "project"|"fallback"}`（source 依 `$sel.Project` 與 `$pyExe` 是否相同），並補一題斷言 manifest 有這幾欄、而且 `source` 與實際挑選一致。

## 複核：wip/a-build-python-2 b86bc4c8（D，2026-09-28）

- BP-M1：`Get-PythonEnvRecord`（build_deploy_package.ps1:215）＝{path, version, source}，`deploy_manifest.json` 與 `build_history.jsonl` 的 env 都帶 `python = $pyEnv`（:1005／:1084），由 Step 2.5 同一個 `$sel` 算出；題 `test_env_record_matches_what_was_actually_picked`（path＝挑中的、version＝它自己回報的、source 與實際挑選一致，project／fallback 兩向）。拋棄式 worktree 跑 11 過。

### 關閉紀錄（標準格式，PLAYBOOK §E-6）

- ✅ BP-M1 關閉（b86bc4c8）——deploy_manifest／build_history 的 env.python 記錄挑中的直譯器路徑、版本、來源
