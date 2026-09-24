# -*- coding: utf-8 -*-
"""e2e helper：操作 `static/ui.js`（MotrixUI）的對話框與提示——取代 `page.on('dialog')`。

☠️ `page.on("dialog", lambda d: d.accept())` 的問題：
- 盲接：接到的是哪一個對話框、內容是什麼，題目不知道；多一個或少一個都照樣綠。
- 原生對話框會卡住整個分頁，題目只能事先掛好 handler，無法「看到了再決定」。

用法：
    from tests._ui_dialogs import answer_confirm, answer_prompt, expect_toast, forbid_native_dialogs
    forbid_native_dialogs(page)                 # 頁面若還在用 alert／confirm ⇒ 題目最後斷言會抓到
    page.click("button:has-text('刪除')")
    msg = answer_confirm(page, ok=True, expect="確定要刪除")   # 回傳對話框的訊息文字
    expect_toast(page, "已刪除")
"""
DIALOG = '[data-testid="ui-dialog"]'


def wait_dialog(page, kind=None, timeout=10000):
    """等對話框出現；`kind` ＝ 'confirm'／'prompt' 時一併檢查種類。回傳 Locator。"""
    sel = DIALOG + ('[data-kind="%s"]' % kind if kind else "")
    loc = page.locator(sel)
    loc.wait_for(state="visible", timeout=timeout)
    return loc


def _message(dlg):
    return dlg.locator(".mui-msg").inner_text().strip()


def answer_confirm(page, ok=True, expect=None, timeout=10000):
    """回答一個 MotrixUI.confirm()。`expect`：訊息必須包含的文字。回傳訊息文字。"""
    dlg = wait_dialog(page, "confirm", timeout)
    msg = _message(dlg)
    if expect is not None:
        assert expect in msg, "確認框的訊息不是預期的那一個：%r（預期包含 %r）" % (msg, expect)
    dlg.locator('[data-testid="ui-dialog-%s"]' % ("ok" if ok else "cancel")).click()
    dlg.wait_for(state="detached", timeout=timeout)
    return msg


def answer_prompt(page, value=None, expect=None, timeout=10000):
    """回答一個 MotrixUI.prompt()。`value=None` ⇒ 按取消；否則填入後按確定。回傳訊息文字。"""
    dlg = wait_dialog(page, "prompt", timeout)
    msg = _message(dlg)
    if expect is not None:
        assert expect in msg, "輸入框的訊息不是預期的那一個：%r（預期包含 %r）" % (msg, expect)
    if value is None:
        dlg.locator('[data-testid="ui-dialog-cancel"]').click()
    else:
        dlg.locator('[data-testid="ui-dialog-input"]').fill(value)
        dlg.locator('[data-testid="ui-dialog-ok"]').click()
    dlg.wait_for(state="detached", timeout=timeout)
    return msg


def expect_toast(page, text=None, kind=None, timeout=10000):
    """等一個提示出現（可指定文字包含、種類 ok／error／info）。回傳 Locator。"""
    sel = '[data-testid="ui-toast"]' + ('[data-kind="%s"]' % kind if kind else "")
    loc = page.locator(sel)
    if text is not None:
        loc = loc.filter(has_text=text)
    loc.first.wait_for(state="visible", timeout=timeout)
    return loc.first


def forbid_native_dialogs(page):
    """記下頁面彈出的原生對話框（並關掉它，免得卡住分頁）。回傳 list，題目最後斷言它是空的。"""
    seen = []

    def _on(d):
        seen.append((d.type, d.message))
        d.dismiss()
    page.on("dialog", _on)
    return seen
