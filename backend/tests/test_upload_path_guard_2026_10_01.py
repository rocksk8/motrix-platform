# -*- coding: utf-8 -*-
"""自訂單據附件的實體刪除只准在 UPLOADS_ROOT 之內（稽核探針 Q4，2026-10-01）：

`custom_record_files.path` 是資料庫欄位——絕對路徑、`../`、`..\\`（Windows）、磁碟機代號／UNC、NTFS 資料流、符號連結都不能把「刪檔」帶到
uploads 之外。涵蓋兩個入口：`custom_module_delete.delete_module`（刪模組連單據）與 `custom_files._remove_physical`（刪暫存檔）。
正對照：根目錄內的檔照刪。反向控制：把守門換回舊寫法（`os.path.join` 後直接刪）⇒ 同一個測試床會刪到外面的檔（`test_the_old_code_would_have_deleted_outside`）。
"""
import os

import pytest

import db
from helpers import custom_files as CF
from helpers import custom_module_delete as MD
from helpers import uploads as UP


@pytest.fixture
def bed(tmp_path, monkeypatch):
    root = tmp_path / "uploads"
    (root / "custom" / "pq4").mkdir(parents=True)
    (root / "custom" / "pq4" / "ok.txt").write_text("inside")
    outside = tmp_path / "outside.txt"
    outside.write_text("keep me")
    outside2 = tmp_path / "outside2.txt"
    outside2.write_text("keep me too")
    monkeypatch.setattr(UP, "UPLOADS_ROOT", str(root))
    return root, outside, outside2


# ── 純函式 ──────────────────────────────────────────────────────────────────

def test_safe_physical_path_accepts_only_files_under_the_root(bed):
    root, outside, outside2 = bed
    ok = CF._safe_physical_path("custom/pq4/ok.txt")
    assert ok is not None and os.path.samefile(ok, root / "custom" / "pq4" / "ok.txt")                       # 正對照
    assert CF._safe_physical_path("custom\\pq4\\ok.txt") is not None                                         # Windows 風格的合法相對路徑
    hostile = [str(outside), str(outside).replace("\\", "/"), "../outside2.txt", "..\\outside2.txt", "custom/../../outside2.txt",
               "custom\\..\\..\\outside2.txt", "/etc/passwd", "\\\\host\\share\\x", "C:\\Windows\\win.ini", "C:/Windows/win.ini",
               "custom/pq4/ok.txt:stream", "", ".", "..", "custom/./pq4/ok.txt", "custom//pq4/ok.txt", None]
    for h in hostile:
        assert CF._safe_physical_path(h) is None, h
    assert CF._safe_physical_path("custom") is not None and os.path.isdir(CF._safe_physical_path("custom"))   # 目錄在根內（刪的人另有 isfile 檢查）
    assert CF._safe_physical_path("custom/pq4/not-there.txt") is not None                                    # 不存在的檔在根內 ⇒ 路徑合法（刪除時 isfile 為假）


def test_a_symlink_inside_the_root_that_points_outside_is_refused(bed, tmp_path):
    root, outside, _o2 = bed
    link = root / "custom" / "pq4" / "link.txt"
    try:
        os.symlink(str(outside), str(link))
    except (OSError, NotImplementedError, AttributeError) as e:         # Windows 一般使用者沒有建符號連結的權限：照實標明，不當成通過
        pytest.skip("這台無法建立符號連結（%s）——此題在有權限的環境才有意義" % type(e).__name__)
    assert CF._safe_physical_path("custom/pq4/link.txt") is None


def test_case_variants_of_an_inside_path_stay_inside_and_never_reach_outside(bed):
    root, outside, _o2 = bed
    p = CF._safe_physical_path("CUSTOM/PQ4/OK.TXT")                       # Windows 大小寫不分：仍是根內那個檔（或 None），絕不是外面的
    assert p is None or os.path.normcase(p).startswith(os.path.normcase(os.path.realpath(str(root))))


