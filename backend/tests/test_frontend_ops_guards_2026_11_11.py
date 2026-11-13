# -*- coding: utf-8 -*-
"""正式機評估衍生的兩個前端守門（2026-11-11，T79 維運票）。靜態讀頁面原始碼。

① approval-queue.html 的「預覽」：勞報單（type=payslip）原本沒有 apiBase 分支，預覽落到
   `/api/quotations/PS-…/pdf-download` → 404＋audit `case.access_denied(not_found)`（正式機 4 筆，superadmin）。
   其他沒有 PDF 端點的類型（期間結帳、自訂紀錄／模組定義、已結案變更…）也會同樣落到報價單端點，所以改成白名單：
   只有「apiBase 對得到 PDF／預覽端點」的類型才顯示預覽鈕、才發請求。
② quotation-form.html：待審核／簽核中、非簽核人（最高管理者、申請人…）開著單，PUT 必 403（正式機 14 次，全是最高管理者），
   而自動存檔失敗是靜默的＝使用者以為存了。現在整張鎖唯讀＋橫幅（N7，使用者確認）。
"""
import re

from core.source_tree import page_file


def _read(name):
    return page_file(name).read_text(encoding="utf-8")


def _slice(text, start_marker, length=1800):
    i = text.index(start_marker)
    return text[i:i + length]


def test_approval_queue_preview_is_whitelisted_and_payslip_has_its_own_base():
    html = _read("approval-queue.html")
    base = _slice(html, "apiBase(item) {", 1600)
    base = base[:base.index("itemPathId")]         # 只取 apiBase 本體
    assert "item?.type === 'payslip'" in base and "'/api/payslips'" in base, "勞報單要有自己的 apiBase（/api/payslips）"
    has = _slice(html, "hasPreview(item) {", 500)
    has = has[:has.index("},")]                    # 只取這個函式本體
    types = set(re.findall(r"'([a-z_]+)'", has))
    # 白名單裡的每一種都必須在 apiBase 對得到端點（quotation 是預設分支）
    for t in types - {"quotation"}:
        assert f"item?.type === '{t}'" in base, f"hasPreview 放行了 {t}，但 apiBase 沒有對應端點"
    assert "payslip" in types and "quotation" in types
    # 沒有 PDF 端點的類型不在白名單
    for t in ("ledger_action", "custom_record", "custom_module_def", "case_change", "extra_expense"):
        assert t not in types, t
    # previewItem 一開始就用白名單擋；按鈕也用同一個判斷（不再各寫一份排除清單）
    assert "if (!this.hasPreview(item)) return" in _slice(html, "async previewItem(item) {", 300)
    assert 'x-show="hasPreview(selected)" @click="previewItem(selected)"' in html


def test_quotation_form_locks_every_non_approver_while_approval_pending():
    """N7：isApproverLocked() 對待審核／簽核中的非簽核人也成立（只有 unlocked 例外），所以 autoSave 最上面那道早退就擋得住；
    橫幅只給非簽核人。行為由 test_e2e_pending_readonly_for_non_approvers 驗，這裡只釘住判斷式沒被改回「只鎖簽核人」。"""
    html = _read("quotation-form.html")
    body = _slice(html, "isApproverLocked() {", 400)
    # V3.45：判斷式改成「!unlocked（任何人沒解鎖都鎖）||（當層簽核人且不是最高管理者）」——最高管理者解鎖後即使同時是當層簽核人也要能編輯
    assert "!this.unlocked" in body and "this.isCurrentTierApprover() && this.session.role !== 'superadmin'" in body, "非簽核人也要鎖（unlocked 才例外）；簽核人（非最高管理者）解鎖不了"
    ban = _slice(html, "pendingReadOnlyBanner() {", 300)
    assert "!this.isCurrentTierApprover()" in ban and "!this.unlocked" in ban
    auto = _slice(html, "autoSave() {", 1500)
    assert auto.index("this.isApproverLocked()") < auto.index("this.apiSave(")
