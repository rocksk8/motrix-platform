# -*- coding: utf-8 -*-
"""`EM3` · 例外的內容不可以上畫面（`docs/windows/SPEC-EM3.md`）。

```
判準  這個 HTTPException 的 detail 會不會把我們沒有寫過的字
      （資料表名／欄位名／暫存檔路徑／SQL 片段／函式庫版本……）
      送到使用者畫面上？—— 全部來自例外物件本身，不是我們決定要說的
```

# 🔴 動工前獨立重掃一次母體（規格自己要求：兩個數字都還沒有第二把尺量過）

規格用 AST 判定：`except … as e` 綁的名字，是否被同一個 handler 裡
`raise HTTPException(detail=X)` 的 `X` 引用到，依 `except` 抓的例外
類型切成三層。獨立重寫一支同方法論、不同實作的掃描器（`ast.walk` 找
`Try`→`ExceptHandler`→`Raise(HTTPException(...))`，逐一比對 `detail`
運算式裡的 `Name` 節點），只掃 `backend/routers/*.py`（規格母體的範圍）：

```
A 組（except Exception，detail 引用例外物件）    18 處  ✅ 與規格逐一核對，數字一致
B 組（我們自己 raise 的例外類別，同樣引用）      17 處  ✅ 同上
C 組（ValueError／RuntimeError，同樣引用）       18 處  ✅ 同上（本檔不對它下驗收）
合計 53 —— 兩把不同實作的尺量出同一個數字，是好的交叉驗證
```
⚠️ 個別行號與規格 `§3`／`§4` 列的有小幅落差（這段期間其他工單動過這幾
個檔案，行數自然位移）——已用**檔案＋函式名**逐一核對過仍然一致，本檔
的基準（`_BASELINE_A`／`_BASELINE_B`）用「檔案＋函式名」當識別 key，
不釘死行號。

## 🔴 第一版掃描器多算了 3 處——「在 `except Exception` 區塊裡」不等於「母體」

第一版用「檔案＋例外類型的出現次數」當 key，跑出 A 組 22 處而不是
18——多出來的 3 處是 `auth.py::webauthn_register_complete`／
`bonus.py::create_award`／`vouchers.py::create_voucher`：它們確實是
`except Exception as e`，而 `raise HTTPException` 的 `detail` 是**手寫
的訊息**（例如「傳票號碼「%s」剛剛被別人用掉了」），根本沒有引用 `e`。
規格 `§2` 的定義逐字是「`detail` 的運算式**引用到** `except…as e` 綁的
名字」——這 3 處從一開始就不是這份 18/17/18 清單的成員，不是「已經
修好了」也不是「本來就安全」，是**從來沒被規格點名過**。⇒ 現在的
`_scan_router_file()` 對每個 call site 都記錄 `leaks`（`detail` 有沒有
引用那個名字），基準的**身分**用 `(檔案, 函式名)` 釘住（不隨「現在還
漏不漏」變動——那正是修完之後應該改變的東西），而「這個身分底下的
call site 現在還漏不漏」是另一道獨立的斷言（`②`／反向控制）。

# ⚙️ 本檔做的與刻意不做的

```
✅ ① 母體三層都對過（A/B/C 各自的檔案＋類型＋次數）
✅ ② 反向控制：B 組 17 處的 detail **仍然**引用例外物件（斷言不動它）
✅ ③ 核心：A 組 18 處扣掉 1 個具名例外＝17 處，detail **不可以再**引用
     例外物件（結構層，逐一釘住）
✅ ③b 反向控制：那 1 個具名例外（`quotations.py::create_quotation`）
     仍然要 `raise HTTPException(400, str(e))`——B 開工時判斷「這一處
     是我們自己的業務例外，不是要防的東西」，見
     `_BASELINE_A_NAMED_EXCEPTION` 的完整說明。**這是規格 §6c 授權
     B 決定之後才出現的分類，不是本檔原本就知道的**（原始版本釘的是
     「A 組 18 處全部不可以洩漏」，B 交件後這一處紅了，查證後確認是
     判準與實際型別分岔，不是缺陷，才拆出這個第四類）。
✅ ④ 用 `completion_notes.py` 的 PDF 匯出端點做**一次**完整行為驗收
     （§7③ⓐⓑⓒ：畫面顯示代碼、log 找得到代碼＋全文、連續兩次代碼不同）
❌ 不對其餘 16 個 A 組端點各自重複④——那需要各自準備前置資料觸發真的
   失敗，成本很高而驗證的是同一段共用邏輯（`helpers/errors.py::
   trace_id()` ＋「先組訊息／log 再 raise」的順序），③已經用結構層
   的方式**同時**釘住這 17 處「不可以還在洩漏」，④證明「這一種寫法
   真的做得到 §7 要求的完整行為」，兩者合起來覆蓋規格要求。
❌ 不對 C 組（18 處）下任何驗收——規格明講「待查不是已判定安全」，
   〈不可以在驗收裡寫『C 組 = 0』〉：寫了會把它們推向「一起改掉」。
"""
import ast
import logging
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
ROUTERS_DIR = ROOT / "backend" / "routers"

