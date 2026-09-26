# -*- coding: utf-8 -*-
"""`AS3` 完整性守門：`APPROVAL_DOC_TYPES` 裡每一個有 submit 端點的 type，
兩支簽核佇列端點（`GET /api/approval-queue`、`GET /api/approval-queue/count`）
是不是都涵蓋到。

## 座標

`docs/windows/STATE.md` §236。A-2 查 `BN8` 時撞到的：`vouchers.py:486` 送審、
`APPROVAL_DOC_TYPES` 第八個就是 `voucher`（`AS2` 已落地），而兩支佇列端點裡
`vouchers_all` 命中 **0** —— 送審端點對、簽核端點對，而沒有人知道有單在等。
〈兩個都對而路不存在〉。

## ☠️ 既有 `test_approval_queue_badge_consistency_2026_09_15.py` 抓不到這一種

它驗的是「對它自己種的那組資料，count == 佇列裡 canApprove 為真的項目數」——
那是**一致性**守門，不是**完整性**守門。一個型別若兩邊都沒有，兩邊都回 0，
`0 == 0`，綠。這支補的是那個洞：直接數「這個型別出現在源碼裡了嗎」，
不靠任何一邊算出來的數字。

## ⚙️ 正對照

拿掉一個 type（`doc_types` 參數塞一個沒登記過的假名字，或用 `queue_source`／
`count_source` 餵一段不含那個字面值的原始碼），這支必須把它報出來。
`voucher` 在這支寫成之前就會被抓到——那是預期的，不是誤報。

## 用法

    cd backend && python tools/check_approval_queue_coverage.py
    python tools/check_approval_queue_coverage.py --selfcheck

或當函式庫用：`check_approval_queue_coverage(doc_types=[...])`——`doc_types`／
`queue_source`／`count_source` 留空時分別讀真正的 `APPROVAL_DOC_TYPES`／
`routers/quotations.py` 的兩支端點原始碼，測試可以三個都自己傳，不必
monkeypatch 任何模組屬性。
"""
import ast
import io
import os
import sys


def say(text):
    """這台機器的主控台是 cp932，emoji 印不出來會整支崩潰（同 check_double_init.py）。"""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"))


_TOOLS_DIR     = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR   = os.path.dirname(_TOOLS_DIR)
_QUOTATIONS_PY = os.path.join(_BACKEND_DIR, "routers", "quotations.py")

#: doc_type（`APPROVAL_DOC_TYPES` 用的鍵）-> (佇列 `type` 欄位的字面值,
#: count 端點 SQL 裡的資料表名)。兩者不是同一組字串
#: （`shipping`/`shipping_note`、`completion`/`completion_note`），
#: 這張表就是那個翻譯。
#: ⚠️ **它本身不是被信任的來源**——下面的函式會拿它去跟兩支端點的原始碼
#:    **核對**，不會只憑這張表說「有」（那樣它自己就是
#:    〈寬鬆驗證會靜默丟掉欄位〉那一種：一張手寫清單，沒人逼它跟著源碼走）。
_QUEUE_TYPE_FOR_DOC_TYPE = {
    "quotation":          ("quotation",         "quotations"),
    "shipping":           ("shipping_note",      "shipping_notes"),
    "invoice_voucher":    ("invoice_voucher",    "invoice_vouchers"),
    "payment_request":    ("payment_request",    "payment_requests"),
    "contractor_voucher": ("contractor_voucher", "contractor_payment_vouchers"),
    "extra_expense":      ("extra_expense",      "case_extra_expenses"),
    "completion":         ("completion_note",    "completion_notes"),
    "voucher":            ("voucher",            "vouchers_all"),
    "bonus":              ("bonus_award",        "bonus_awards"),
}


#: 送審單據類型 → 擁有它的 L2 模組（`modules/<key>/`）。模組不在這個安裝包 ⇒ 那一類「不適用」（它的單不存在），
#: 不算漏掉（稽核 D AP-M1：列車 core-only／真刪時，覆蓋檢查掃不到已拿掉模組的提供者）。不在表上的類型屬 L1 或 M01。
_OWNER_MODULE = {
    "contractor_voucher": "subcontract",
    "invoice_voucher":    "arap",
    "payment_request":    "arap",
    "bonus":              "payroll",
}


def _module_installed(key, backend_dir=None):
    """看 module.json（不看資料夾：拿掉模組後殘留的 __pycache__ 會讓資料夾還在）。"""
    return os.path.isfile(os.path.join(backend_dir or _BACKEND_DIR, "modules", key, "module.json"))


