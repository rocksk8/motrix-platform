"""§9 QL 的共用件：把「PDF 上印出來的公司身分」抽成可比對的一段。

---

# 🔑 為什麼要有這個檔

`QL6` 的驗收條件是**逐字相同**：
> 清空所有據點的抬頭欄位 ⇒ **PDF 的 header/footer 與改版前逐字相同。**

☠️ **而「改版前」這個基準，只有在 B 動 `pdf_gen.py` 之前取得才算數。**
⇒ `GOLDEN`（在 `test_quote_location_identity_2026_09_22.py` 裡）是
**2026-09-22 用還沒改過的 `pdf_gen.py` 跑出來的**。

⚠️ **而這個做法本身有一個我踩過五次的風險**：
**把今天的實作釘成不變量。**
🔑 這一次它是對的，理由很窄：**規格明著把「與改版前逐字相同」寫成驗收條件。**
📌 ⇒ 所以釘的範圍要**剛好是身分那幾行**，不是整份文件
（整份含日期、金額、流水號，那些本來就該變）。
"""
import inspect
import re

#: 一行 HTML 只要含這些字樣之一，就算是「印出公司身分的那一行」。
#:
#: ⚠️ 判準刻意**不是** `class="co-name"` —— 那是**版面**，
#: ☠️ 而 B 要改的正是版面（把寫死的值換成從據點讀）。
#: 🔑 用**值**當判準 ⇒ 「這幾個字還印不印得出來」問的是行為，不是結構。
IDENTITY_MARKERS = (
    "允碩整合集創",
    "MOTRIX Synergy Integration Corp.",
    "60575481",
    "04-3610-6566",
    "info@miactw.com",
)

#: 9 支 builder。📌 `payslip` 是第 9 支，走 `QL8` 那條路（用主要據點）。
BUILDERS = (
    "_build_quote_html",
    "_build_shipping_html",
    "_build_contractor_voucher_html",
    "_build_invoice_voucher_html",
    "_build_payment_request_html",
    "_build_case_closing_html",
    "_build_project_execution_report_html",
    "_build_completion_html",
    "_build_payslip_html",
)

#: 有兩支吃不下空 dict，補上它們**只為了跑起來**需要的鍵。
#: ⚠️ 值刻意留空／留空清單：這個檔關心的是抬頭，不是內容。
MINIMAL_INPUT = {
    "_build_case_closing_html": {
        "paymentRows": [], "dispatches": [], "stages": [],
        "closedAt": "", "wonAt": "", "quoteDate": "", "quoteNo": "",
        "customer": "", "project": "", "salesPerson": "",
        "total": 0, "pretax": 0, "taxAmount": 0, "receivedTotal": 0,
    },
    "_build_project_execution_report_html": {
        "stages": [], "actionItems": [], "feed": [],
        "materials": [], "workLogs": [],
        "quoteNo": "", "customer": "", "project": "",
        "salesPerson": "", "assignedNames": "", "dealTag": "",
    },
}


#: builder 不在 pdf_gen 的（樣板已搬回擁有模組）：名稱 → 模組名
BUILDER_HOME = {"_build_completion_html": "modules.case.completion_pdf"}   # M01 ②


def builder(name):
    import importlib
    return getattr(importlib.import_module(BUILDER_HOME.get(name, "pdf_gen")), name, None)


def render(name):
    """跑一支 builder，回傳整份 HTML。"""
    fn = builder(name)
    payload = dict(MINIMAL_INPUT.get(name, {}))
    required = [p for p in inspect.signature(fn).parameters.values()
                if p.default is inspect.Parameter.empty]
    args = []
    for i, _p in enumerate(required):
        args.append(payload if i == 0 else {})
    return fn(*args)


def identity_lines(html):
    """那份 HTML 裡**印出公司身分**的每一行（去掉左右空白，保留順序）。

    🔑 回傳的是 list 不是 set：**順序與重複次數都算**。
    ☠️ 用 set 的話，「footer 被整個刪掉而 header 還在」會通過。
    """
    out = []
    for line in html.splitlines():
        if any(mark in line for mark in IDENTITY_MARKERS):
            out.append(line.strip())
    return out


def snapshot():
    """9 支 builder 的身分行，`{builder 名: [行, ...]}`。"""
    return {name: identity_lines(render(name)) for name in BUILDERS}


def normalise(lines):
    """把連續空白壓成一個 —— 排版改動不該讓這些題紅。

    ⚠️ 全形空白 `　` **不壓**：它是 `統一編號：60575481　｜　電話` 裡
    那個分隔符的一部分，壓掉就分不出「版面換行」與「內容變了」。
    """
    return [re.sub(r"[ \t]+", " ", ln) for ln in lines]
