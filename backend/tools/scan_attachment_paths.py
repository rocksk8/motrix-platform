# -*- coding: utf-8 -*-
"""附件路徑舊資料掃描（唯讀）——找出「檔案 metadata 的 `path` 不在該文件自己資料夾底下」的資料列。

背景（安全複驗 #1 ISSUE-2，2026-09-30）：`/api/attachments/open` 與案件紀錄寫入端已綁單據資料夾，
但傳票的 `line-source-file`／帶入（`resolve_picks`）仍信任資料庫裡存的 `path`；修正前就存在的舊列若含
別處的路徑，仍可被讀到。這支腳本在正式機資料庫上數出那些列，供決定要不要清。

用法：
  python backend\\tools\\scan_attachment_paths.py [--db <motrix_erp.db>] [--root <安裝目錄>] [--out <輸出.json>]

🔴 嚴格唯讀：只以 sqlite URI `mode=ro` 開庫、只有標準函式庫、不 import 產品程式（不寫 __pycache__、不觸發 import main 的副作用）、
不碰 uploads 檔案系統（只看路徑字串，不檢查檔在不在）。唯一的寫入是 --out（先 .tmp 再 os.replace；不可在安裝目錄內）。
輸出只含：各來源的掃描筆數、可疑筆數（分原因）、至多 5 個遮罩範例（來源／文件 id／原因／第幾個檔）——
**不含檔名、路徑內容、客戶名**。結束碼一律 0（來源讀不到記在 errors）；看 `total_suspect`。

判定（與 `helpers.uploads.upload_path_key` 同規則；去掉 demo 前綴 `_demo_uploads/`、`_demo_projects/`→`projects/`）：
  malformed      絕對路徑、磁碟代號／冒號、反斜線、NUL、`.`／`..`／空段、少於兩段、不是字串
  wrong_folder   第一段資料夾不是該來源該用的
  wrong_depth    資料夾之後的段數不對（資料夾之後的段數：單據鍵＋檔名＝2；工作日誌照片 `<worklog_id>/<日期>/<檔名>`＝3）
  wrong_doc      資料夾對、單據鍵不是這份文件（案件類：同案件；額外支出：`<案件>_<id>`；派工／開發案／日誌：id）
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

sys.dont_write_bytecode = True

SCHEMA = 1
DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BAD_CHARS = ("\\", ":", "\x00")
_DEMO = {"_demo_uploads": None, "_demo_projects": "projects"}
MAX_EXAMPLES = 5


def classify(entry, folder, depth, key_ok):
    """entry（metadata 一筆）⇒ None（正常）或原因字串。`key_ok(單據鍵)` 決定單據鍵對不對。"""
    raw = entry.get("path") if isinstance(entry, dict) else None
    if not isinstance(raw, str) or not raw or raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        return "malformed"
    if any(c in raw for c in _BAD_CHARS):
        return "malformed"
    segs = raw.split("/")
    if len(segs) < 2 or any((not s) or s in (".", "..") for s in segs):
        return "malformed"
    if segs[0] in _DEMO:
        alias = _DEMO[segs[0]]
        segs = ([alias] if alias else []) + segs[1:]
        if len(segs) < 2:
            return "malformed"
    if segs[0] != folder:
        return "wrong_folder"
    if len(segs) - 1 != depth:
        return "wrong_depth"
    return None if key_ok(segs[1]) else "wrong_doc"


def _quote_of_key(key):
    """`{案件編號}_{索引或id}` ⇒ 案件編號（從右邊切；報價單號含 `-` 不含 `_`）。"""
    base, sep, tail = key.rpartition("_")
    return base if sep and tail.isdigit() else key


class Report:
    def __init__(self):
        self.sources = {}
        self.errors = {}

    def src(self, name):
        return self.sources.setdefault(name, {"scanned": 0, "suspect": 0, "reasons": {}, "examples": []})

    def hit(self, name, doc_id, idx, reason):
        s = self.src(name)
        s["suspect"] += 1
        s["reasons"][reason] = s["reasons"].get(reason, 0) + 1
        if len(s["examples"]) < MAX_EXAMPLES:
            s["examples"].append({"doc": str(doc_id), "file_index": idx, "reason": reason})


def _files(rep, name, doc_id, raw_json):
    """JSON 欄 ⇒ 檔案 metadata 清單；壞 JSON 記 `json_bad`（算一筆可疑）。"""
    if raw_json in (None, "", "[]"):
        return []
    try:
        v = json.loads(raw_json)
    except (TypeError, ValueError):
        rep.src(name)["scanned"] += 1
        rep.hit(name, doc_id, -1, "json_bad")
        return []
    return v if isinstance(v, list) else []


def _scan_list(rep, name, doc_id, files, folder, depth, key_ok):
    for i, e in enumerate(files):
        rep.src(name)["scanned"] += 1
        r = classify(e, folder, depth, key_ok)
        if r:
            rep.hit(name, doc_id, i, r)


def _rows(conn, rep, name, sql):
    try:
        return conn.execute(sql).fetchall()
    except sqlite3.Error as e:
        rep.errors[name] = "%s: %s" % (type(e).__name__, e)
        return []


def scan(conn):
    rep = Report()

    # 案件：報價單回簽（quotations.signed_files_json）＋ caseRecord 內的三類
    for qn, sj, dj in _rows(conn, rep, "quotations", "SELECT quote_no, signed_files_json, data_json FROM quotations"):
        _scan_list(rep, "quotation_signed", qn, _files(rep, "quotation_signed", qn, sj), "quotations", 2,
                   lambda k, qn=qn: k == qn)
        try:
            cr = (json.loads(dj or "{}") or {}).get("caseRecord") or {}
        except (TypeError, ValueError):
            rep.src("case_record")["scanned"] += 1
            rep.hit("case_record", qn, -1, "json_bad")
            continue
        if not isinstance(cr, dict):
            continue
        same_case = lambda k, qn=qn: _quote_of_key(k) == qn
        for m in ((cr.get("materials") or []) if isinstance(cr.get("materials"), list) else []):
            if not isinstance(m, dict):
                continue
            _scan_list(rep, "material", qn, m.get("files") if isinstance(m.get("files"), list) else [], "quotation_materials", 2, same_case)
            _scan_list(rep, "material_invoice", qn, m.get("invoiceFiles") if isinstance(m.get("invoiceFiles"), list) else [],
                       "quotation_materials_invoices", 2, same_case)
        pay = cr.get("payment") if isinstance(cr.get("payment"), dict) else {}
        for it in (pay.get("items") or []) if isinstance(pay.get("items"), list) else []:
            if isinstance(it, dict):
                _scan_list(rep, "payment_item", qn, it.get("invoiceFiles") if isinstance(it.get("invoiceFiles"), list) else [],
                           "quotation_payment_items", 2, same_case)

    for cid, qn, fj in _rows(conn, rep, "case_updates", "SELECT id, quote_no, files_json FROM case_updates"):
        _scan_list(rep, "case_update", "%s#%s" % (qn, cid), _files(rep, "case_update", "%s#%s" % (qn, cid), fj), "case_updates", 2,
                   lambda k, qn=qn: k == qn)

    for eid, qn, fj in _rows(conn, rep, "extra_expense", "SELECT id, quote_no, files_json FROM case_extra_expenses"):
        _scan_list(rep, "extra_expense", eid, _files(rep, "extra_expense", eid, fj), "case_extra_expense", 2,
                   lambda k, qn=qn, eid=eid: k == "%s_%s" % (qn, eid))

    for did, fj, ij in _rows(conn, rep, "contractor_dispatches", "SELECT id, files_json, invoice_files_json FROM contractor_dispatches"):
        _scan_list(rep, "contractor_dispatch", did, _files(rep, "contractor_dispatch", did, fj), "contractor_dispatches", 2,
                   lambda k, did=did: k == str(did))
        _scan_list(rep, "contractor_invoice", did, _files(rep, "contractor_invoice", did, ij), "contractor_dispatch_invoices", 2,
                   lambda k, did=did: k == str(did))

    for lid, cid, fj in _rows(conn, rep, "dev_logs", "SELECT id, case_id, files_json FROM dev_logs"):
        _scan_list(rep, "dev_log", lid, _files(rep, "dev_log", lid, fj), "dev_logs", 2, lambda k, cid=cid: k == str(cid))

    for wid, pj in _rows(conn, rep, "work_logs", "SELECT id, photos FROM work_logs"):
        _scan_list(rep, "work_log_photo", wid, _files(rep, "work_log_photo", wid, pj), "projects", 3,
                   lambda k, wid=wid: k == "worklog_%s" % wid)
    return rep


def build_result(db_path):
    uri = "file:%s?mode=ro" % db_path.replace("\\", "/").replace("?", "%3f").replace("#", "%23")
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        conn.execute("PRAGMA query_only = 1")
        rep = scan(conn)
    finally:
        conn.close()
    total = sum(s["suspect"] for s in rep.sources.values())
    return {"schema": SCHEMA, "generated_at": datetime.now().isoformat(timespec="seconds"),
            "total_scanned": sum(s["scanned"] for s in rep.sources.values()), "total_suspect": total,
            "sources": rep.sources, "errors": rep.errors}


def main(argv=None):
    ap = argparse.ArgumentParser(description="附件路徑舊資料掃描（唯讀）")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="安裝目錄（預設：本檔往上三層）")
    ap.add_argument("--db", default="", help="資料庫路徑（預設 <root>\\backend\\motrix_erp.db）")
    ap.add_argument("--out", default="", help="輸出 JSON（不可在安裝目錄內）")
    a = ap.parse_args(argv)
    db = a.db or os.path.join(a.root, "backend", "motrix_erp.db")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                            # noqa: BLE001
        pass
    if not os.path.isfile(db):
        res = {"schema": SCHEMA, "generated_at": datetime.now().isoformat(timespec="seconds"), "total_scanned": 0, "total_suspect": 0,
               "sources": {}, "errors": {"db": "找不到資料庫檔"}}
    else:
        try:
            res = build_result(db)
        except sqlite3.Error as e:
            res = {"schema": SCHEMA, "generated_at": datetime.now().isoformat(timespec="seconds"), "total_scanned": 0, "total_suspect": 0,
                   "sources": {}, "errors": {"db": "%s: %s" % (type(e).__name__, e)}}
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        out = os.path.abspath(a.out)
        root = os.path.abspath(a.root)
        if os.path.normcase(out).startswith(os.path.normcase(root) + os.sep):
            print("--out 不可在安裝目錄內：%s" % out, file=sys.stderr)
        else:
            tmp = out + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, out)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
