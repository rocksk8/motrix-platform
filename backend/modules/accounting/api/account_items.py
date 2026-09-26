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
import re
import sqlite3

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from db import get_db
from helpers import _require_user, _audit, _tok

router = APIRouter(prefix="/api/account-items", tags=["account-items"])

#: 法定項目：`v93` 的兩支 TRIGGER 擋著，**資料層**就不可改。
SOURCE_STATUTORY = "statutory"

#: 三態（`v93` 的 CHECK）。畫面要分得出來 ——
#: ☠️ 把 `system_default` 併進 `custom` 的話，使用者會在「我的自訂」裡
#:    看到一個他從來沒建過的項目，而他不敢刪。
SOURCES = (SOURCE_STATUTORY, "system_default", "custom")


#: `CA1 §3②`：尾碼要當**整數**比，不能當字串比。
#:
#: ```
#: "1111-9" 之後是 "1111-10"，字串比大小 "1111-10" < "1111-9"（'1' < '9'）
#: ⇒ 排序把 1111-10 排到 1111-2 前面
#: ```
#: ☠️ 它會在**第 10 個自建科目**那天才出錯，症狀是「順序怪怪的」，
#: 沒有人會報修——這裡改用自然排序：把代號裡的連續數字段落轉成 `int`
#: 再比，其餘照字串比。同一個函式對範圍代號（`11-12`）與延伸代號
#: （`1111-1`）都適用，不必先判斷它是哪一種——這裡只管排序正確，
#: 不判斷語意。
_NAT_SPLIT_RE = re.compile(r"(\d+)")


def _natural_code_key(code):
    return [int(p) if p.isdigit() else p for p in _NAT_SPLIT_RE.split(code or "")]


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
        # 照 level 再照 code 自然排序（見 `_natural_code_key`）。
        group.sort(key=lambda n: (n.get("level") or 0,
                                  _natural_code_key(n.get("code") or "")))
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
        # 🔴 `CA1 §6`：「頁面須說明自建總數有多少」——由後端算，
        #    前端不要自己數（前端數的是「畫面上載入的那些」，日後加分頁
        #    或篩選，那個數字會安靜地變小）。
        #    ⚠️ **獨立查，不重用上面那個 `items`**：`items` 依
        #    `include_inactive` 篩過，而自建總數要含已停用的（停用不是
        #    刪除——一個科目曾經被自建過這件事不會因為停用而消失）。
        custom_total = conn.execute(
            "SELECT COUNT(*) c FROM account_items WHERE source = 'custom'"
        ).fetchone()["c"]
        custom_inactive = conn.execute(
            "SELECT COUNT(*) c FROM account_items"
            " WHERE source = 'custom' AND is_active = 0"
        ).fetchone()["c"]
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
        "custom_count": custom_total,
        "custom_inactive_count": custom_inactive,
    }


def _walk(nodes):
    for n in nodes:
        yield n
        for x in _walk(n.get("children") or ()):
            yield x


# ══════════════════════════════════════════════════════════════════════
# `CA1` 自訂會計科目（延伸建立 ＋ 停用）
# ══════════════════════════════════════════════════════════════════════
#
# 使用者原話：「例如1111已經有了，只能延伸建立例如1111-1這樣的科目，
# 用延伸遞增去建立，父層級不可創立，且頁面須說明自建總數有多少」。
# 施工圖：`docs/windows/SPEC-CA1-CUSTOM-ACCOUNTS.md`。


class ExtendAccountItemIn(BaseModel):
    """延伸建立的請求體——**只有這兩個欄位**（白名單，不是黑名單）。

    ⚠️ `code`／`level`／`parent_code`（作為結構鍵）不由前端送：`code` 由
    後端算（同 `voucher_no` 的理由：前端不發號），`level` 從被延伸科目
    推出來。pydantic 對不在模型裡的欄位預設 `extra='ignore'`——這正是
    `§5④`「父層級不可創立：body 帶了 code／level／parent_code 以外的
    結構欄位 => 忽略」要的效果，不必另外寫檢查。
    """
    parent_code: str
    name: str


class SetAccountItemActiveIn(BaseModel):
    is_active: bool


