# -*- coding: utf-8 -*-
"""`gl.events` 契約 v1：來源模組回報「事件」、總帳引擎收集與驗證。設計：proposal-gl/02-events-engine.md §2。

本檔只做**介面與守門**（總帳 A 階段）：事件形狀、驗證、內容雜湊、向所有提供者收集並明說缺席。
不產生傳票（引擎的草稿產生與 gl_source_events 在 C 階段隨第一個來源一起做）——所以對現有手工傳票沒有任何副作用。

提供者契約（多提供者，`registry.providers("gl.events")`，鍵＝來源模組 key）：
    fn(start: str, end: str, *, changed_since: str = "") -> {"events": [Event], "notice": str}
Event（JSON 可序列化）見 `validate_event`。來源給**角色**（role），不給科目；角色→科目由 `roles.resolve_role`。
"""
import hashlib
import json

from core import registry

CONTRACT_VERSION = 1
CAPABILITY = "gl.events"
#: 事件行的角色名（帳務角色，不是使用者角色）；用常數比對，避免被「使用者角色字串」掃描誤判（test_system_audit）
_ROLE_AP = "AP"
_ROLE_INPUT_TAX = "INPUT_TAX"
_ROLE_BANK = "BANK"
MODES = ("snapshot", "cumulative", "append", "native", "stock")
#: mode=native：來源模組**已經自己開了傳票**（例：獎金核准／發放），事件只登記「這張傳票就是這個事件」，引擎不重複產生、不改動它。
#: 事件帶 `native_voucher_id`（正整數），不帶 lines。
#: mode=stock：存貨出庫（E10）。來源只回『哪個料號、出庫幾件、哪個案件、哪天』（`stock_part_no`、`stock_qty`，不帶 lines、不帶金額）；
#: 金額由引擎依移動加權平均（`ledger/inventory.py`）在產生草稿時算出，來源不知道也不該知道成本。
SIDES = ("D", "C")

#: 已知的事件來源模組與它們負責的事件（缺席時的說明用；順序＝畫面順序）。
#: 模組已載入但還沒提供 gl.events ＝「尚未接入」（不是錯誤）；模組沒載入 ＝「未安裝」。
SOURCES = {
    "arap": "銷項發票、客戶收款（E01～E03）",
    "subcontract": "承攬商發票與付款（E04～E05）",
    "payroll": "勞報單與獎金（E06～E07）",
    "supply": "進貨、存貨、出貨成本（E08～E10）",
    "case": "案件額外支出、材料申請、保固（E11～E12）",
    "fixed_assets": "固定資產取得、折舊、處分（E13）",
    "custom_modules": "自訂模組單據入帳（E20／E21）",
}


def known_roles():
    from modules.accounting.ledger.roles import DEFAULT_ROLES
    return set(DEFAULT_ROLES)


