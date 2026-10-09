# 最終系統驗證（W3）範本與用法

> 工具：`tools/platform/final_verify.py`（唯讀；只讀樹與回報資料夾的文字檔，不連正式機資料、不跑重閘門）。白名單：`tools/platform/final_verify_allow.json`。
> 測試：`backend/tests/platform/test_final_verify_tool.py`（合成小樹；每項各有正對照與反向控制）。

## 用法

```
# 列車最終樹（第 49 班）——Python 用 .venv312
python tools/platform/final_verify.py --root <樹> --tag T49 --md docs/platform/plans/FINAL-VERIFY-T49.md

# 套用到正式機之後（再跑一次，加正式機部署對照）
python tools/platform/final_verify.py --root <樹> --prod-report "G:\我的雲端硬碟\MOTRIX-交付\正式機回報" --baseline-ref prod/<短sha> --tag T49-prod --md docs/platform/plans/FINAL-VERIFY-T49-PROD.md
```
`--only V1,V3.2` 只跑指定項、`--skip V2.2` 略過；`--json` 機器可讀。結束碼：0＝沒有 FAIL（WARN 不擋）、1＝有 FAIL。

## 檢查項目

| 組 | 項目 | FAIL 的意思 |
|---|---|---|
| V1.1 | `CORE_VERSION` ＝ core CHANGELOG 最上面 ＝ G1 快照 `core_version`，且是正式版號 | 還有 `next` 佔位／三處不一致（列車沒取號或取號後沒重產快照） |
| V1.2 | 每個模組 `module.json version` ＝ 該模組 CHANGELOG 最上面版號 | 版號與紀錄脫節 |
| V1.3 | `version_manifest.json` 沒有 `next`、版號格式 `YYYY-MM-DD`＋字母、無重複 | 佔位沒定號 |
| V1.4 | `CURRENT_VERSION` ≥ `V9_BASELINE`，且 `db.py`／`core/upgrade.py` 兩處基準一致 | 升級基準錯位 |
| V1.5 | 全樹沒有殘留的 `## (next)`／`"version": "next"` | 有分支佔位沒被列車定號 |
| V2.1 | CACHE-INDEX 來源檔都存在；來源 commit 落後 ≤ 8（落後只 WARN） | 索引指向不存在的檔 |
| V2.2 | `regen_all.py --check`：dep_graph／UNIT-INDEX／test_map 是最新 | 產生檔過期（`python tools/platform/regen_all.py` 重產後提交） |
| V2.3a | KEEP 文件（根目錄、`docs/quick`、`docs/platform` 排除 archive／audit／windows）的 markdown 相對連結都指得到檔 | 有壞連結（修連結或移除） |
| V2.3b | 反引號寫的 repo 路徑存在（WARN：多半是歷史敘述或執行期檔案；白名單 `dangling_tick_patterns`） | 僅提示 |
| V2.4 | `docs/windows`、`docs/platform/archive` 的每個追蹤檔 `git check-attr export-ignore` ＝ set | 封存文件會被帶進出貨包 |
| V3.1 | `dep_scan.py --check-modules`：路由歸屬／`api_prefixes` ↔ `modules.json` | 路由沒人認領／前綴不一致 |
| V3.2a/b/c | `auth_middleware` 閘門在；公開 API 白名單 ⊆ `public_ok` 基準且都對得到路由；handler 自己沒有授權檢查的路由（WARN） | 新增公開路徑未登記／閘門被拿掉 |
| V3.3 | 前端字面的 `/api/…` 呼叫都對得到後端路由 | 懸空呼叫（前端打一支不存在的 API） |
| V3.4a/b | 被消費的提供者都有人宣告；宣告的名稱寫在 INTEGRATION-POINTS.md（後者 WARN） | IP 登錄不一致 |
| V3.5 | `module.json` 的 `provides.probes` 都對得到路由且在 `api_prefixes` 內 | 探針指向不存在的端點 |
| V4.1 | 沒有追蹤 `*.db`／`.pyc`／`__pycache__`／`*.log`／`*.bak`／`*.tmp` 等 | 不該進版控的檔進來了 |
| V4.2 | 根目錄追蹤檔都在 `root_files` 白名單 | 根目錄多了計畫外的檔 |
| V5.1–5.4 | （給 `--prod-report` 才跑）最新套用摘要 `status=success service=up exit=0`；部署 commit ＝ 基準；部署 `api_version` ＝ manifest 最新版號；`status\latest.json` 一致且 `errors` 為空 | 部署的不是這一版 |

## 總結範本（`--md` 輸出的骨架；人工在下方補『判斷』）

```
# 最終系統驗證 <T49>
> final_verify.py 產生；樹：<路徑>（HEAD <sha>）；時間：<時間>
**結論：PASS|FAIL**（PASS n／FAIL n／WARN n／SKIP n）
| 項目 | 結果 | 說明 |
...（每項一列）
## 需要人判斷的項目
- **V? …**（FAIL|WARN）：<原因>   ← 每一項寫：是否阻擋上線、處置、負責人
```

## 已知狀態（第 48 班樹 `9dcb24ce7` 實測）
- V1、V2.2、V2.4、V3.1–V3.5、V4、V5（對 `prod/e526a2ef`）全 PASS。
- **V2.3a FAIL**：`docs/quick/changelog.md` 第 1353 行的連結 `../../docs/UI-BACKLOG.md` 指向不存在的檔（文件清理後被移除）——要嘛恢復該檔、要嘛改文字。
- V2.1 WARN：`PLAYBOOK.md` 摘要落後 17 個 commit（重寫 CACHE-INDEX 該段即可）。
- V2.3b WARN：若干歷史敘述／執行期路徑（不阻擋）。
