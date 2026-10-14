# -*- coding: utf-8 -*-
"""通知信內文預設逸出（2026-10-14，04 稽核；b4 指派「既有信件的資安補強」）。

規則：`email_notify._build_html` 把所有文字欄位當純文字逸出（& < > " '）；呼叫端刻意傳入的 HTML 要包成 `_safe()`，且其中的使用者資料自己 `_esc()`。

黃金題（對每一支寄信函式）：
  A. **純文字、不含 & < > " ' 的資料 ⇒ 寄出的主旨與內文與逸出前（舊版 `_build_html`）逐位元相同**——包含刻意帶標記的那幾支（回報修改前後、憑證、備份、磁碟、標案、模組異動…）。
  B. 每個使用者欄位帶 `<b>名稱&'</b>` ⇒ 內文沒有未逸出的那一串，且逸出後的那一串出現在內文（欄位有出現在信裡的話）。
  C. 刻意帶標記的版面（<b>、<br>、<code>、<span>、<strong>）在 B 的資料下仍保留標記。
主旨（純文字）不逸出。
"""
import datetime as _dt
import inspect

import pytest

from helpers import email_notify as EN

#: 舊版（逸出前）`_build_html`，原樣保留作比對基準。
_LEGACY_SRC = '''
def _legacy_build_html(mail_key, title, badge_text, badge_color, rows, quote_no, base_url,
                       note="", intro="", button_text="前往系統查看", impact=None, action=None):
    t = EN._mt.get(mail_key)
    impact = impact if impact is not None else (t.impact if t else "")
    action = action if action is not None else (t.action if t else "")
    row_html = "".join(
        f'<div class="lbl">{k}</div><div class="val">{v}</div>'
        for k, v in rows
    )
    reason = intro or title
    note_html  = f'<div class="note">{note}</div>' if note else ""
    link = f"{base_url}/pages/quotation-form.html?no={quote_no}" if quote_no else base_url
    sent_at = EN.datetime.now().strftime("%Y-%m-%d %H:%M")
    source = "MOTRIX 系統（%s）／信件類型：%s" % (base_url, t.name if t else mail_key)

    def _sec(label, body):
        return (f'<div class="lbl" style="margin-top:14px;font-weight:700">{label}</div>'
                f'<div class="val">{body}</div>') if body else ""
    return (
        f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="UTF-8">'
        f'<style>{EN._STYLE}</style></head><body><div class="card">'
        f'<div style="font-size:18px;font-weight:700;color:#1a1a1a;margin-bottom:16px;">'
        f'{title} <span class="badge" style="background:{badge_color}">{badge_text}</span></div>'
        f'{_sec("事由", reason)}{row_html}{note_html}'
        f'{_sec("影響", impact)}{_sec("建議處理", action)}'
        f'{_sec("發送時間與來源", sent_at + "　" + source)}'
        f'<a href="{link}" class="btn" style="display:inline-block;margin-top:22px;padding:10px 22px;background:#1D4ED8;color:#ffffff !important;border-radius:7px;text-decoration:none;font-size:14px;font-weight:600">{button_text}</a>'
        f'<div class="foot">本郵件由 MOTRIX 系統自動發送，請勿直接回覆。'
        f'如有疑問，請聯絡系統管理員。</div>'
        f'</div></body></html>'
    )
'''
_ns = {"EN": EN}
exec(_LEGACY_SRC, _ns)                                  # noqa: S102  測試基準
legacy_build_html = _ns["_legacy_build_html"]

_DATEISH = ("date", "not_after", "since")