@router.post("")
def extend_account_item(body: ExtendAccountItemIn,
                        authorization: str = Header(None)):
    """延伸建立一個自訂科目。`code` = `{被延伸代號}-{流水號}`。

    ## 🔴 撞號時**一律用純 `INSERT`**，不要 `OR IGNORE`／`OR REPLACE`

    `db.py:4298` 現成的一句是 `INSERT OR IGNORE`——同一張表、欄位幾乎
    一樣，就在附近，是最可能被照抄的一句，而它的後果是**靜默無事發生**
    （使用者按了建立、回應 200，而畫面上什麼都沒有）。`OR REPLACE` 更糟：
    舊列可能已被傳票引用，覆蓋掉它就是**改寫歷史**。這裡用純 `INSERT`，
    撞號讓它丟 `IntegrityError`，接住之後回一句看得懂的話。

    ## ⚠️ 取下一號用**最大值 +1**，不是數筆數；且**不濾掉停用的**

    `1111-1 1111-2 1111-3`，停用 `1111-2` 之後再建 => 下一個必須是
    `1111-4` 不是 `1111-3`——停用不是刪除，號碼不可以被重用（同
    `helpers/voucher.py::next_voucher_no` 的理由）。

    ## 🔴 `§8②`（A-2 建議，未裁）：範圍代號不可延伸

    `11-12` 這種法定範圍代號（`source='statutory'` 且代號本身含 `-`）
    擋下延伸——擋了還能放寬，放了收不回來。這條**還沒有人裁過**，
    先照 A-2 的建議做，需要時再改。

    ⚠️ `§8①`（延伸能不能再延伸，`1111-1-1`）**也還沒有人裁過**——這裡
    沒有加額外限制（`validate_parent()` 只看代號存不存在，不看它本身
    是不是延伸出來的），因為使用者原話「被延伸的代號必須已經存在」對
    `1111-1` 一樣成立。若要禁止，之後再加一條件即可。
    """
    user = _require_user(authorization, require_superadmin=True)
    parent_code = (body.parent_code or "").strip()
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "請填寫科目名稱。")
    if not parent_code:
        raise HTTPException(400, "請選擇要延伸的科目。")

    conn = get_db()
    try:
        ok, err = validate_parent(conn, parent_code)
        if not ok:
            raise HTTPException(400, err)
        prow = conn.execute(
            "SELECT level, source, is_active FROM account_items WHERE code = ?",
            (parent_code,)).fetchone()
        if not prow["is_active"]:
            raise HTTPException(
                400, "「%s」已停用，不能在它底下新增。" % parent_code)
        if prow["source"] == SOURCE_STATUTORY and "-" in parent_code:
            raise HTTPException(
                400, "「%s」是範圍代號，不是單一科目，不能在它底下新增，"
                     "請選一個明確的科目。" % parent_code)

        existing = conn.execute(
            "SELECT code FROM account_items"
            " WHERE parent_code = ? AND source = 'custom'", (parent_code,)
        ).fetchall()
        max_n = 0
        for r in existing:
            suffix = r["code"].rsplit("-", 1)[-1]
            if suffix.isdigit():
                max_n = max(max_n, int(suffix))
        new_code = "%s-%d" % (parent_code, max_n + 1)
        new_level = int(prow["level"] or 0) + 1

        try:
            conn.execute(
                "INSERT INTO account_items"
                " (code, level, name, name_en, parent_code, source, is_active)"
                " VALUES (?,?,?,?,?,?,1)",
                (new_code, new_level, name, "", parent_code, "custom"))
        except sqlite3.IntegrityError:
            raise HTTPException(
                409, "科目代號「%s」已經存在，請重新整理後再試一次。" % new_code)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "account_item.extend", "account_items",
           new_code, "延伸建立會計科目：%s（%s），母科目 %s"
                     % (new_code, name, parent_code))
    return {"ok": True, "code": new_code, "level": new_level,
           "parent_code": parent_code, "name": name}


@router.patch("/{code}")
def set_account_item_active(code: str, body: SetAccountItemActiveIn,
                            authorization: str = Header(None)):
    """停用／啟用一個**自訂**科目。**停用不是刪除**（`db.py` v96 docstring
    逐字）⇒ 用 `PATCH`，不用 `DELETE`。

    🔴 `§7⑦`：拒絕停用法定科目要在**應用層**先擋，給一句看得懂的話——
    `account_items_statutory_no_update` TRIGGER 會擋，但那樣冒出來的是
    `sqlite3.IntegrityError`，使用者看不懂。
    """
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT source, is_active FROM account_items WHERE code = ?",
            (code,)).fetchone()
        if row is None:
            raise HTTPException(404, "找不到科目代號「%s」。" % code)
        if row["source"] == SOURCE_STATUTORY:
            raise HTTPException(
                400, "「%s」是法定科目，不能停用或啟用。" % code)
        conn.execute(
            "UPDATE account_items SET is_active = ? WHERE code = ?",
            (1 if body.is_active else 0, code))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "account_item.set_active", "account_items",
           code, "會計科目%s：%s" % ("啟用" if body.is_active else "停用", code))
    return {"ok": True, "code": code, "is_active": body.is_active}
