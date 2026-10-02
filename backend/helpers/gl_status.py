# -*- coding: utf-8 -*-
"""[單位] helper:gl_status    [層] L1    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] MESSAGE, gl_posted_warning
[契約題] tests/test_gl_source_status_2026_09_30.py
[不變式] 只讀、吞例外；沒有總帳提供者（模組不在／旗標關）⇒ None（沒有總帳就沒有可提示的）；提示是**非阻擋**的，不影響寫入本身
[注意] 各來源模組的寫入端點用：修改已入帳來源前呼叫，成功後把文字放進回應的 `glWarning`，前端顯示 toast（MONEY-FLOWS §9 L3）

能力名 `gl.source_status`（accounting 提供，IP-106 暫定號）。L2 不互相 import：來源模組不直接讀總帳表。"""
import logging

_log = logging.getLogger(__name__)

MESSAGE = "此筆已入總帳{voucher}：修改後，總帳引擎下次執行時會產生沖轉草稿與新草稿（請通知會計）。"


def gl_posted_warning(conn, source_type, source_key, prefix=False):
    """該來源在總帳已入帳（已過帳／來源已變動未處理）⇒ 回一句提示文字；否則 None。"""
    try:
        from core import registry
        prov = registry.providers("gl.source_status").get("accounting")
        if prov is None:
            return None
        hits = prov(conn, source_type, source_key, prefix=prefix)
    except Exception:                                        # noqa: BLE001 — 提示失敗不可以擋住寫入
        _log.exception("gl.source_status 查詢失敗（%s／%s）", source_type, source_key)
        return None
    if not hits:
        return None
    nos = sorted({h["voucher_no"] for h in hits if h.get("voucher_no")})
    return MESSAGE.format(voucher="（傳票 %s）" % "、".join(nos[:3]) if nos else "")
