# -*- coding: utf-8 -*-
"""自訂模組附件（file／image 欄位，建構器第三輪 S2；core migration v4 `custom_record_files`）。

[單位] helper:custom_files    [層] L1    [穩定度] 契約（只增）
[公開介面] ALLOWED_EXTS, CustomFilesAccess, FOLDER, IMAGE_EXTS, PROVIDER, accepted_exts, bind_files, check_files, clean_ids, file_meta,
    files_of_field, purge_stale_staged, register_staged, remove_files, remove_staged, view_names
[不變式]
  - 先傳後綁單：上傳當下 record_id＝0（暫存；只有上傳者讀得到、只有上傳者能刪）；單據存檔時綁到該單；
    從單據拿掉 ⇒ 列與實體檔一併刪。已送出的單據內容凍結（改附件＝開修訂版 -R）
  - 單據裡的值＝檔案 id 清單（去重、依序）；每個 id 必須是「這個模組這個欄位」的檔，且是自己暫存的或已綁在這張單
  - 副檔名＝欄位 `accept`（子集）∩ uploads 白名單（jpg／png／pdf；image 型別只有 jpg／png）；空白＝白名單全部
  - 讀檔權限走 `uploads.path_access`（IP-104）：暫存檔＝上傳者；已綁單的檔＝看得到該模組的人（模組權限，或該模組某張
    引用這個檔的單據的簽核人）且看得到這個欄位（`access.visibleTo`）
  - 實體檔在 `uploads/custom_records/<模組>/`（demo 走 `_demo_uploads` 前綴、隨 demo 重置清掉；正式隨 uploads 鏡像備份）
[契約題] tests/test_builder3_files_2026_09_30.py
"""
import json
import logging
import os
import re
from datetime import datetime

from . import custom_builder_support as _S
from . import uploads as _up

FOLDER = "custom_records"
PROVIDER = "custom_files"                      # uploads.path_access 提供者名稱
ALLOWED_EXTS = ("jpg", "jpeg", "png", "pdf")   # 與 helpers.uploads._ALLOWED_EXTS 同（去掉點）
IMAGE_EXTS = ("jpg", "jpeg", "png")
_MAX_FILES = 50


def accepted_exts(field) -> tuple:
    """欄位允許的副檔名（小寫、不含點）：欄位 accept 與白名單的交集；沒設 ⇒ 該型別的白名單全部。"""
    base = IMAGE_EXTS if field.get("type") == "image" else ALLOWED_EXTS
    acc = [str(x).strip().lower().lstrip(".") for x in field.get("accept") or [] if str(x).strip()]
    if "jpg" in acc and "jpeg" not in acc:
        acc.append("jpeg")
    return tuple(e for e in base if not acc or e in acc)


def _now():
    return datetime.now().isoformat(timespec="seconds")


def register_staged(conn, module_key, field, saved, username) -> list:
    """`uploads.save_document_files` 的回傳（metadata 陣列）⇒ 寫進暫存列；回 `[{id, filename, size, mime, path}]`。"""
    out = []
    for m in saved:
        conn.execute("INSERT INTO custom_record_files (id, module_key, field, record_id, path, filename, size, mime, uploaded_by, uploaded_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)", (m["id"], module_key, field, 0, m["path"], m["filename"], m["size"], m.get("mime") or "",
                                                       username, m.get("uploadedAt") or _now()))
        out.append({"id": m["id"], "filename": m["filename"], "size": m["size"], "mime": m.get("mime") or "", "path": m["path"]})
    conn.commit()
    return out


_logger = logging.getLogger(__name__)


def _safe_physical_path(rel):
    """資料庫存的相對路徑 ⇒ 實體檔的真實路徑；**只准在 UPLOADS_ROOT 底下**，否則 None（呼叫端略過、不刪、不丟例外）。
    `custom_record_files.path` 是資料庫欄位，不是可信輸入：絕對路徑、`..`、磁碟機代號／UNC、符號連結繞出去都不算。
    做法同 `uploads.upload_path_key`／`doc_dir`：realpath 後 commonpath（Windows 用 normcase）必須等於根，且不能就是根本身。"""
    s = str(rel or "")
    if not s or os.path.isabs(s) or s[0] in "/\\" or ":" in s:
        return None
    segs = re.split("[" + re.escape(chr(92)) + "/]", s)          # 反斜線與斜線都當分隔
    if any(x in ("", ".", "..") for x in segs):
        return None
    root = os.path.realpath(_up.UPLOADS_ROOT)
    real = os.path.realpath(os.path.join(root, *segs))
    try:
        inside = os.path.commonpath([os.path.normcase(root), os.path.normcase(real)]) == os.path.normcase(root)
    except ValueError:                                   # 不同磁碟機
        return None
    if not inside or os.path.normcase(real) == os.path.normcase(root):
        return None
    return real


