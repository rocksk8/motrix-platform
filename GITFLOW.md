# MOTRIX ERP — Git Flow 分支規則

> 建立日期：2026-07-22

---

## 分支架構

```
master   ─── 生產穩定版（只接受 develop merge 或 hotfix merge）
  │
  └── develop ─── 整合測試分支（日常開發的匯集點）
        │
        ├── feature/xxx   功能開發
        ├── fix/xxx       非緊急 bug 修復
        └── hotfix/xxx    生產緊急修復（直接從 master 開，merge 回 master + develop）
```

---

## 分支命名規則

| 類型 | 格式 | 範例 |
|------|------|------|
| 功能 | `feature/簡述` | `feature/dispatch-acceptance` |
| 修復 | `fix/簡述` | `fix/modal-flash` |
| 緊急 | `hotfix/簡述` | `hotfix/login-lockout` |

---

## 日常開發流程

### 新功能

```bash
# 1. 從 develop 開新分支
git checkout develop
git pull origin develop
git checkout -b feature/xxx

# 2. 開發 + commit（遵循 Conventional Commits）
git commit -m "feat: 功能說明"

# 3. 完成後 merge 回 develop
git checkout develop
git merge --no-ff feature/xxx
git branch -d feature/xxx
```

### 緊急修復（hotfix）

```bash
# 從 master 開
git checkout master
git checkout -b hotfix/xxx

# 修復後同時 merge 回 master 和 develop
git checkout master
git merge --no-ff hotfix/xxx

git checkout develop
git merge --no-ff hotfix/xxx

git branch -d hotfix/xxx
```

---

## 發布節奏（建議）

| 時間 | 動作 |
|------|------|
| 週四 17:00 | develop 功能凍結（不再 merge 新 feature） |
| 週四–週五 | 測試、修 fix/ 分支 |
| 週一 09:00 | develop → master merge，打版本 tag |

```bash
# 打 tag（格式：YYYY.MM.W，第幾週）
git tag -a 2026.07.4 -m "Sprint 1 release"
```

---

## Commit Message 規範（Conventional Commits）

```
<type>: <說明>（繁中或英文均可）

types:
  feat     新功能
  fix      錯誤修復
  chore    維護性工作（死碼清理、文件、設定）
  docs     文件更新
  refactor 重構（不改功能）
  test     新增/修改測試
  hotfix   生產緊急修復
```

範例：
```
feat: 承攬商驗收流程節點（DB v25）
fix: 修復報價清單 Modal 閃現問題
chore: 刪除 frontend/js/ 21 個死碼 JS 檔案
```

---

## 保護規則（人工遵守，無 GitHub Actions）

- **master** 不得直接 push 功能 commit；只接受 merge commit
- **master** 不得 `git push --force`
- 每次 merge 進 master 前確認 `test_core.py` 全數通過
- DB migration 必須附在同一個 commit，不得拆分

---

## 目前分支狀態

```
master  ← 生產（HEAD，已含 DB v25）
develop ← 整合測試（從 master 建立，同步至 HEAD）
```
