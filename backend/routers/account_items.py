# -*- coding: utf-8 -*-
"""會計科目（`account_items`）—— 科目樹的讀取端（`FN1`）。

資料來源是經濟部公告的《商業會計項目表》112 年版，547 筆，四層。
`v93` 建表／`v94` 載入／`v96` 加 `is_active`。

# 🔴 樹**只能**靠 `parent_code` 建，不可以靠代號前綴

這不是「有例外要小心」，是**那個規則根本不成立**。實算（547 筆全掃）：

```
232 筆（42%）的 parent_code **不是**自己的前綴
  201 筆  父是**範圍代號**    111 → 11-12     1268 → 126-127
  31 筆   另一種成因
          1401…1468 → 139     （139 是真實存在的 L3 代號，子代卻編成 14xx）
          561/581/591 → 51
          3220 → 321          ☠️ L4 跑 3211…3219 之後**進位成 3220**
```
🔑 最後那一筆最說明問題：它與範圍代號無關，**是四級編號自己跨出了父的前綴**。
⚠️ 而 `126` 這個代號**根本不存在** —— 只有 `126-127`。
   ⇒ 任何「取前 n 碼當父」的寫法，在這份資料上會產生 232 個錯位或孤兒。

📌 範圍代號也**不是只在二級**：13 個裡 **4 個在 L2、9 個在 L3**。

# ⚠️ `561 勞務成本` 掛在 `51 銷貨成本` 底下是**官方表自己的形狀**

語意上讀起來是錯的（勞務成本不是一種銷貨成本），而它與解析無關 ——
實查：PDF 第 2 欄共 20 個代號，與本表 `level==2` 的 20 筆相同，
且 PDF 第 2 欄**沒有** `56`／`58`／`59`。
🔴 ⇒ **不要「修正」它。** 那是公告的表，我們照抄；擅自改結構才是問題。
"""
from fastapi import APIRouter, Header

from db import get_db
from helpers import _require_user

router = APIRouter(prefix="/api/account-items", tags=["account-items"])

#: 法定項目：`v93` 的兩支 TRIGGER 擋著，**資料層**就不可改。
SOURCE_STATUTORY = "statutory"

#: 三態（`v93` 的 CHECK）。畫面要分得出來 ——
#: ☠️ 把 `system_default` 併進 `custom` 的話，使用者會在「我的自訂」裡
#:    看到一個他從來沒建過的項目，而他不敢刪。
SOURCES = (SOURCE_STATUTORY, "system_default", "custom")


def build_tree(items):
    """`[{code, parent_code, …}]` → 巢狀樹（每個節點多一個 `children`）。

    🔴 **完全靠 `parent_code`**，一個字元的前綴都不看（理由見檔頭）。

    ⚠️ 回傳的是**新的 dict**，不改動傳進來的那些 —— 呼叫端可能還要用原始清單。
    ⚙️ 而 `parent_code` 指到不存在的代號時，那一筆會被當成**根**：
       ☠️ 丟掉它才是壞的 —— 那會讓「建了一筆而樹上看不到」變成**靜默**，
          而使用者會再建一次。看得到才有人會回報。
    """
    nodes = {}
    for it in items:
        node = dict(it)
        node["children"] = []
        nodes[node["code"]] = node

    roots = []
    for node in nodes.values():
        parent = nodes.get(node.get("parent_code") or "")
        # 🔑 `parent is node` 擋自我指涉：一筆 parent_code 等於自己的資料
        #    會讓下面的遞迴無限深，而它在清單上看起來完全正常。
        if parent is None or parent is node:
            roots.append(node)
        else:
            parent["children"].append(node)

    def _sort(group):
        # 代號是字串（`11-12` 排不成數字）⇒ 照 level 再照 code 字典序。
        group.sort(key=lambda n: (n.get("level") or 0, n.get("code") or ""))
        for n in group:
            _sort(n["children"])

    _sort(roots)
    return roots


def count_descendants(node):
    """這個節點底下總共有幾筆（不含自己）。

    🔑 畫面要在收合的節點上標出子項數 —— **它是「這裡還有東西」的唯一訊號**：
    ☠️ 預設收合而不標數字的話，使用者看到 8 個一級項目，
       會以為整個系統只有 8 筆科目。
    """
    return sum(1 + count_descendants(c) for c in node.get("children") or ())


def validate_parent(conn, parent_code):
    """建立自訂科目前，檢查 `parent_code` 指得到東西。回 `(ok, err)`。

    ⚠️ 空的 `parent_code` 是**合法**的：那是一個一級項目。
    ☠️ 放行一個不存在的父的後果不是報錯：
    ```
    那一筆建好了、清單查得到，**而樹上看不到它**（掛不上任何節點）
    => 使用者會再建一次
    ```
    🔑 而錯誤訊息要**說出是哪一個代號找不到** ——
       與借貸平衡的「說出差額」同一族：不說的話，使用者要自己去比對。
    🔴 **不可以用前綴驗**（例如「父必須是子的前 n 碼」）：
       `126-127` 是一個**存在的**合法父，而它不是 `1268` 的前綴。
    """
    code = (parent_code or "").strip()
    if not code:
        return True, None
    row = conn.execute(
        "SELECT code FROM account_items WHERE code = ?", (code,)).fetchone()
    if row is None:
        return False, ("找不到上層科目代號「%s」，請先確認它存在。" % code)
    return True, None


@router.get("")
def list_account_items(include_inactive: bool = False,
                       authorization: str = Header(None)):
    """科目樹 ＋ 統計。

    ⚠️ 預設**只回啟用中的** —— 停用的科目仍然留在資料庫裡
       （歷史傳票要印得出名稱），而它不該出現在挑選科目的地方。
    """
    _require_user(authorization)
    conn = get_db()
    try:
        sql = ("SELECT code, level, name, name_en, parent_code, source,"
               " is_active FROM account_items")
        if not include_inactive:
            sql += " WHERE is_active = 1"
        items = [dict(r) for r in conn.execute(sql + " ORDER BY code")]
    finally:
        conn.close()

    tree = build_tree(items)
    by_source = {}
    for it in items:
        by_source[it["source"]] = by_source.get(it["source"], 0) + 1
    return {
        "tree": tree,
        "total": len(items),
        "by_source": by_source,
        # 🔑 畫面靠這個標「(32)」，算在後端是為了 §37a 同源同單位：
        #    **畫面與日後的匯出用同一個數字**，不要各算各的。
        "counts": {n["code"]: count_descendants(n) for n in _walk(tree)},
    }


def _walk(nodes):
    for n in nodes:
        yield n
        for x in _walk(n.get("children") or ()):
            yield x