class _Clock(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return _dt.datetime(2026, 10, 14, 9, 0)


def _tok(name, evil):
    return "<b>%s&'</b>" % name if evil else "T_%s" % name


def _args(fn, evil, variant):
    sig = inspect.signature(fn)
    out = {}
    for n, p in sig.parameters.items():
        ann = p.annotation
        if n in variant:
            out[n] = variant[n]
        elif n == "changes":
            out[n] = [{"label": _tok("l", evil), "old": _tok("o", evil), "new": _tok("n", evil)}]
        elif n == "stale":
            out[n] = [(_tok("stale_label", evil), None), (_tok("stale_label2", evil), _dt.datetime(2026, 10, 10, 9, 0))]
        elif n == "problems":
            out[n] = [{"label": _tok("plabel", evil), "path": _tok("ppath", evil), "free_gb": 1.5, "total_gb": 10, "free_pct": 15}]
        elif n == "temp_bloat":
            out[n] = [{"name": _tok("bname", evil), "path": _tok("bpath", evil), "gb": 2}]
        elif n == "tenders":
            out[n] = [{"name": _tok("tname", evil), "org": _tok("torg", evil), "location": _tok("tloc", evil), "procurement_type": _tok("tpt", evil),
                       "tender_method": _tok("ttm", evil), "budget": 100, "deadline": "2026-12-31"}]
        elif n in ("reasons", "watch_names"):
            out[n] = [_tok(n, evil)]
        elif n in ("approver_usernames", "assignee_usernames", "supervisor_usernames", "cashier_usernames", "usernames", "approver_names", "pending_usernames", "reviewer_usernames"):
            out[n] = ["u"]
        elif ann is bytes or n.endswith("_bytes"):
            out[n] = b"x"
        elif n in ("tier_no", "total_tiers", "days_left", "days_elapsed", "days_overdue", "days_since_update", "task_id", "case_id", "version", "department_id", "threshold_hours"):
            out[n] = 3
        elif n == "temp_total_gb":
            out[n] = 1.5
        elif ann is bool or p.default is False:
            out[n] = False
        elif any(d in n for d in _DATEISH):
            out[n] = "2026-10-20"
        elif n == "period_str":
            out[n] = "2026-09"
        elif n in ("page_path",):
            out[n] = "quotations.html"
        elif n == "audience":
            out[n] = "admins"
        elif p.default is not inspect.Parameter.empty and ann is str and p.default == "":
            out[n] = _tok(n, evil)
        else:
            out[n] = _tok(n, evil)
    return out


#: 每支函式要跑的版本（涵蓋不同分支的版面）
_VARIANTS = {
    "notify_daily_task_completed": [{}, {"is_edit": True}],
    "notify_cert_expiry": [{"is_acme": True}, {"is_acme": False}],
    "notify_bonus_correction_approved": [{"needs_payout": True}, {"needs_payout": False}],
    "notify_disk_space_low": [{}, {"problems": [], "temp_total_gb": 3.5}],
    "notify_module_activity": [{}, {"detail": "第一行\n第二行"}],
}
_SKIP = {"notify_monthly_report"}      # 附件與收件人由另一組設定決定；版面沿用 _build_html，另題覆蓋


def _all_notifiers():
    out = []
    for n, f in inspect.getmembers(EN, inspect.isfunction):
        if n.startswith("notify_") and n not in _SKIP:
            out.append((n, f))
    try:
        from modules.accounting import notify as AN
        out += [("accounting." + n, f) for n, f in inspect.getmembers(AN, inspect.isfunction) if n.startswith("notify_")]
    except Exception:                                                # noqa: BLE001
        pass
    try:
        from modules.tender_radar import notify as TN
        out += [("tender." + n, f) for n, f in inspect.getmembers(TN, inspect.isfunction) if n.startswith("notify_")]
    except Exception:                                                # noqa: BLE001
        pass
    return out


def _install(monkeypatch, sink, build):
    for nm in ("_users_emails", "_custom_emails", "_group_emails", "_finance_audience_emails", "_admin_emails", "_lookup_emails",
               "_superadmin_emails", "_monthly_report_recipient_emails", "_department_manager_emails"):
        monkeypatch.setattr(EN, nm, lambda *a, **k: ["a@example.com"])
    monkeypatch.setattr(EN, "_base_url", lambda: "https://x.example")
    monkeypatch.setattr(EN, "datetime", _Clock)
    monkeypatch.setattr(EN, "_build_html", build)

    def cap(to, subject, html, *rest):
        sink.append((subject, html))
        return EN.SEND_SENT
    monkeypatch.setattr(EN, "_async_send", cap)
    monkeypatch.setattr(EN, "_send_raising", cap)
    monkeypatch.setattr(EN, "_send", cap)
    monkeypatch.setattr(EN, "_send_with_attachments", cap)

    class _T:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self.t, self.a, self.k = target, args, kwargs or {}

        def start(self):
            self.t(*self.a, **self.k)
    monkeypatch.setattr(EN.threading, "Thread", _T)


def _render(monkeypatch, name, fn, evil, build, variant):
    sink = []
    _install(monkeypatch, sink, build)
    # 其他模組以 `_en._build_html` 屬性存取，上面已換；以防萬一，模組內若 import 了別名也換掉
    try:
        fn(**_args(fn, evil, variant))
    except TypeError:
        raise
    return sink


CASES = [(n, f, i, v) for n, f in _all_notifiers() for i, v in enumerate(_VARIANTS.get(n.split(".")[-1], [{}]))]


@pytest.mark.parametrize("name,fn,idx,variant", CASES, ids=["%s#%d" % (c[0], c[2]) for c in CASES])
def test_plain_data_is_byte_identical_to_the_unescaped_version(monkeypatch, name, fn, idx, variant):
    new = _render(monkeypatch, name, fn, False, EN.__dict__["_build_html"], variant)
    monkeypatch.undo()
    old = _render(monkeypatch, name, fn, False, legacy_build_html, variant)
    assert new, "沒有寄出任何信（測試資料不足？）：" + name
    assert new == old, name


@pytest.mark.parametrize("name,fn,idx,variant", CASES, ids=["%s#%d" % (c[0], c[2]) for c in CASES])
def test_special_characters_in_every_user_field_are_escaped(monkeypatch, name, fn, idx, variant):
    plain = _render(monkeypatch, name, fn, False, EN.__dict__["_build_html"], variant)
    monkeypatch.undo()
    evil = _render(monkeypatch, name, fn, True, EN.__dict__["_build_html"], variant)
    assert evil and plain
    names = [n for n in inspect.signature(fn).parameters] + ["l", "o", "n", "stale_label", "stale_label2", "plabel", "ppath", "bname", "bpath",
                                                             "tname", "torg", "tloc", "tpt", "ttm", "reasons", "watch_names"]
    for (_s1, html_plain), (_s2, html_evil) in zip(plain, evil):
        for n in names:
            if "T_%s" % n not in html_plain:
                continue                                           # 這個欄位沒有進內文（只進主旨或不顯示）
            raw = "<b>%s&'</b>" % n
            assert raw not in html_evil, "%s 的欄位 %s 沒有逸出" % (name, n)
            assert "&lt;b&gt;%s&amp;&#x27;&lt;/b&gt;" % n in html_evil, "%s 的欄位 %s 逸出後的字串沒有出現在內文" % (name, n)