_TRACE_CODE_RE = re.compile(r"\b[0-9a-f]{8}\b")


def _exc_type_names(handler):
    t = handler.type
    if t is None:
        return []
    if isinstance(t, ast.Name):
        return [t.id]
    if isinstance(t, ast.Tuple):
        return [e.id for e in t.elts if isinstance(e, ast.Name)]
    if isinstance(t, ast.Attribute):
        return [t.attr]
    return []


def _references_name(node, name):
    return any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(node))


def _find_http_exceptions_in(body, bound_name):
    """`handler.body` 這段語句裡，`raise HTTPException(...)` 的 `detail`
    引用到 `bound_name` 的那些呼叫。回 `[(lineno, references_it), …]`。
    """
    out = []
    wrapper = ast.Module(body=body, type_ignores=[])
    for node in ast.walk(wrapper):
        if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
            continue
        call = node.exc
        fname = (call.func.id if isinstance(call.func, ast.Name)
                else getattr(call.func, "attr", ""))
        if fname != "HTTPException":
            continue
        detail_expr = call.args[1] if len(call.args) >= 2 else None
        for kw in call.keywords:
            if kw.arg == "detail":
                detail_expr = kw.value
        if detail_expr is not None:
            out.append((node.lineno, _references_name(detail_expr, bound_name)))
    return out


def _classify(types):
    if "Exception" in types:
        return "A"
    if any(t in ("ValueError", "RuntimeError") for t in types):
        return "C"
    return "B"


def _enclosing_function_map(tree):
    """回傳 `{id(try_node): 最近的外層函式名字}`——用**遞迴下鑽**（不是
    `ast.walk` 的扁平走訪）才分得出「這個 `Try` 屬於哪一個函式」；
    `ast.walk` 沒有階層資訊，兩個函式各自的 `Try` 會混在一起。
    """
    mapping = {}

    def visit(node, current_func):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            current_func = node.name
        if isinstance(node, ast.Try):
            mapping[id(node)] = current_func
        for child in ast.iter_child_nodes(node):
            visit(child, current_func)

    visit(tree, None)
    return mapping


