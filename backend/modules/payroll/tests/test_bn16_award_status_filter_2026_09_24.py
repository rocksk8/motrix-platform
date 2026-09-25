"""（已退役）test_bn16_award_status_filter_2026_09_24.py：驗的全部是已停用的舊獎金流程，題已全部移除。"""

# ── 2026-09-24 移除（SPEC-BONUS §十一）───────────────────────────────────────
# 舊「獎金項目＋分潤單」流程停用：寫入端點回 410、bonus.html 改為以案件為中心的新頁面
# （使用者：「上一次開發的內容我無法接受」「重做成新流程」、舊單「舊的都是開發機測試用，直接作廢」）。
# 本檔下列題驗的是已停用的流程，已移除；新流程的題見 test_bonus_case_*_2026_09_24.py、
# test_e2e_bonus_case_page_2026_09_24.py、test_bonus_legacy_retired_2026_09_24.py。
# 移除：test_bn16_counts_and_lists_come_from_the_same_array、test_bn16_marking_paid_moves_the_award_to_the_paid_tab、test_bn16_pending_holds_both_pending_statuses、test_bn16_the_page_fetches_the_award_list_exactly_once、test_bn16_voided_awards_are_hidden_until_asked_for
# 同檔其餘題驗的是仍在運作的部分（讀取端點、群組、輔助函式），保留。
