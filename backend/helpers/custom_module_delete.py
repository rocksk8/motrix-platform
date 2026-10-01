# -*- coding: utf-8 -*-
"""刪除自訂模組（建構器首頁「刪除模組」）。

定義文件庫的不變式是「已發布版本不可刪」（core/definitions.py）；本檔是唯一的例外：整個模組（所有版本＋草稿）一起刪，
且**只有在沒有任何單據時**才允許。有單據 ⇒ 拒絕並回單據數（單據可能已入帳、已簽核，不能悄悄消失）。
測試用的模組若要連單據清掉，須明確 `with_records=True`，且該模組不得有金流 outbox 紀錄（已入帳 ⇒ 一律拒絕）。
"""
import os

from . import uploads as _up

#: 以 module_key 欄位綁模組的單據表（刪單據時一併清）
_BY_MODULE_KEY = ("custom_record_values", "custom_record_snapshots", "custom_record_revisions", "custom_record_files")


class ModuleDeleteError(ValueError):
    def __init__(self, message, status=409, records=0):
        super().__init__(message)
        self.status = status
        self.records = records


def record_count(conn, key) -> int:
    return conn.execute("SELECT COUNT(*) FROM custom_records WHERE module_key=?", (key,)).fetchone()[0]


def delete_module(conn, key, with_records=False) -> dict:
    """刪整個模組。回 `{"versions": 刪掉的定義列數, "records": 刪掉的單據數}`。"""
    n_def = conn.execute("SELECT COUNT(*) FROM ui_definitions WHERE kind='custom_module' AND scope='company' AND key=?",
                         (key,)).fetchone()[0]
    if not n_def:
        raise ModuleDeleteError("沒有這個模組", status=404)
    open_sub = conn.execute("SELECT 1 FROM ui_definitions WHERE kind='custom_module' AND scope='company' AND key=? "
                            "AND status='submitted'", (key,)).fetchone()
    if open_sub:
        raise ModuleDeleteError("這個模組有送審中的版本：請先核可或退回，再刪除")
    n_rec = record_count(conn, key)
    if n_rec and not with_records:
        raise ModuleDeleteError("這個模組已有 %d 筆單據，不能直接刪除（單據可能已簽核或入帳）。"
                                "若只是測試資料，請確認後選「連同單據一併刪除」" % n_rec, records=n_rec)
    if n_rec:
        if conn.execute("SELECT 1 FROM custom_record_finance_outbox WHERE module_key=? LIMIT 1", (key,)).fetchone():
            raise ModuleDeleteError("這個模組的單據已產生金流入帳事件，不能刪除；請改為在選單隱藏（誰看得到＝無人）", records=n_rec)
    paths = [r[0] for r in conn.execute("SELECT path FROM custom_record_files WHERE module_key=?", (key,)).fetchall()]
    ids = "SELECT id FROM custom_records WHERE module_key=?"
    conn.execute("DELETE FROM custom_record_log WHERE record_id IN (%s)" % ids, (key,))
    for t in _BY_MODULE_KEY:
        conn.execute("DELETE FROM %s WHERE module_key=?" % t, (key,))
    conn.execute("DELETE FROM custom_records WHERE module_key=?", (key,))
    conn.execute("DELETE FROM custom_record_counters WHERE module=?", (key,))
    conn.execute("DELETE FROM ui_definitions WHERE kind='custom_module' AND scope='company' AND key=?", (key,))
    conn.commit()
    for p in paths:                       # 實體檔在 commit 之後才刪：資料庫失敗時不會留下指向已刪檔的列
        try:
            full = os.path.join(_up.UPLOADS_ROOT, p)
            if os.path.isfile(full):
                os.remove(full)
        except OSError:
            pass
    return {"versions": n_def, "records": n_rec}
