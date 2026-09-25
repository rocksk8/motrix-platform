"""（已退役）test_bonus_award_export_watermark_2026_09_23.py：驗的全部是已停用的舊獎金流程，題已全部移除。"""

# ── 2026-09-24 移除（SPEC-BONUS §十一）───────────────────────────────────────
# 舊「獎金項目＋分潤單」流程停用：寫入端點回 410、bonus.html 改為以案件為中心的新頁面
# （使用者：「上一次開發的內容我無法接受」「重做成新流程」、舊單「舊的都是開發機測試用，直接作廢」）。
# 本檔下列題驗的是已停用的流程，已移除；新流程的題見 test_bonus_case_*_2026_09_24.py、
# test_e2e_bonus_case_page_2026_09_24.py、test_bonus_legacy_retired_2026_09_24.py。
# 移除：test_bn13_a_voided_award_export_pdf_has_the_void_watermark、test_bn13_an_approved_not_voided_award_export_has_no_watermark
# 同檔其餘題驗的是仍在運作的部分（讀取端點、群組、輔助函式），保留。
