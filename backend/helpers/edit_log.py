# -*- coding: utf-8 -*-
"""逐筆編寫紀錄（`FN4②`）—— **缺「改前值」就寫不進去**。

施工圖 `§六①`。適用兩張同形狀的表：
```
voucher_edit_log        傳票     外鍵 voucher_id
bonus_award_edit_log    獎金單   外鍵 award_id
```

# 🔴 為什麼這條規則要抽出來，而不是寫在每支 endpoint 裡

```
內嵌在 endpoint  =>  「缺改前值要失敗」要在**每一支各實作一次**
                 =>  而漏掉的那一支**不會有任何訊號**
```
⇒ 抽成一支：規則只有一個地方，而它可以不接資料庫就被驗。

# ☠️ 而 `DEFAULT '[]'` 擋不住空紀錄

一列 `changes_json='[]'` 的留痕**看起來像有記錄**，而它什麼都沒說。
少了改前值的那一列更刺：它有時間、有人、有欄位名，
**而回答不出「原本是什麼」** —— 🔑 **那正是逐筆紀錄唯一要回答的問題。**

# 📌 而這一支刻意**不是**兩張表共用的「引擎」

施工圖選「同形狀 ＋ 同命名」而不是「同一份實作」的理由是
**共用的東西壞掉時兩個模組同時失效**。
⇒ 這裡共用的只有**驗證規則**（一段純邏輯），寫入仍由各自的呼叫端指定表。
"""
import json

#: 合法的保留期（`§五`）。**這裡不訂天數** ——
#:
#: ⚠️ 法條的起算點是「年度決算辦理終了後」，而系統**沒有記錄那個時點**
#:    ⇒ 任何寫進來的天數都是猜的。會計師答了之後改設定值，不改結構。
RETENTION_VALUES = ("permanent", "term")

#: 這一支支援的表。**名字是資料，不是字串拼接的來源** ——
#: ⚠️ 呼叫端只能從這裡挑，避免有人把使用者輸入拼進 SQL。
EDIT_LOG_TABLES = {
    "voucher_edit_log": "voucher_id",
    "bonus_award_edit_log": "award_id",
}


class MissingOldValue(ValueError):
    """改動紀錄缺「改前值」。

    🔑 用一個**自己的例外型別**，讓呼叫端分得出「規則擋下來」與
       「資料庫壞了」—— 兩者的下一步完全不同。
    """


def validate_changes(changes):
    """每一筆改動都要有 `from`（改前）與 `to`（改後）。回正規化後的清單。

    ⚠️ `from` 是 `None` 或空字串**算有值** —— 「原本是空的」是一個合法的答案，
       而「沒有記錄原本是什麼」不是。
    ☠️ 用 `changes.get("from")` 的真假值判斷的話，一筆「原本是空白」的改動
       會被當成缺值而拒絕 ⇒ 使用者改不了任何一個原本空白的欄位。
       〈null 不等於 0〉的同族：**用 `in` 判斷鍵在不在，不要用值的真假。**
    """
    if not changes:
        raise MissingOldValue(
            "沒有任何改動內容：一筆空的編寫紀錄回答不出「改了什麼」。")
    out = []
    for i, ch in enumerate(changes):
        if not isinstance(ch, dict):
            raise MissingOldValue("第 %d 筆改動的格式不正確。" % (i + 1))
        field = ch.get("field") or ch.get("name")
        if not field:
            raise MissingOldValue("第 %d 筆改動沒有指出是哪一個欄位。" % (i + 1))
        if "from" not in ch and "old" not in ch:
            raise MissingOldValue(
                "欄位「%s」的改動沒有記錄**改前的值** —— "
                "少了它，這一列回答不出「原本是什麼」。" % field)
        if "to" not in ch and "new" not in ch:
            raise MissingOldValue(
                "欄位「%s」的改動沒有記錄改後的值。" % field)
        out.append({
            "field": field,
            "from": ch["from"] if "from" in ch else ch.get("old"),
            "to": ch["to"] if "to" in ch else ch.get("new"),
        })
    return out


def append_edit_log(conn, entity_id, changed_by, changes,
                    table="voucher_edit_log", retention="term", changed_at=None):
    """寫一列編寫紀錄。缺改前值 ⇒ 丟 `MissingOldValue`，**不寫入**。

    ## ⚠️ `conn` 可以是 `None` ＝ **只驗不寫**

    那不是一個偷懶的旁路，是刻意留的：這條規則要能在**沒有資料庫**的情況下
    被驗（守門、單元測試、呼叫端的前置檢查都用得到）。
    🔑 而順序是**先驗後寫** —— 驗不過就沒有任何東西進到資料庫，
       ☠️ 反過來的話會留下一列「寫進去又被回滾」的空隙，
          而那在並行時看得到。
    """
    rows = validate_changes(changes)
    if retention not in RETENTION_VALUES:
        raise ValueError(
            "保留期「%s」不在允許的值裡（%s）——\n"
            "值域外的值不會報錯，它只是讓清理排程**跳過那一列**。"
            % (retention, "／".join(RETENTION_VALUES)))
    if conn is None:
        # 只驗不寫。回正規化後的內容，讓呼叫端可以接著用。
        return rows

    fk = EDIT_LOG_TABLES.get(table)
    if fk is None:
        raise ValueError("不支援的編寫紀錄表「%s」。" % table)
    from datetime import datetime
    conn.execute(
        "INSERT INTO %s (%s, changed_by, changed_at, changes_json, retention)"
        " VALUES (?,?,?,?,?)" % (table, fk),
        (entity_id, changed_by, changed_at or datetime.now().isoformat(),
         json.dumps(rows, ensure_ascii=False), retention))
    return rows