def _default_doc_types():
    """真的 `APPROVAL_DOC_TYPES`（CLI 用；測試應該自己傳 `doc_types`，
    不必靠這支去 import 或 monkeypatch）。"""
    if _BACKEND_DIR not in sys.path:
        sys.path.insert(0, _BACKEND_DIR)
    import helpers.tiered_approval as ta
    return list(ta.APPROVAL_DOC_TYPES)


def _func_body_text(source, func_name):
    """`source` 裡指名函式的原始碼片段（含字串常數，找不到回空字串）。"""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
           and node.name == func_name:
            return ast.get_source_segment(source, node) or ""
    return ""


def _provider_sources(backend_dir=None):
    """`approval.queue_items` 提供者的函式原始碼（M01-PLAN §3-7：單據模組自己提供待簽項目，M01 只彙整）。

    靜態找兩種登記寫法（不 import 任何模組）：
    - `registry.provide("approval.queue_items", "<名>", fn)` ⇒ 同檔的 `def fn`
    - ModuleSpec 的 `providers={("approval.queue_items", "<名>"): mod.fn}` ⇒ 同一個模組套件裡 `mod.py`（或 `api/mod.py`）的 `def fn`
    回傳 [(標籤, 原始碼), …]。"""
    backend_dir = backend_dir or _BACKEND_DIR
    files = {}
    for root, dirs, names in os.walk(backend_dir):
        dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__", "tools", "node_modules")]
        for n in names:
            if n.endswith(".py"):
                path = os.path.join(root, n)
                with io.open(path, encoding="utf-8") as f:
                    files[path] = f.read()

    def _def_in(path, name):
        src = files.get(path)
        return _func_body_text(src, name) if src else ""

    out = []
    for path, src in files.items():
        if "approval.queue_items" not in src:
            continue
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Call) and len(node.args) >= 3 \
               and isinstance(node.args[0], ast.Constant) and node.args[0].value == "approval.queue_items" \
               and isinstance(node.args[2], ast.Name):
                out.append((os.path.relpath(path, backend_dir), _def_in(path, node.args[2].id)))
            elif isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Tuple) and k.elts and isinstance(k.elts[0], ast.Constant) \
                       and k.elts[0].value == "approval.queue_items" \
                       and isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name):
                        pkg = os.path.dirname(path)
                        for cand in (os.path.join(pkg, v.value.id + ".py"),
                                     os.path.join(pkg, "api", v.value.id + ".py")):
                            if cand in files:
                                out.append((os.path.relpath(cand, backend_dir), _def_in(cand, v.attr)))
    return out


def _has_literal(src, lit):
    return ('"%s"' % lit) in src or ("'%s'" % lit) in src


def check_approval_queue_coverage(doc_types=None, queue_source=None,
                                  count_source=None, provider_sources=None, installed=None):
    """回傳一個 dict，三個鍵在完全涵蓋時都應該是空 list：

    ```
    missing_from_map    doc_type 沒有登記在 _QUEUE_TYPE_FOR_DOC_TYPE
    missing_from_queue  登記了，而 get_approval_queue() 源碼與任何 `approval.queue_items`
                         提供者都找不到那個 type 字面值
    missing_from_count  登記了，而 get_approval_queue_count() 源碼裡找不到那個資料表名，
                         也不是「提供者列出、count 端點彙整提供者」
    ```
    `provider_sources`：[(標籤, 原始碼)]；留空讀真的登記處（`_provider_sources()`）。提供者的項目同時餵兩支端點，
    所以提供者型別在 count 端看的是「count 端點呼叫 `_queue_provider_items(`」＋提供者源碼裡有那張表。
    `installed`：`fn(module_key) -> bool`；留空看 `modules/<key>/module.json`。擁有模組不在的類型列在
    `not_applicable`（{doc_type: 原因}），不算漏掉。
    """
    if provider_sources is None:
        provider_sources = _provider_sources()
    if installed is None:
        installed = _module_installed
    not_applicable = {}
    if doc_types is None:
        doc_types = _default_doc_types()
    if queue_source is None or count_source is None:
        with io.open(_QUOTATIONS_PY, encoding="utf-8") as f:
            src = f.read()
        if queue_source is None:
            queue_source = _func_body_text(src, "get_approval_queue")
        if count_source is None:
            count_source = _func_body_text(src, "get_approval_queue_count")

    missing_from_map, missing_from_queue, missing_from_count = [], [], []
    for dt in doc_types:
        owner = _OWNER_MODULE.get(dt)
        if owner and not installed(owner):
            not_applicable[dt] = "擁有模組 %s 不在這個安裝包（它的單據不存在）" % owner
            continue
        mapping = _QUEUE_TYPE_FOR_DOC_TYPE.get(dt)
        if mapping is None:
            missing_from_map.append(dt)
            continue
        type_literal, table_name = mapping
        owners = [src for _lbl, src in provider_sources if _has_literal(src, type_literal)]
        if not (_has_literal(queue_source, type_literal) or owners):
            missing_from_queue.append(dt)
        via_provider = "_queue_provider_items(" in count_source and any(table_name in src for src in owners)
        if not (table_name in count_source or via_provider):
            missing_from_count.append(dt)

    return {
        "missing_from_map":   sorted(missing_from_map),
        "missing_from_queue": sorted(missing_from_queue),
        "missing_from_count": sorted(missing_from_count),
        "not_applicable":     not_applicable,
    }


