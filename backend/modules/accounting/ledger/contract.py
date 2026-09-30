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
MODES = ("snapshot", "cumulative", "append")
SIDES = ("D", "C")

#: 已知的事件來源模組與它們負責的事件（缺席時的說明用；順序＝畫面順序）。
#: 模組已載入但還沒提供 gl.events ＝「尚未接入」（不是錯誤）；模組沒載入 ＝「未安裝」。
SOURCES = {
    "arap": "銷項發票、客戶收款（E01～E03）",
    "subcontract": "承攬商發票與付款（E04～E05）",
    "payroll": "勞報單與獎金（E06～E07）",
    "supply": "進貨、存貨、出貨成本（E08～E10）",
    "case": "案件額外支出、叫料、保固（E11～E12）",
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
    core = {
        "date": ev.get("event_date"), "case": ev.get("case_no") or "", "party": (ev.get("party") or {}).get("key") or "",
        "tax": ev.get("tax_code") or "",
        "lines": sorted([ln.get("role"), ln.get("side"), ln.get("amount"), ln.get("case_no") or "", ln.get("party_key") or "",
                         ln.get("tax_code") or "", ln.get("account_code") or ""] for ln in ev.get("lines", [])),
    }
    return hashlib.sha256(json.dumps(core, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def apply_annotations(conn, ev):
    """會計在 `gl_source_annotations` 補登的來源憑證資料覆寫來源值（不改來源模組）。目前認得：field=input_tax（進項稅額整數）。
    只作用在同時有『借 INPUT_TAX 或無稅額』與『貸 AP』的事件（E04）；補登值不是非負整數 ⇒ 忽略並在 meta 記 annotation_ignored。"""
    row = conn.execute("SELECT value FROM gl_source_annotations WHERE source_type=? AND source_key=? AND field='input_tax'",
                       (ev.get("source_type"), ev.get("source_key"))).fetchone()
    if row is None:
        return ev
    lines = ev.get("lines") or []
    ap = [ln for ln in lines if ln.get("role") == "AP" and ln.get("side") == "C"]
    if len(ap) != 1:
        return ev
    try:
        tax = int(str(row[0]).strip())
        if tax < 0:
            raise ValueError
    except ValueError:
        ev.setdefault("meta", {})["annotation_ignored"] = "input_tax=%r" % row[0]
        return ev
    old_tax = sum(ln["amount"] for ln in lines if ln.get("role") == "INPUT_TAX")
    keep = [ln for ln in lines if ln.get("role") != "INPUT_TAX"]
    code = ev.get("tax_code") or "IN-5"
    if tax:
        keep.insert(len(keep) - 1, {"role": "INPUT_TAX", "side": "D", "amount": tax, "memo": "進項稅額（會計補登）", "tax_code": code})
    for ln in keep:
        if ln is ap[0]:
            ln["amount"] = ln["amount"] - old_tax + tax
    ev["lines"] = keep
    ev["tax_code"] = code if tax else "IN-EX"
    m = ev.setdefault("meta", {})
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
            e["source_module"] = src
            e["mode"] = e.get("mode", "snapshot")
            e["content_hash"] = canonical_hash(e)
            out["events"].append(e)
    return out