def test_a_junction_inside_the_root_that_points_outside_is_refused(client, bed, tmp_path):
    """Windows 的目錄接合點（mklink /J，不需要系統管理員）：根內一個目錄其實指到根外 ⇒ realpath 會穿出去 ⇒ 必須拒絕。"""
    import subprocess
    root, _o, _o2 = bed
    outdir = tmp_path / "outdir"
    outdir.mkdir()
    (outdir / "secret.txt").write_text("keep me")
    jn = root / "custom" / "jn"
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(jn), str(outdir)], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("無法建立目錄接合點：%s" % (r.stdout + r.stderr).strip()[:80])
    assert os.path.isfile(root / "custom" / "jn" / "secret.txt")                       # 接合點真的穿出去了（測試床有效）
    assert CF._safe_physical_path("custom/jn/secret.txt") is None
    conn = db.get_db()
    try:
        _seed(conn, "pq5", ["custom/jn/secret.txt"])
        MD.delete_module(conn, "pq5", with_records=True)
    finally:
        conn.close()
    assert (outdir / "secret.txt").exists(), "ESCAPE：接合點被穿出 uploads"


# ── 入口 1：刪模組連單據（探針 Q4 原題）────────────────────────────────────

def _seed(conn, key, paths):
    conn.execute("INSERT INTO ui_definitions(kind,key,scope,version,status,body_json) VALUES ('custom_module',?, 'company',1,'published','{}')", (key,))
    cur = conn.execute("INSERT INTO custom_records(module_key,record_no,def_version,status) VALUES (?,?,1,'草稿')", (key, key + "-1"))
    for i, p in enumerate(paths):
        conn.execute("INSERT INTO custom_record_files(id,module_key,field,record_id,path) VALUES (?,?,?,?,?)", ("f%d" % i, key, "f", cur.lastrowid, p))
    conn.commit()


def test_delete_module_removes_inside_files_and_never_touches_outside_ones(client, bed):
    root, outside, outside2 = bed
    conn = db.get_db()
    try:
        _seed(conn, "pq4", ["custom/pq4/ok.txt", str(outside), "../outside2.txt", "..\\outside2.txt", str(root.parent)])
        r = MD.delete_module(conn, "pq4", with_records=True)
    finally:
        conn.close()
    assert r["records"] == 1
    assert not (root / "custom" / "pq4" / "ok.txt").exists()               # 正對照：根內的檔被刪
    assert outside.exists() and outside2.exists(), "ESCAPE：uploads 之外的檔被刪了"
    assert root.parent.exists()


# ── 入口 2：刪暫存檔 ────────────────────────────────────────────────────────

def test_remove_staged_does_not_delete_outside_files(client, bed):
    root, outside, _o2 = bed
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO custom_record_files(id,module_key,field,record_id,path,uploaded_by) VALUES (?,?,?,?,?,?)",
                     ("s1", "pq4", "f", 0, str(outside), "alice"))
        conn.execute("INSERT INTO custom_record_files(id,module_key,field,record_id,path,uploaded_by) VALUES (?,?,?,?,?,?)",
                     ("s2", "pq4", "f", 0, "custom/pq4/ok.txt", "alice"))
        conn.commit()
        assert CF.remove_staged(conn, "pq4", "s1", "alice") is True        # 列照刪（使用者要的是刪暫存），但實體檔不能被帶出去刪
        assert CF.remove_staged(conn, "pq4", "s2", "alice") is True
    finally:
        conn.close()
    assert outside.exists(), "ESCAPE：remove_staged 刪到 uploads 之外"
    assert not (root / "custom" / "pq4" / "ok.txt").exists()


# ── 反向控制：舊寫法會刪到外面 ───────────────────────────────────────────────

def test_the_old_code_would_have_deleted_outside(bed):
    """證明上面的測試床抓得到：把舊寫法（join 後直接刪）放進同一張床 ⇒ 外面的檔真的被刪。"""
    root, outside, outside2 = bed
    for p in (str(outside), "../outside2.txt"):
        full = os.path.join(UP.UPLOADS_ROOT, p)
        if os.path.isfile(full):
            os.remove(full)
    assert not outside.exists() and not outside2.exists()