def _remove_physical(path):
    full = _safe_physical_path(path)
    if full is None:
        _logger.warning("custom_record_files.path 不在 uploads 之內，略過刪除：%r", str(path)[:120])
        return
    try:
        if os.path.isfile(full):
            os.remove(full)
    except OSError:
        pass


def remove_staged(conn, module_key, file_id, username) -> bool:
    """刪自己暫存、尚未綁單的檔（列＋實體）。不是自己的、已綁單的、不存在 ⇒ False。"""
    r = conn.execute("SELECT path FROM custom_record_files WHERE id=? AND module_key=? AND record_id=0 AND uploaded_by=?",
                     (str(file_id), module_key, username)).fetchone()
    if r is None:
        return False
    conn.execute("DELETE FROM custom_record_files WHERE id=?", (str(file_id),))
    conn.commit()
    _remove_physical(r["path"])
    return True


def _file_fields(body):
    return [f for f in body.get("fields", []) if isinstance(f, dict) and f.get("type") in ("file", "image")]


def clean_ids(f, raw) -> tuple:
    """欄位的原始值 ⇒ (去重的 id 清單, 錯誤)。允許直接是 id 字串清單，或帶 id 的物件清單（前端回傳 metadata 時）。"""
    label = f.get("label") or f["key"]
    if raw is None or raw == "" or raw == []:
        return [], ([{"key": f["key"], "message": "%s：必填" % label}] if f.get("required") else [])
    if not isinstance(raw, list):
        return [], [{"key": f["key"], "message": "%s：要是檔案清單" % label}]
    ids = []
    for x in raw:
        v = x.get("id") if isinstance(x, dict) else x
        if not isinstance(v, str) or not v.strip():
            return [], [{"key": f["key"], "message": "%s：檔案代號不正確" % label}]
        if v not in ids:
            ids.append(v.strip())
    mx = f.get("maxFiles")
    limit = mx if isinstance(mx, int) and not isinstance(mx, bool) and mx >= 1 else _MAX_FILES
    if len(ids) > limit:
        return [], [{"key": f["key"], "message": "%s：最多 %d 個檔案" % (label, limit)}]
    return ids, []


def check_files(conn, module_key, body, vals, username, rec_id=0) -> list:
    """寫入前驗證：每個 id 要是這個模組這個欄位的檔，且是自己暫存的或已綁在這張單（`rec_id`）。回錯誤清單。"""
    errors = []
    for f in _file_fields(body):
        ids = vals.get(f["key"]) or []
        for i in ids:
            r = conn.execute("SELECT field, record_id, uploaded_by, filename FROM custom_record_files WHERE id=? AND module_key=?",
                             (i, module_key)).fetchone()
            ok = r is not None and r["field"] == f["key"] and (
                (r["record_id"] == 0 and r["uploaded_by"] == username) or (rec_id and r["record_id"] == rec_id))
            if not ok:
                errors.append({"key": f["key"], "message": "%s：找不到這個檔案（%s），請重新上傳" % (f.get("label") or f["key"], i)})
    return errors


def bind_files(conn, module_key, body, vals, rec_id, previous=None) -> list:
    """存檔後（同一個交易內）：值裡的檔綁到這張單；`previous`（舊值）有而新值沒有的 ⇒ 刪列。
    回「要在 commit 之後刪的實體路徑」清單（交易失敗就不刪）。"""
    doomed = []
    now = _now()
    for f in _file_fields(body):
        cur = set(vals.get(f["key"]) or [])
        for i in cur:
            conn.execute("UPDATE custom_record_files SET record_id=?, bound_at=CASE WHEN bound_at='' THEN ? ELSE bound_at END WHERE id=? AND module_key=?",
                         (rec_id, now, i, module_key))
        for i in set((previous or {}).get(f["key"]) or []) - cur:
            r = conn.execute("SELECT path FROM custom_record_files WHERE id=? AND module_key=? AND record_id=?", (i, module_key, rec_id)).fetchone()
            if r is not None:
                conn.execute("DELETE FROM custom_record_files WHERE id=?", (i,))
                doomed.append(r["path"])
    return doomed


