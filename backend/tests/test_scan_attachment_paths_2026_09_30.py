# -*- coding: utf-8 -*-
"""tools/scan_attachment_paths.py：唯讀掃描附件 metadata 的 `path` 是否在該文件自己的資料夾底下（安全複驗 #1 ISSUE-2）。

正對照：每個來源各種一筆「別處的路徑」，掃描器必須逐一亮起；同時種正常列，必須不亮（否則「0 筆」沒有意義）。
"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys

TOOL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "scan_attachment_paths.py")
SECRET = "SECRETNAME-王大明.png"


def _f(path):
    return {"id": "f1", "filename": SECRET, "path": path}


def _make(db):
    c = sqlite3.connect(db)
    c.executescript("""
    CREATE TABLE quotations (quote_no TEXT, signed_files_json TEXT, data_json TEXT);
    CREATE TABLE case_updates (id INTEGER, quote_no TEXT, files_json TEXT);
    CREATE TABLE case_extra_expenses (id INTEGER, quote_no TEXT, files_json TEXT);
    CREATE TABLE contractor_dispatches (id INTEGER, files_json TEXT, invoice_files_json TEXT);
    CREATE TABLE dev_logs (id INTEGER, case_id INTEGER, files_json TEXT);
    CREATE TABLE work_logs (id INTEGER, photos TEXT);
    """)
    J = json.dumps
    ok = {"quotations": "quotations/MQ-1/a.png", "mat": "quotation_materials/MQ-1_0/a.png", "matinv": "quotation_materials_invoices/MQ-1_3/a.png",
          "pay": "quotation_payment_items/MQ-1_1/a.png"}
    cr = {"materials": [{"files": [_f(ok["mat"]), _f("voucher_attachments/77/x.png")], "invoiceFiles": [_f(ok["matinv"]), _f("../../etc/passwd")]}],
          "payment": {"items": [{"invoiceFiles": [_f(ok["pay"]), _f("quotation_payment_items/MQ-2_1/a.png")]}]}}
    c.execute("INSERT INTO quotations VALUES (?,?,?)", ("MQ-1", J([_f(ok["quotations"]), _f("quotations/MQ-9/a.png")]), J({"caseRecord": cr})))
    c.execute("INSERT INTO case_updates VALUES (1,'MQ-1',?)", (J([_f("case_updates/MQ-1/a.png"), _f("C:/Windows/win.ini")]),))
    c.execute("INSERT INTO case_extra_expenses VALUES (5,'MQ-1',?)", (J([_f("case_extra_expense/MQ-1_5/a.png"), _f("case_extra_expense/MQ-1_6/a.png")]),))
    c.execute("INSERT INTO contractor_dispatches VALUES (7,?,?)", (J([_f("contractor_dispatches/7/a.png"), _f("contractor_dispatches/8/a.png")]),
                                                                    J([_f("contractor_dispatch_invoices/7/a.png"), _f("contractor_dispatches/7/a.png")])))
    c.execute("INSERT INTO dev_logs VALUES (3,42,?)", (J([_f("dev_logs/42/a.png"), _f("dev_logs\43\a.png")]),))
    c.execute("INSERT INTO work_logs VALUES (9,?)", (J([_f("projects/worklog_9/2026-09-30/a.png"), _f("projects/worklog_10/2026-09-30/a.png"),
                                                        _f("_demo_projects/worklog_9/2026-09-30/b.png")]),))
    c.commit()
    c.close()


def _run(*args):
    r = subprocess.run([sys.executable, TOOL, *args], capture_output=True, text=True, encoding="utf-8")
    return r


def test_planted_foreign_paths_are_found_per_source_and_clean_rows_are_not(tmp_path):
    db = str(tmp_path / "t.db")
    _make(db)
    r = _run("--db", db, "--root", str(tmp_path / "root"))
    assert r.returncode == 0, r.stderr
    res = json.loads(r.stdout)
    exp = {"quotation_signed": ("wrong_doc", 1, 2), "material": ("wrong_folder", 1, 2), "material_invoice": ("malformed", 1, 2), "payment_item": ("wrong_doc", 1, 2),
           "case_update": ("malformed", 1, 2), "extra_expense": ("wrong_doc", 1, 2), "contractor_dispatch": ("wrong_doc", 1, 2),
           "contractor_invoice": ("wrong_folder", 1, 2), "dev_log": ("malformed", 1, 2), "work_log_photo": ("wrong_doc", 1, 3)}
    for name, (reason, suspect, scanned) in exp.items():
        s = res["sources"][name]
        if name == "material":                                 # 材料：一個正常、一個 voucher_attachments ⇒ wrong_folder
            assert (s["suspect"], s["scanned"]) == (1, 2) and s["reasons"] == {"wrong_folder": 1}, s
            continue
        assert (s["suspect"], s["scanned"]) == (suspect, scanned), (name, s)
        assert reason in s["reasons"], (name, s)
    assert res["total_suspect"] == 10 and res["errors"] == {}, res


def test_output_has_no_filenames_and_examples_are_capped(tmp_path):
    db = str(tmp_path / "t.db")
    _make(db)
    c = sqlite3.connect(db)
    c.execute("INSERT INTO dev_logs VALUES (4,50,?)", (json.dumps([_f("x/y/%d.png" % i) for i in range(20)]),))
    c.commit()
    c.close()
    out = _run("--db", db, "--root", str(tmp_path / "root")).stdout
    assert SECRET not in out and "王大明" not in out and "win.ini" not in out and "passwd" not in out
    res = json.loads(out)
    assert len(res["sources"]["dev_log"]["examples"]) <= 5 and res["sources"]["dev_log"]["suspect"] >= 20


def test_scan_is_read_only_and_out_inside_root_is_refused(tmp_path):
    db = str(tmp_path / "t.db")
    _make(db)
    before = hashlib.sha256(open(db, "rb").read()).hexdigest()
    names = set(os.listdir(tmp_path))
    root = tmp_path / "root"
    root.mkdir()
    r = _run("--db", db, "--root", str(root), "--out", str(root / "o.json"))
    assert r.returncode == 0 and not (root / "o.json").exists()               # 安裝目錄內不寫
    out = tmp_path / "o.json"
    _run("--db", db, "--root", str(root), "--out", str(out))
    assert json.loads(out.read_text(encoding="utf-8"))["total_suspect"] == 10
    assert hashlib.sha256(open(db, "rb").read()).hexdigest() == before
    assert set(os.listdir(tmp_path)) == names | {"root", "o.json"}            # 沒有 -wal／-journal／.tmp 殘留


def test_missing_db_and_missing_tables_do_not_fail(tmp_path):
    r = _run("--db", str(tmp_path / "nope.db"), "--root", str(tmp_path))
    assert r.returncode == 0 and json.loads(r.stdout)["errors"]["db"]
    db = str(tmp_path / "empty.db")
    sqlite3.connect(db).close()
    r = _run("--db", db, "--root", str(tmp_path / "root"))
    res = json.loads(r.stdout)
    assert r.returncode == 0 and res["total_suspect"] == 0 and len(res["errors"]) >= 5


def test_reverse_control_a_broken_classifier_would_go_dark(tmp_path):
    """反向控制：把判定換成「全部正常」，正對照題必須變紅（證明上面的題不是恆真）。"""
    sys.path.insert(0, os.path.dirname(TOOL))
    import importlib
    T = importlib.import_module("scan_attachment_paths")
    db = str(tmp_path / "t.db")
    _make(db)
    good = T.build_result(db)["total_suspect"]
    orig = T.classify
    try:
        T.classify = lambda *a, **k: None
        assert T.build_result(db)["total_suspect"] == 0 != good
    finally:
        T.classify = orig