def _scan_router_file(path):
    """回傳這個檔案裡**所有**「`except` 綁了名字、且區塊內有
    `raise HTTPException(...)`」的呼叫（`leaks` 記錄 `detail` 有沒有
    引用那個綁定的名字）。

    🔑 population（要不要進 18/17/18 這份清單）**逐字照抄規格 §2**：
    「`HTTPException(detail=X)` 而 `X` 的運算式引用到 `except…as e`
    綁的名字」——`detail` 沒有引用那個名字的 call site（例如手寫訊息、
    UNIQUE 約束衝突訊息）從來就不是這份清單裡的任何一員。⚠️ 而**這裡
    刻意不過濾**：過濾成「只回目前還在漏的」會讓這支掃描器在 B 修完
    之後找不到任何一筆——那樣就沒有東西可以拿來確認「A 組那 18 個
    call site 本身還在，只是不再漏了」。過濾的動作留到「決定基準」
    那一步（下面的 `_BASELINE_A`／`_BASELINE_B`，用 `(file, function)`
    釘住身分，不用「現在還漏不漏」釘）。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    func_of = _enclosing_function_map(tree)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            if handler.name is None:
                continue
            types = tuple(_exc_type_names(handler))
            for lineno, refs in _find_http_exceptions_in(handler.body,
                                                         handler.name):
                out.append({
                    "file": str(path.relative_to(ROOT)),
                    "function": func_of.get(id(node)),
                    "lineno": lineno,
                    "types": types,
                    "group": _classify(types),
                    "leaks": refs,
                })
    return out


def _scan_all():
    out = []
    from core import source_tree  # 模組的 api.py 也要掃（守門對象不可以被搬走）
    for p in source_tree.router_files():
        out.extend(_scan_router_file(p))
    return out


def _by_identity(entries):
    """鍵是 `(檔案, 函式名)`——這是身分，不是「現在還漏不漏」。"""
    return {(e["file"], e["function"]): e for e in entries}


#: 獨立重掃驗證過的 A 組基準（要改的 18 處）：`(檔案, 函式名)` 的集合。
#: ⚠️ **不用「檔案＋例外類型的出現次數」當鍵**——第一版這樣做時，
#: `auth.py::webauthn_register_complete`／`bonus.py::create_award`／
#: `vouchers.py::create_voucher` 這三個「在 `except Exception` 區塊裡，
#: 但 `detail` 是手寫訊息、根本沒有引用例外物件」的 call site 被誤算
#: 進母體，把 18 灌成 22——它們符合「例外類型」但不符合規格 §2 的定義
#: （`detail` 沒有引用 `except…as e` 綁的名字），本來就不在這份清單裡。
#: ⚠️ 也不釘行號——其他工單會動到這些檔案上下文，行號會漂移；函式名
#: 是這批端點裡最穩定的識別方式（一個端點一個函式，不會因為上面多了
#: 幾行程式碼就變成另一個端點）。
_BASELINE_A = {
    ("backend\\modules\\case\\api\\completion_notes.py", "download_completion_pdf"),
    ("backend\\modules\\subcontract\\api\\contractor_vouchers.py", "download_contractor_voucher_pdf"),
    ("backend\\routers\\customers.py", "create_customer"),
    ("backend\\modules\\arap\\api\\invoice_vouchers.py", "download_invoice_voucher_pdf"),
    ("backend\\modules\\netplan\\api.py", "preview_network_plan_topology"),
    ("backend\\modules\\netplan\\api.py", "import_network_plan_excel"),
    ("backend\\modules\\netplan\\api.py", "preview_quick_topology"),
    ("backend\\modules\\arap\\api\\payment_requests.py", "download_payment_request_pdf"),
    ("backend\\modules\\payroll\\api\\payslips.py", "get_archive_pdf"),
    ("backend\\modules\\payroll\\api\\payslips.py", "pdf_download"),
    ("backend\\modules\\case\\api\\quotations.py", "create_quotation"),
    ("backend\\modules\\case\\api\\quotations.py", "download_quotation_pdf"),
    ("backend\\modules\\case\\api\\quotations.py", "download_case_closing_report_pdf"),
    ("backend\\modules\\case\\api\\quotations.py", "download_project_execution_report_pdf"),
    ("backend\\modules\\supply\\api\\shipping_notes.py", "download_shipping_pdf"),
    ("backend\\modules\\supply\\api\\suppliers.py", "create_supplier"),
    ("backend\\routers\\system.py", "test_google_calendar"),
    ("backend\\routers\\system.py", "test_email_notify"),
}

#: 🔴 A 組裡的**具名例外**：這一處 B 開工時判斷「不改」，且判斷本身是對
#: 的（`SPEC-EM3.md §6c` 授權「B 開工時決定，規格不猜」）。
#:
#: ```
#: modules/case/api/quotations.py::create_quotation
#:   except Exception as e:
#:       ...
#:       if isinstance(e, UnresolvedManagerError):
#:           raise HTTPException(400, str(e))
#:       raise
#: ```
#: AST 判準看的是「`except` 子句寫什麼」（靜態形狀：外層寫
#: `except Exception`，所以歸進 A 組）；而**執行到 `raise HTTPException`
#: 那一行時**，前面的 `isinstance` 守衛已經把 `e` 鎖定成
#: `UnresolvedManagerError`——內容與 B 組那 17 處一樣是我們自己寫的訊息
#: （例如「找不到 X 的主管」），不是未過濾的例外內容。判準與實際型別在
#: 這一處分岔：**不要為了這一處把判準寫得更細**（再細只會更難懂、更
#: 容易誤報），正確處置是承認例外並具名。
_BASELINE_A_NAMED_EXCEPTION = {
    ("backend\\modules\\case\\api\\quotations.py", "create_quotation"),
}

#: B 組基準（**不要動**的 17 處）。
_BASELINE_B = {
    ("backend\\modules\\payroll\\api\\bonus.py", "submit_award"),
    ("backend\\modules\\case\\api\\case_extra_expenses.py", "submit_extra_expense"),
    ("backend\\modules\\case\\api\\case_extra_expenses.py", "submit_change_request"),
    ("backend\\modules\\case\\api\\completion_notes.py", "submit_completion_note"),
    ("backend\\modules\\case\\api\\completion_notes.py", "approve_completion_note"),
    ("backend\\modules\\subcontract\\api\\contractor_vouchers.py", "submit_contractor_voucher"),
    ("backend\\modules\\subcontract\\api\\contractor_vouchers.py", "approve_contractor_voucher"),
    ("backend\\modules\\arap\\api\\invoice_vouchers.py", "submit_invoice_voucher"),
    ("backend\\modules\\arap\\api\\invoice_vouchers.py", "approve_invoice_voucher"),
    ("backend\\modules\\arap\\api\\payment_requests.py", "submit_payment_request"),
    ("backend\\modules\\arap\\api\\payment_requests.py", "approve_payment_request"),
    ("backend\\modules\\case\\api\\quotations.py", "update_quotation"),
    ("backend\\modules\\case\\api\\quotations.py", "approve_quotation"),
    ("backend\\modules\\supply\\api\\shipping_notes.py", "submit_shipping_note"),
    ("backend\\modules\\supply\\api\\shipping_notes.py", "approve_shipping_note"),
    ("backend\\routers\\vouchers.py", "submit_voucher"),
    ("backend\\routers\\vouchers.py", "update_voucher"),
}


def _norm(key):
    """鍵在 Windows 上用 `\\`——正規化成 `pathlib` 產生的分隔符。"""
    path, func = key
    return (path.replace("\\", "/"), func)


def _scan_all_normalized():
    return [dict(e, file=e["file"].replace("\\", "/")) for e in _scan_all()]


# ══════════════════════════════════════════════════════════════════════
# ① 母體：A／B 兩組的**身分**不可以漂移（不是「現在還漏不漏」）
# ══════════════════════════════════════════════════════════════════════

def test_em3_the_known_18_and_17_call_sites_still_exist_with_the_same_type():
    """🔴🔴 **A 組 18 個、B 組 17 個 call site，逐一還在、例外類型沒有變。**

    ☠️ 若這一題紅了，代表某個 call site 被刪掉了，或者 `except` 抓的
    例外類型被改了（不小心把它搬去了另一組）——兩種情況都要回來確認
    這份基準本身要不要更新，不是直接改期望值讓它變綠。

    🔑 用 `(檔案, 函式名)` 當身分、不用「現在還漏不漏」——後者是 `②`
    要驗的事，這一題只確認「這個 call site 本身」還在同一個分類裡。
    """
    entries = _scan_all_normalized()
    by_id = _by_identity(entries)

    # 模組資料夾被拿掉（選配／反向控制，PLAYBOOK §B 步驟 11）⇒ 它的 call site 本來就不在，不算缺
    from core import source_tree
    want_a = {_norm(k) for k in _BASELINE_A if source_tree.module_installed(k[0])}
    want_b = {_norm(k) for k in _BASELINE_B if source_tree.module_installed(k[0])}

    missing_a = [k for k in want_a if k not in by_id or by_id[k]["group"] != "A"]
    missing_b = [k for k in want_b if k not in by_id or by_id[k]["group"] != "B"]
    assert not missing_a, (
        "A 組基準裡有 %d 個 call site 現在找不到，或例外類型已經不是"
        " `Exception`：%r" % (len(missing_a), missing_a))
    assert not missing_b, (
        "B 組基準裡有 %d 個 call site 現在找不到，或例外類型已經變了："
        "%r" % (len(missing_b), missing_b))


def test_em3_the_scanner_still_catches_a_synthetic_leak():
    """⚙️ **正對照：合成一段會漏的原始碼，掃描器要抓得到——`②` 修完之後
    17 處都是綠的，這一題證明「掃描器自己會不會叫」沒有跟著消失。**

    ☠️ `②` 從紅變綠之後，它自己的紅燈曾經是「掃描器抓得到真缺陷」的
    證據；那個證據現在不在了（17 處都乾淨）。少了這一題，掃描器本身
    若哪天被改壞（例如 `_references_name()` 誤判），`②` 會安靜地
    一直綠下去，而沒有人知道那是因為「真的沒有漏」還是「量不到了」。
    ⚙️ 用**自己合成的誘餌**（不是真缺陷改好那天就失效的那種）：一段
    會漏的 `except Exception`、一段是我們自己例外的 `except`（不該被
    當成 A 組）、一段正確寫法（不該被誤判成漏）。

    ✅ **牙齒已驗證（方式：資料建構／常設）**——這一題本身就是牙齒的
    證明，不是另外驗它：斷言直接打在合成輸入的已知正確答案上，每次
    跑這個檔案都會重新驗證一次，不是跑過一次就收掉的臨時突變。
    """
    synthetic = '''
from fastapi import HTTPException

def _decoy_leaks():
    try:
        do_something()
    except Exception as e:
        raise HTTPException(500, f"操作失敗：{e}")

def _decoy_custom_exception_not_group_a():
    try:
        do_something()
    except SomeCustomError as e:
        raise HTTPException(400, str(e))

def _decoy_correct_after_fix():
    try:
        do_something()
    except Exception as e:
        tid = trace_id()
        logger.exception("failed trace=%s", tid)
        raise HTTPException(500, f"操作失敗（代碼 {tid}）")
'''
    # 🔑 `_scan_router_file()` 對每一筆結果都算 `path.relative_to(ROOT)`
    #    ——temp 目錄不在 `ROOT` 底下會直接 `ValueError`，所以誘餌檔案
    #    要放在 `ROOT` 底下（`backend/tests/` 自己這裡，真正的 `_scan_
    #    all()` 已經排除 `tests/`，不會把這個誘餌檔算進真實母體）。
    p = pathlib.Path(__file__).resolve().parent / "_em3_decoy_TEMP.py"
    try:
        p.write_text(synthetic, encoding="utf-8")
        got = {(e["function"], e["group"], e["leaks"]) for e in _scan_router_file(p)}
    finally:
        p.unlink(missing_ok=True)

    assert ("_decoy_leaks", "A", True) in got, (
        "掃描器抓不到合成的 A 組洩漏——退回檢查 `_scan_router_file()`"
        " 本身壞了，不是產品碼變乾淨了：%r" % got)
    assert ("_decoy_custom_exception_not_group_a", "B", True) in got, (
        "合成的自訂例外沒有被歸進 B 組：%r" % got)
    assert ("_decoy_correct_after_fix", "A", False) in got, (
        "掃描器把已經修好（引用 `tid` 不引用 `e`）的合成函式仍然判成"
        "洩漏——退回檢查 `_references_name()`：%r" % got)


# ══════════════════════════════════════════════════════════════════════
# ② 核心：A 組 18 處，detail 不可以再引用原始例外物件
# ══════════════════════════════════════════════════════════════════════

def test_em3_group_a_detail_must_not_reference_the_raw_exception():
    """🔴🔴 **核心：A 組 17 處（18 處扣掉一個具名例外），`HTTPException`
    的 `detail` 不可以再引用 `except … as e` 綁的那個例外物件本身。**

    ⚙️ 這是結構層的判準（AST 看得出「這個運算式裡有沒有引用那個名字」），
    不管 B 最後把 `f'PDF 產生失敗：{e}'` 改成 `f'PDF 產生失敗（代碼 {tid}）'`
    的哪一種寫法，只要 `detail` 運算式裡不再出現 `e`（改成引用一個新的
    追蹤碼變數），這一項就會過——不綁死追蹤碼變數要叫什麼名字。

    🔴 **`quotations.py::create_quotation` 排除在外**——見
    `_BASELINE_A_NAMED_EXCEPTION` 的說明與下面的
    `test_em3_the_one_named_exception_still_raises_its_own_message`。
    ☠️ **不要因為這一題紅了就把它也改掉**：那正是判斷「不該改」的那一處，
    改了會把一個使用者讀得懂、可行動的錯誤（「找不到 X 的主管」）變成
    一串看不懂的代碼，洩漏風險零減少。

    ☠️ 今天其餘 17 處都還在洩漏，這一題今天是紅的。
    """
    entries = _scan_all_normalized()
    by_id = _by_identity(entries)
    want_a = {_norm(k) for k in _BASELINE_A} - {
        _norm(k) for k in _BASELINE_A_NAMED_EXCEPTION}

    leaking = [k for k in want_a if k in by_id and by_id[k]["leaks"]]
    assert not leaking, (
        "A 組還有 %d／%d 個 call site 的 `detail` 直接引用例外物件本身：\n"
        % (len(leaking), len(want_a))
        + "\n".join("  %s :: %s" % k for k in sorted(leaking))
        + "\n☠️ 這些訊息會把資料表名／欄位名／暫存檔路徑／SQL 片段／"
          "函式庫版本這類我們沒有寫過的字直接送到使用者畫面上。")


def test_em3_the_one_named_exception_still_raises_its_own_message():
    """⚙️🔴 **反向控制：`quotations.py::create_quotation` 那一處具名例外
    仍然要 `raise HTTPException(400, str(e))`，不可以被「順手」改掉。**

    🔑 依據 `_BASELINE_A_NAMED_EXCEPTION` 的說明：AST 判準看的是
    `except` 子句寫什麼（靜態形狀），而執行到 `raise HTTPException`
    那一行時，前面的 `isinstance(e, UnresolvedManagerError)` 守衛已經
    把 `e` 的實際型別鎖定成我們自己的業務例外——內容與 B 組那 17 處
    一樣是我們自己寫的訊息，不是要防的東西。

    ☠️ 少了這一題，②那一題紅了之後，下一個看到紅燈的人最省力的反應是
    「把第 18 處也改掉讓它變綠」——而那正好是判斷「不該改」的那一處。

    ✅ **牙齒已驗證（方式：資料建構／常設）**——這一題每次都對**真的
    產品碼**斷言，不是合成輸入：寫完當場對 B 已提交的版本跑過，確認
    `assert still_leaking == list(want)` 通過（那一處確實還在 raise
    `str(e)`），不是只讀過程式碼就假設它對。
    """
    entries = _scan_all_normalized()
    by_id = _by_identity(entries)
    want = {_norm(k) for k in _BASELINE_A_NAMED_EXCEPTION}

    still_leaking = [k for k in want if k in by_id and by_id[k]["leaks"]]
    assert still_leaking == list(want), (
        "`quotations.py::create_quotation` 的 `detail` 不再引用例外物件"
        "了——%r\n" % (set(want) - set(still_leaking))
        + "☠️ 這一處是刻意保留的具名例外（`isinstance` 守衛保證內容是我們"
          "自己寫的訊息），若被改成追蹤碼，會把一個使用者讀得懂、可行動"
          "的錯誤（例如「找不到 X 的主管」）變得看不懂，而洩漏風險零減少。"
          "\n若這是刻意的重新判斷（例如那個 `isinstance` 守衛被拿掉了），"
          "請更新 `_BASELINE_A_NAMED_EXCEPTION` 並寫下新的理由，不要"
          "只是讓這一題安靜地變紅又被忽略。")


def test_em3_group_b_detail_still_references_the_custom_exception_message():
    """⚙️🔴 **反向控制：B 組 17 處的 `detail` 必須仍然引用例外物件。**

    `UnresolvedManagerError`／`MissingOldValue` 是我們自己 `raise` 的，
    `str(e)` 拿到的是我們自己寫的那句話（例如「找不到 X 的主管」）——
    這 17 處寫法與 A 組一模一樣（`str(e)`），若只驗「A 組 = 0 處洩漏」，
    一個以「把 `str(e)` 清乾淨」為目標的修法會把這 17 處一起清掉，把
    這句對使用者有意義的話換成一串看不懂的追蹤碼，而驗收會全綠。

    🔑 這一題今天就是綠的（沒有人動過）——它的價值在**修 `②` 之後**：
    確認變成「該改的改了、不該動的沒動」，不是「全部都變成追蹤碼」。
    """
    entries = _scan_all_normalized()
    by_id = _by_identity(entries)
    want_b = {_norm(k) for k in _BASELINE_B}

    not_leaking = [k for k in want_b if k in by_id and not by_id[k]["leaks"]]
    assert not not_leaking, (
        "B 組有 %d 個 call site 的 `detail` **不再**引用例外物件了——\n"
        % len(not_leaking)
        + "\n".join("  %s :: %s" % k for k in sorted(not_leaking))
        + "\n☠️ 這些是我們自己 `raise` 的例外，`str(e)` 是我們自己寫的訊息"
          "（例如「找不到 X 的主管」）——換成追蹤碼會讓使用者從「知道是"
          "誰沒設主管」變成「拿到一串代碼」，那不是這一輪要改的範圍。")


# ══════════════════════════════════════════════════════════════════════
# ③ 完整行為驗收：用一個代表性端點走一次 §7③ⓐⓑⓒ
# ══════════════════════════════════════════════════════════════════════

def _seed_completion_note(note_no="EM3-EXC-001"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO completion_notes (note_no, quote_no, customer_name)"
            " VALUES (?,?,?)", (note_no, "MQ-EM3-001", "EM3 測試客戶"))
        conn.commit()
    finally:
        conn.close()
    return note_no


def _hdr(client, make_user, username):
    u, p = make_user(username=username, role="superadmin", modules=["cashier"])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_em3_pdf_failure_shows_a_trace_code_not_the_raw_exception(
        client, make_user, monkeypatch, caplog):
    """🔴🔴 **`§7③ⓐ`：PDF 產生失敗，畫面要顯示「PDF 產生失敗（代碼 XXXXXXXX）」，
    不可以出現例外本身的內容。**

    ⚙️ 用 `completion_notes.py` 的 PDF 匯出端點代表 A 組其餘 17 處共用的
    同一段邏輯（見檔頭「刻意不做」）。監視函式故意丟一個帶著**不該出現
    在畫面上的內容**（假造的暫存檔路徑）的例外，驗收畫面上完全看不到
    這段內容，只看得到一個 8 碼 hex 代碼。
    """
    import modules.case.api.completion_notes as mod
    note_no = _seed_completion_note("EM3-EXC-001")
    hdr = _hdr(client, make_user, "em3_pdf_fail")

    leak = "C:\\some\\internal\\temp\\path\\that\\must\\not\\leak.tmp"

    def _boom(_note_no):
        raise RuntimeError("cannot open " + leak)

    monkeypatch.setattr(mod, "generate_completion_pdf_bytes", _boom)

    with caplog.at_level(logging.ERROR):
        r = client.get("/api/completion-notes/%s/pdf-download" % note_no,
                       headers=hdr)

    assert r.status_code == 500, "回 %s（預期 500）：%s" % (r.status_code, r.text[:300])
    detail = r.json().get("detail", "")
    assert leak not in detail, (
        "畫面上的 `detail` 直接洩漏了內部路徑：%r" % detail)
    assert "cannot open" not in detail, (
        "畫面上的 `detail` 直接洩漏了例外訊息本身：%r" % detail)
    assert "PDF 產生失敗" in detail, (
        "`detail` 沒有保留原本那句自己的話：%r\n" % detail
        + "🔑 A 組這幾處已經有一句自己的話，改的是後半段，不是整句重寫。")
    m = _TRACE_CODE_RE.search(detail)
    assert m, "`detail` 裡找不到 8 碼 hex 追蹤碼：%r" % detail


def test_em3_the_trace_code_is_findable_in_the_log_with_the_full_exception_text(
        client, make_user, monkeypatch, caplog):
    """🔴🔴 **`§7③ⓑ`：拿畫面上的代碼去 log 搜得到，且那裡有例外全文。**

    🔑 這是這一件的重點——沒有它，追蹤碼只是一個好看的裝飾。用
    `caplog`（in-process 攔截）而不是直接讀 `logs/server.log`：這是共用
    的開發機工作目錄，另一個視窗的伺服器行程可能正在寫同一份檔案，
    直接讀檔案風險是量到別人那一份的內容或搶不到鎖；`caplog` 攔的是
    **這個測試行程自己**呼叫 `logging` 的紀錄，不受這個影響。
    """
    import modules.case.api.completion_notes as mod
    note_no = _seed_completion_note("EM3-EXC-002")
    hdr = _hdr(client, make_user, "em3_pdf_log")

    leak = "internal detail xyz123 that only the log should see"

    def _boom(_note_no):
        raise RuntimeError(leak)

    monkeypatch.setattr(mod, "generate_completion_pdf_bytes", _boom)

    with caplog.at_level(logging.ERROR):
        r = client.get("/api/completion-notes/%s/pdf-download" % note_no,
                       headers=hdr)
    assert r.status_code == 500, r.text[:300]
    detail = r.json().get("detail", "")
    m = _TRACE_CODE_RE.search(detail)
    assert m, "畫面上的 `detail` 找不到追蹤碼，先看上一題：%r" % detail
    tid = m.group(0)

    log_text = "\n".join(rec.getMessage() + " " + (rec.exc_text or "")
                         for rec in caplog.records)
    assert tid in log_text, (
        "追蹤碼 %r 沒有出現在任何一筆 log 記錄裡：\n%s" % (tid, log_text[:500]))
    assert leak in log_text, (
        "log 裡找不到例外全文——追蹤碼查得到，而查到的東西是空的：\n%s"
        % log_text[:500])


def test_em3_two_consecutive_failures_get_different_trace_codes(
        client, make_user, monkeypatch):
    """🔴 **`§7③ⓒ`：連續觸發兩次失敗，要拿到兩個不同的代碼。**

    ☠️ 不可以是同一個（例如把 tid 快取成模組層常數），也不可以是 +1
    （流水號可猜，而且洩漏系統出過幾次錯——`§6a` 已經裁定要用
    `secrets.token_hex`）。
    """
    import modules.case.api.completion_notes as mod
    note_no = _seed_completion_note("EM3-EXC-003")
    hdr = _hdr(client, make_user, "em3_pdf_twice")

    def _boom(_note_no):
        raise RuntimeError("boom")

    monkeypatch.setattr(mod, "generate_completion_pdf_bytes", _boom)

    codes = []
    for _ in range(2):
        r = client.get("/api/completion-notes/%s/pdf-download" % note_no,
                       headers=hdr)
        assert r.status_code == 500, r.text[:300]
        m = _TRACE_CODE_RE.search(r.json().get("detail", ""))
        assert m, "找不到追蹤碼——先看前面幾題。"
        codes.append(m.group(0))

    assert codes[0] != codes[1], (
        "連續兩次失敗拿到同一個代碼 %r——\n" % codes[0]
        + "☠️ 使用者回報問題時，兩次不同的錯誤會被誤判成同一件事。")
