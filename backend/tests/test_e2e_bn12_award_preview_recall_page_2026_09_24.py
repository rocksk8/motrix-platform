"""（已退役）test_e2e_bn12_award_preview_recall_page_2026_09_24.py：驗的全部是已停用的舊獎金流程，題已全部移除。"""

# ── 2026-09-24 移除（SPEC-BONUS §十一）───────────────────────────────────────
# 舊「獎金項目＋分潤單」流程停用：寫入端點回 410、bonus.html 改為以案件為中心的新頁面
# （使用者：「上一次開發的內容我無法接受」「重做成新流程」、舊單「舊的都是開發機測試用，直接作廢」）。
# 本檔下列題驗的是已停用的流程，已移除；新流程的題見 test_bonus_case_*_2026_09_24.py、
# test_e2e_bonus_case_page_2026_09_24.py、test_bonus_legacy_retired_2026_09_24.py。
# 移除：test_the_detail_window_previews_the_pdf_and_lets_the_requester_recall
# 同檔其餘題驗的是仍在運作的部分（讀取端點、群組、輔助函式），保留。