def is_clean(result):
    return not (result["missing_from_map"] or result["missing_from_queue"]
                or result["missing_from_count"])


def _self_check():
    """正對照＋負對照：拿掉一個 type 必須紅，涵蓋到的型別不可以被誤報。"""
    bad = 0

    # ① 完全沒登記的假型別 —— missing_from_map 必須抓到它。
    r = check_approval_queue_coverage(doc_types=["quotation", "__fake_type__"])
    if "__fake_type__" not in r["missing_from_map"]:
        say("   NG  正對照(1)：完全沒登記的型別沒有被抓到 => 這支尺本身壞了")
        bad += 1
    else:
        say("   OK  正對照(1)：完全沒登記的型別被抓到")

    # ② 登記了、但兩支端點源碼裡都沒有那個字面值 —— 餵一段空白源碼，
    #    不必真的去改 quotations.py。
    r = check_approval_queue_coverage(
        doc_types=["voucher"], queue_source="def f():\n    pass\n",
        count_source="def g():\n    pass\n", provider_sources=[])
    if "voucher" not in r["missing_from_queue"] or "voucher" not in r["missing_from_count"]:
        say("   NG  正對照(2)：空白源碼沒有被判定為漏掉 => 這支尺本身壞了")
        bad += 1
    else:
        say("   OK  正對照(2)：空白源碼被判定為兩邊都漏掉")

    # ③ 負對照：涵蓋到的型別不可以被誤報成漏掉。
    r = check_approval_queue_coverage(
        doc_types=["quotation"],
        queue_source='items.append({"type": "quotation"})',
        count_source="SELECT 1 FROM quotations")
    if r["missing_from_queue"] or r["missing_from_count"]:
        say("   NG  負對照：涵蓋到的型別被誤報成漏掉")
        bad += 1
    else:
        say("   OK  負對照：涵蓋到的型別沒有被誤報")

    # ④ 對真正的源碼跑一次，確認掃描機制本身讀得到函式（不是永遠回空字串
    #    因而每一項都判成「漏掉」的假陽性）。
    real = check_approval_queue_coverage(doc_types=["quotation"])
    if real["missing_from_queue"] or real["missing_from_count"]:
        say("   NG  對真源碼掃描：quotation 型別本身被判成漏掉，"
            "掃描機制可能讀不到函式內容")
        bad += 1
    else:
        say("   OK  對真源碼掃描：quotation 型別（一定存在的那個）沒有被誤報")

    return bad


def main():
    args = sys.argv[1:]
    if "--selfcheck" in args:
        bad = _self_check()
        say("")
        say("全過" if not bad else ("%d 項沒過" % bad))
        sys.exit(1 if bad else 0)

    result = check_approval_queue_coverage()
    say("== AS3 完整性守門：APPROVAL_DOC_TYPES 的兩支佇列端點涵蓋 ==")
    for dt, why in sorted(result["not_applicable"].items()):
        say("   --  不適用 %s：%s" % (dt, why))
    if is_clean(result):
        say("   OK  全部涵蓋")
        sys.exit(0)
    if result["missing_from_map"]:
        say("   NG  沒有登記翻譯表：%s" % ", ".join(result["missing_from_map"]))
    if result["missing_from_queue"]:
        say("   NG  GET /api/approval-queue 源碼裡找不到：%s"
            % ", ".join(result["missing_from_queue"]))
    if result["missing_from_count"]:
        say("   NG  GET /api/approval-queue/count 源碼裡找不到：%s"
            % ", ".join(result["missing_from_count"]))
    sys.exit(1)


if __name__ == "__main__":
    main()
