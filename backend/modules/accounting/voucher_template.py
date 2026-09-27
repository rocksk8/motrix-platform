# -*- coding: utf-8 -*-
"""傳票摘要範本的**佔位符**：封閉清單、取值來源、解析與驗證。

規格：`docs/windows/SPEC-VOUCHER.md`（施工圖）`§四`。
第一行逐字：`🔴 **這一份是施工圖：單一版本、無修訂層。照這一份做。**`

## 🔴 驗證發生在**儲存範本**那一刻，不是產生摘要的時候

施工圖 `§四` 逐字：「佔位符必須在封閉清單內，**儲存範本時**就驗證，
不在就拒絕儲存並指出是哪一個」。

☠️ 擋得晚的後果不是報錯：
```
範本存下去 => 之後每一張用它的傳票，摘要那一段**印空白**
=> 使用者看到的是「摘要有時候是空的」
=> 而那個症狀查起來會指向完全不同的地方
```
🔑 〈防護的副作用落在盲側〉：**擋得晚 ＝ 錯誤被搬到一個看不出成因的位置。**

## 📌 這支不碰資料庫

〈模組化：L2 功能模組彼此不可依賴〉—— 它只吃字串回值，
所以「儲存範本」那條路與「產生摘要」那條路可以共用同一份判斷。
"""
import re

#: 施工圖 `§四` 的封閉清單，**起始版 13 個，逐字**。
#:
#: ## ⚠️ 規則是「**只增不刪**」，而那不是保守，是因為來源的風險方向
#: ```
#: 這 13 個沒有權威來源（A-2 自己列的）=> 風險方向是**太短**，不是太長
#: 多一個  => 使用者多一個可用的欄位，沒有壞處
#: 少一個  => 使用者打得出來的東西存不進去，而他不知道為什麼
#: ```
#: 🔴 **刪之前要先查有沒有範本在用它** —— 刪掉一個正在被引用的佔位符，
#:    那些範本會從「合法」變成「非法」，而它們**已經存下去了**。
SUMMARY_PLACEHOLDERS = (
    "發票號", "發票日期", "單號", "客戶名稱", "廠商名稱",
    "未稅", "稅額", "含稅", "本行金額",
    "單據日期", "上傳檔案日期",
    "案件編號", "專案名稱",
)

#: 每個佔位符**從哪裡取值** —— 值是產生摘要時 context 字典的鍵。
#:
#: ## 🔴 它存在的理由：「在清單裡」與「拿得到值」是兩件事
#: ```
#: 有人把 {合約編號} 加進清單而沒有人寫它從哪取值
#: => 範本**存得下去**（驗證只看清單）
#: => 而之後每一張傳票那一段印空白 => **使用者以為是自己沒填**
#: ```
#: 🔑 ⇒ 這張表讓「加了佔位符卻忘了接它」**變成一個訊號**。
#: ⚠️ 而它必須**可以被數**：散在 `if/elif` 裡的話，漏接一個不會有任何訊號。
#: ⚙️ 兩個方向都要守：清單裡有而這裡沒有 ⇒ 孤兒；
#:    這裡有而清單裡沒有 ⇒ 殘留（刪了佔位符卻忘了刪它的取值來源）。
PLACEHOLDER_RESOLVERS = {
    "發票號":       "invoice_no",
    "發票日期":     "invoice_date",
    "單號":         "voucher_no",
    "客戶名稱":     "customer_name",
    "廠商名稱":     "supplier_name",
    "未稅":         "amount_untaxed",
    "稅額":         "amount_tax",
    "含稅":         "amount_total",
    "本行金額":     "line_amount",
    "單據日期":     "document_date",
    "上傳檔案日期": "uploaded_at",
    "案件編號":     "case_no",
    "專案名稱":     "project_name",
}

#: 語法：**單層大括號** `{名稱}`（B 2026-09-23 定版）。
#:
#: ⚠️ `[^{}]+` 而不是 `.+?` —— 後者會讓 `{a{b}` 這種殘缺輸入匹配出奇怪的東西。
#: ⚙️ 而「一段沒有佔位符的文字必須認出 0 個」是正對照：
#:    ☠️ 一個「什麼都認成佔位符」的解析器會讓驗證**一律拒絕**，
#:       而症狀是使用者**一個範本都存不了**。
_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")


def extract_placeholders(body):
    """回這段範本裡出現的佔位符名稱（**依出現順序、不去重**）。

    ⚠️ 不去重是刻意的：`validate_template_body()` 要能說出
       「`{發票類別}` 出現了幾次」，而去重會把那個資訊丟掉。
    """
    return [m.group(1).strip() for m in _PLACEHOLDER_RE.finditer(body or "")]


def unknown_placeholders(body):
    """這段範本裡**不在封閉清單內**的佔位符（去重、保持出現順序）。"""
    known = set(SUMMARY_PLACEHOLDERS)
    out = []
    for name in extract_placeholders(body):
        if name not in known and name not in out:
            out.append(name)
    return out


def validate_template_body(body):
    """儲存範本前的驗證。回 `(ok, bad)` —— `bad` 是**不合法的佔位符名稱清單**。

    🔑 回的是**名稱本身**，不是一句「範本含有無效的佔位符」：
    ☠️ 只說有問題的話，使用者要自己把 13 個名稱跟他打的每一個逐字對一次 ——
       **而那個字串是檢查它的人手上就有的。**
    📌 與借貸平衡的「不平衡要說出差額」同一族。
    """
    bad = unknown_placeholders(body)
    return (not bad), bad


def describe_template_error(body):
    """不能儲存的原因（**指名是哪一個**）；可以儲存回 `None`。"""
    ok, bad = validate_template_body(body)
    if ok:
        return None
    return ("範本裡有不能使用的欄位：%s。\n可用的欄位有 %d 個：%s"
            % ("、".join("{%s}" % b for b in bad),
               len(SUMMARY_PLACEHOLDERS),
               "、".join("{%s}" % p for p in SUMMARY_PLACEHOLDERS)))


def render_summary(body, context):
    """把範本填成摘要。回 `(文字, 缺值的佔位符清單)`。

    ⚠️ **缺值不靜默補空字串** —— 那正是 `PLACEHOLDER_RESOLVERS` 要防的症狀
       （摘要那一段印空白，而使用者以為是自己沒填）。
    ⇒ 缺了什麼要**回報出來**，由呼叫端決定要擋還是要提示。
    🔑 而摘要是**產生當下凍結**的（施工圖 `§四`）：這一支回傳的文字會連同
       `summary_template_id` ＋ `summary_template_version` 一起存進 `voucher_lines`，
       之後**不再重算** —— 範本日後改了，已開出的傳票不受影響。
    """
    missing = []

    def _sub(m):
        name = m.group(1).strip()
        key = PLACEHOLDER_RESOLVERS.get(name)
        # 🔑 `key is None` ＝「這個佔位符沒有取值來源」，
        #    與「來源有而值是空字串」是兩件事 —— 〈null 不等於 0〉。
        if key is None or key not in (context or {}):
            missing.append(name)
            return m.group(0)          # 原樣留著，讓它看得出來沒填上
        return str((context or {})[key])

    return _PLACEHOLDER_RE.sub(_sub, body or ""), missing
