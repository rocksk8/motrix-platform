# -*- coding: utf-8 -*-
"""正式機評估衍生的兩個前端守門（2026-11-11，T79 維運票）。靜態讀頁面原始碼。

① approval-queue.html 的「預覽」：勞報單（type=payslip）原本沒有 apiBase 分支，預覽落到
   `/api/quotations/PS-…/pdf-download` → 404＋audit `case.access_denied(not_found)`（正式機 4 筆，superadmin）。
   其他沒有 PDF 端點的類型（期間結帳、自訂紀錄／模組定義、已結案變更…）也會同樣落到報價單端點，所以改成白名單：
   只有「apiBase 對得到 PDF／預覽端點」的類型才顯示預覽鈕、才發請求。
② quotation-form.html 的自動存檔：待審核／簽核中、且不是簽核人／複查編輯／解鎖編輯時，PUT 必 403（正式機 14 次，全是最高管理者），
   而自動存檔失敗是靜默的＝使用者以為存了。不送請求、提醒一次。
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


def test_quotation_form_autosave_does_not_put_while_approval_pending():
    html = _read("quotation-form.html")
    body = _slice(html, "autoSave() {", 2200)
    guard = body.index("this.q.status === '待審核' || this.q.status === '簽核中'")
    put = body.index("this.apiSave(")
    assert guard < put, "待審核／簽核中的守門必須在 apiSave 之前（不能先送再看結果）"
    assert "!this.unlocked" in body[guard:put] and "return" in body[guard:put]
    # 原本的兩道早退仍在
    assert "this.isApproverLocked()" in body[:guard] and "this.reviewEditing" in body[:guard]
