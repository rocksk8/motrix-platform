# 標案雷達 更新紀錄

## 1.1.0 — 2026-09-26
- 新增：三種通知信在模組載入時登記信件類型（標案雷達新標案＝業務；無法連線來源網站、來源網站格式異動＝系統技術，預設只寄超級管理員）
- 修改：通知信主旨改為【MOTRIX 系統通知】分類－事由，內文依事由、影響、建議處理、發送時間與來源；用語正式化

## 1.0.1 — 2026-09-25
- module.json 新增 `license_key: tender_radar`（CORE-SPEC §9c ② 模組授權；授權金鑰的 modules 清單寫這個值）

## 1.0.0 — 2026-09-25
- 模組化：自 `routers/tender_radar.py`、`helpers/tender_source.py`、`helpers/tender_match.py` 搬入 `modules/tender_radar/`（a150e52a）
- 三支通知信自 `helpers/email_notify.py` 移入 `notify.py`（967fe6b1）
- V9 之前的歷史見 `docs/quick/changelog*.md`（標案雷達自 2026-09-21 起）