def purge_stale_staged(conn, hours=48) -> int:
    """上傳後一直沒綁單的暫存檔（放棄的表單）：超過 `hours` 小時 ⇒ 刪列與實體檔。上傳端點順手呼叫。回刪除個數。"""
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")
    rows = conn.execute("SELECT id, path FROM custom_record_files WHERE record_id=0 AND uploaded_at < ?", (cutoff,)).fetchall()
    for r in rows:
        conn.execute("DELETE FROM custom_record_files WHERE id=?", (r["id"],))
    conn.commit()
    for r in rows:
        _remove_physical(r["path"])
    return len(rows)


def remove_files(paths):
    """commit 之後刪實體檔。"""
    for p in paths or []:
        _remove_physical(p)


def file_meta(conn, module_key, ids) -> dict:
    """id 清單 ⇒ `{id: {id, filename, size, mime, path}}`（查不到的不列）。"""
    ids = [i for i in ids if isinstance(i, str)]
    if not ids:
        return {}
    rows = conn.execute("SELECT id, filename, size, mime, path FROM custom_record_files WHERE module_key=? AND id IN (%s)"
                        % ",".join("?" * len(ids)), [module_key] + ids).fetchall()
    return {r["id"]: dict(r) for r in rows}


def files_of_field(conn, module_key, body, data) -> dict:
    """單據資料 ⇒ `{欄位: [file meta…]}`（依值的順序；查不到的檔略過）。"""
    out = {}
    for f in _file_fields(body):
        ids = [x.get("id") if isinstance(x, dict) else x for x in (data.get(f["key"]) or [])]
        if not ids:
            continue
        m = file_meta(conn, module_key, ids)
        out[f["key"]] = [m[i] for i in ids if i in m]
    return out


def view_names(body, meta) -> dict:
    """輸出用：`{欄位: [檔名…]}`（版型只顯示檔名，不放連結）。"""
    return {k: [m["filename"] for m in v] for k, v in meta.items()}


class CustomFilesAccess:
    """`uploads.path_access`（IP-104）：`custom_records/<模組>/<檔>` ＝自訂模組附件。
    暫存（record_id＝0）⇒ 只有上傳者；已綁單 ⇒ 看得到該模組（模組權限，或引用這個檔的某張單據的簽核人／代理人）且看得到該欄位。"""
    FOLDERS = (FOLDER,)

    @staticmethod
    def readable(conn, folder, rest, user):
        if len(rest) != 2:
            return False
        want = (folder, tuple(rest))
        rows = conn.execute("SELECT * FROM custom_record_files WHERE path LIKE ?", ("%" + rest[-1],)).fetchall()
        row = next((r for r in rows if _up.upload_owner(r["path"]) == want), None)
        if row is None:
            return False
        if row["record_id"] == 0:
            return row["uploaded_by"] == user.get("username")
        from . import custom_modules as CM
        try:
            d = CM._load_def(conn, row["module_key"])
        except CM.CustomModuleError:
            return False
        field = next((f for f in d["body"].get("fields", []) if isinstance(f, dict) and f.get("key") == row["field"]), None)
        if field is not None and not _S.can_see_field(field, user):
            return False
        if user.get("role") == "superadmin":
            return True
        try:
            mods = set(json.loads(user.get("modules") or "[]"))
        except (TypeError, ValueError):
            mods = set()
        if CM.permission_of(row["module_key"], d["body"]) in mods:
            return True
        from .tiered_approval import active_delegators_for
        names = {user.get("username")} | set(active_delegators_for(conn, user.get("username")))
        for r in conn.execute("SELECT approval_json FROM custom_records WHERE module_key=? AND data_json LIKE ?",
                              (row["module_key"], "%" + row["id"] + "%")).fetchall():
            try:
                a = json.loads(r["approval_json"] or "{}")
            except (TypeError, ValueError):
                continue
            if names & {x.get("username") for t in a.get("tiers", []) for x in t.get("approvers", [])}:
                return True
        return False