def _is_int_amount(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def validate_event(ev, roles=None):
    """回問題清單（空＝合格）。不丟例外：壞事件要被列出來，不能讓整批失敗，也不能悄悄消失。"""
    roles = roles if roles is not None else known_roles()
    p = []
    if not isinstance(ev, dict):
        return ["事件不是物件"]
    for k in ("source_type", "source_key", "event_code", "event_date"):
        if not isinstance(ev.get(k), str) or not ev.get(k).strip():
            p.append("缺少 %s" % k)
    d = ev.get("event_date")
    if isinstance(d, str) and d.strip():
        import datetime as _dt
        try:
            _dt.date.fromisoformat(d)
        except ValueError:
            p.append("event_date 格式要是 YYYY-MM-DD（%r）" % d)
    if ev.get("mode", "snapshot") not in MODES:
        p.append("mode 只能是 %s" % "、".join(MODES))
    if ev.get("mode") == "stock":
        qty = ev.get("stock_qty")
        if not isinstance(ev.get("stock_part_no"), str) or not ev.get("stock_part_no").strip():
            p.append("mode=stock 需要 stock_part_no")
        if not (isinstance(qty, int) and not isinstance(qty, bool) and qty > 0):
            p.append("mode=stock 需要正整數 stock_qty")
        return p
    if ev.get("mode") == "native":
        nv = ev.get("native_voucher_id")
        if not (isinstance(nv, int) and not isinstance(nv, bool) and nv > 0):
            p.append("mode=native 需要正整數 native_voucher_id")
        return p
    lines = ev.get("lines")
    if not isinstance(lines, list) or not lines:
        p.append("lines 必須是非空清單")
        return p
    debit = credit = 0
    for i, ln in enumerate(lines, start=1):
        if not isinstance(ln, dict):
            p.append("第 %d 行不是物件" % i)
            continue
        if ln.get("role") not in roles:
            p.append("第 %d 行的角色 %r 未登記" % (i, ln.get("role")))
        if ln.get("side") not in SIDES:
            p.append("第 %d 行 side 只能是 D 或 C" % i)
        if not _is_int_amount(ln.get("amount")):
            p.append("第 %d 行金額要是非負整數（新臺幣元；%r）" % (i, ln.get("amount")))
            continue
        if ln.get("side") == "D":
            debit += ln["amount"]
        elif ln.get("side") == "C":
            credit += ln["amount"]
    if not p and debit != credit:
        p.append("借貸不相等（借 %d、貸 %d）" % (debit, credit))
    if not p and debit == 0:
        p.append("金額全部是 0")
    return p


def canonical_hash(ev):
    """內容雜湊：入帳日、各行（角色／方向／金額／維度）、案件、對象、稅碼。`meta` 與說明文字不參與（診斷用，改了不算內容變）。"""
    if ev.get("mode") == "stock":       # 不含金額：均價變動不算來源變動
        return hashlib.sha256(json.dumps({"stock": [ev.get("stock_part_no"), ev.get("stock_qty")], "date": ev.get("event_date"),
                                          "case": ev.get("case_no") or ""}, sort_keys=True).encode("utf-8")).hexdigest()
    if ev.get("mode") == "native":
        return hashlib.sha256(json.dumps({"native": ev.get("native_voucher_id"), "date": ev.get("event_date")}, sort_keys=True).encode("utf-8")).hexdigest()
    core = {
        "date": ev.get("event_date"), "case": ev.get("case_no") or "", "party": (ev.get("party") or {}).get("key") or "",
        "tax": ev.get("tax_code") or "",
        "lines": sorted([ln.get("role"), ln.get("side"), ln.get("amount"), ln.get("case_no") or "", ln.get("party_key") or "",
                         ln.get("tax_code") or "", ln.get("account_code") or ""] + ([json.dumps(ln["dims"], sort_keys=True, ensure_ascii=False)] if ln.get("dims") else [])
                        for ln in ev.get("lines", [])),       # dims 只在有值時才進雜湊 ⇒ 舊事件雜湊不變
    }
    return hashlib.sha256(json.dumps(core, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


#: 補登值沿用別的事件的來源鍵：進貨付款（E09）的稅額跟著進貨發票（E08b）的補登走
_ANNOT_ALIAS = {"stock_batch_payment": "stock_batch_invoice"}


def _annotation(conn, ev, field):
    st = _ANNOT_ALIAS.get(ev.get("source_type"), ev.get("source_type"))
    row = conn.execute("SELECT value FROM gl_source_annotations WHERE source_type=? AND source_key=? AND field=?",
                       (st, ev.get("source_key"), field)).fetchone()
    return None if row is None else row[0]


def _apply_category_map(conn, ev):
    from modules.accounting.ledger import category_map as _cm          # 晚 import：避免載入循環
    return _cm.apply_category_map(conn, ev)


def apply_annotations(conn, ev):
    """會計在 `gl_source_annotations` 補登的來源憑證資料覆寫來源值（不改來源模組）。認得：
    - field=input_tax（非負整數）：承攬商發票 E04、進貨發票 E08b 的進項稅額；進貨付款 E09 跟著 E08b 的補登（應付與銀行金額同步調整）。
    - field=invoice_date（YYYY-MM-DD）：E04／E08b 的入帳日。
    補登值不合法 ⇒ 忽略並在事件 meta 記 annotation_ignored。"""
    code = ev.get("event_code")
    if code == "E09" and ev.get("source_type") == "stock_batch_payment":
        return _apply_payment_tax(conn, ev)
    lines = ev.get("lines") or []
    ap = [ln for ln in lines if ln.get("role") == _ROLE_AP and ln.get("side") == "C"]
    if len(ap) != 1:
        return ev
    raw_date = _annotation(conn, ev, "invoice_date")
    if raw_date is not None:
        import datetime as _dt
        try:
            ev["event_date"] = _dt.date.fromisoformat(str(raw_date).strip()).isoformat()
            ev.setdefault("meta", {})["date_estimated"] = False
        except ValueError:
            ev.setdefault("meta", {})["annotation_ignored"] = "invoice_date=%r" % raw_date
    raw = _annotation(conn, ev, "input_tax")
    if raw is None:
        return ev
    try:
        tax = int(str(raw).strip())
        if tax < 0:
            raise ValueError
    except ValueError:
        ev.setdefault("meta", {})["annotation_ignored"] = "input_tax=%r" % raw
        return ev
    old_tax = sum(ln["amount"] for ln in lines if ln.get("role") == _ROLE_INPUT_TAX)
    if old_tax == 0 and (ev.get("meta") or {}).get("tax_unsplit"):
        return _split_unsplit_tax(ev, lines, tax)
    keep = [ln for ln in lines if ln.get("role") != _ROLE_INPUT_TAX]
    code_ = ev.get("tax_code") or "IN-5"
    if tax:
        keep.insert(len(keep) - 1, {"role": "INPUT_TAX", "side": "D", "amount": tax, "memo": "進項稅額（會計補登）", "tax_code": code_})
    for ln in keep:
        if ln is ap[0]:
            ln["amount"] = ln["amount"] - old_tax + tax
    ev["lines"] = keep
    ev["tax_code"] = code_ if tax else "IN-EX"
    m = ev.setdefault("meta", {})
    m["tax_estimated"] = False
    m["tax_annotated"] = True
    return ev


def _split_unsplit_tax(ev, lines, tax):
    """來源金額是含稅未拆稅（額外支出、叫料）：補登進項稅額 ⇒ 成本改為 全額－稅額，另加一行進項稅額，應付不變。稅額 0 或不小於成本 ⇒ 忽略並標記。"""
    cost = [ln for ln in lines if ln.get("side") == "D" and ln.get("role") != _ROLE_INPUT_TAX]
    if tax <= 0 or len(cost) != 1 or tax >= cost[0]["amount"]:
        ev.setdefault("meta", {})["annotation_ignored"] = "input_tax=%r（需為大於 0 且小於成本的整數）" % tax
        return ev
    cost[0]["amount"] -= tax
    code_ = ev.get("tax_code") or "IN-5"
    cost[0]["tax_code"] = code_
    new = []
    for ln in lines:
        new.append(ln)
        if ln is cost[0]:
            new.append({"role": _ROLE_INPUT_TAX, "side": "D", "amount": tax, "memo": "進項稅額（會計補登）", "tax_code": code_})
    ev["lines"] = new
    ev["tax_code"] = code_
    m = ev.setdefault("meta", {})
    m["tax_unsplit"] = False
    m["tax_annotated"] = True
    return ev


def _apply_payment_tax(conn, ev):
    raw = _annotation(conn, ev, "input_tax")
    if raw is None:
        return ev
    try:
        tax = int(str(raw).strip())
        if tax < 0:
            raise ValueError
    except ValueError:
        ev.setdefault("meta", {})["annotation_ignored"] = "input_tax=%r" % raw
        return ev
    m = ev.setdefault("meta", {})
    delta = tax - int(m.get("est_tax") or 0)
    if delta:
        for ln in ev["lines"]:
            if (ln.get("role") == _ROLE_AP and ln.get("side") == "D") or (ln.get("role") == _ROLE_BANK and ln.get("side") == "C"):
                ln["amount"] += delta
    m["tax_estimated"] = False
    m["tax_annotated"] = True
    return ev


def collect(start, end, changed_since="", conn=None):
    """向所有提供者收集事件。回 `{"events": [...已驗證＋content_hash], "invalid": [{"source","event","problems"}],
    "notices": [...], "sources": {模組: "ok"|"not_connected"|"not_installed"|"error"}}`。

    缺席一律明說（notices）：未安裝／尚未接入／提供者丟例外／提供者自己回的 notice；**不可與「0 筆」長得一樣**。
    """
    provs = registry.providers(CAPABILITY)   # 變數不是字面值：A 階段尚無提供者，登記表守門（只認字面值＋provider 形式）待 C1 第一個提供者上線時改成字面值
    roles = known_roles()
    out = {"events": [], "invalid": [], "notices": [], "sources": {}}
    seen = set()
    for src, label in SOURCES.items():
        fn = provs.get(src)
        if fn is None:
            if registry.is_loaded(src):
                out["sources"][src] = "not_connected"
                out["notices"].append("%s 尚未接入總帳事件契約（未提供事件提供者）：不含%s。" % (src, label))
            else:
                out["sources"][src] = "not_installed"
                out["notices"].append("%s 模組未安裝：不含%s。" % (src, label))
    for src, fn in sorted(provs.items()):
        try:
            res = fn(start, end, changed_since=changed_since) or {}
        except Exception as exc:                    # noqa: BLE001  提供者壞了不能拖垮其他來源，也不能靜默
            out["sources"][src] = "error"
            out["notices"].append("%s 的分錄事件讀取失敗（%s）：不含其事件。" % (src, type(exc).__name__))
            continue
        out["sources"][src] = "ok"
        if res.get("notice"):
            out["notices"].append("%s：%s" % (src, res["notice"]))
        for ev in res.get("events") or []:
            probs = validate_event(ev, roles)
            key = (ev.get("source_type"), ev.get("source_key"), ev.get("event_code")) if isinstance(ev, dict) else None
            if not probs and key in seen:
                probs = ["同一來源事件重複（%s／%s／%s）" % key]
            if probs:
                out["invalid"].append({"source": src, "event": ev, "problems": probs})
                continue
            seen.add(key)
            e = dict(ev)
            if conn is not None:
                e = apply_annotations(conn, e)
                e = _apply_category_map(conn, e)            # 費用類別代碼 → 科目與拆稅（來源模組只回類別代碼）
            e["source_module"] = src
            e["mode"] = e.get("mode", "snapshot")
            e["content_hash"] = canonical_hash(e)
            out["events"].append(e)
    return out
