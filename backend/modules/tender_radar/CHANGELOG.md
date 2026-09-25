# 標案雷達 更新紀錄

## 1.0.1 — 2026-09-25
- module.json 新增 `license_key: tender_radar`（CORE-SPEC §9c ② 模組授權；授權金鑰的 modules 清單寫這個值）

## 1.0.0 — 2026-09-25
- 模組化：自 `routers/tender_radar.py`、`helpers/tender_source.py`、`helpers/tender_match.py` 搬入 `modules/tender_radar/`（a150e52a）
- 三支通知信自 `helpers/email_notify.py` 移入 `notify.py`（967fe6b1）
- V9 之前的歷史見 `docs/quick/changelog*.md`（標案雷達自 2026-09-21 起）
