import json, os
import db
from helpers import custom_module_delete as MD
from helpers import uploads as UP


def _seed(conn, key, paths):
    conn.execute("INSERT INTO ui_definitions(kind,key,scope,version,status,body_json) VALUES ('custom_module',?, 'company',1,'published','{}')", (key,))
    cur = conn.execute("INSERT INTO custom_records(module_key,record_no,def_version,status) VALUES (?,?,1,'草稿')", (key, key + "-1"))
    for i, p in enumerate(paths):
        conn.execute("INSERT INTO custom_record_files(id,module_key,field,record_id,path) VALUES (?,?,?,?,?)", ("f%d" % i, key, "f", cur.lastrowid, p))
    conn.commit()


def test_q4(client, tmp_path, monkeypatch):
    root = tmp_path / "uploads"; root.mkdir()
    outside = tmp_path / "outside.txt"; outside.write_text("keep me")
    outside2 = tmp_path / "outside2.txt"; outside2.write_text("keep me too")
    inside = root / "custom" / "pq4"; inside.mkdir(parents=True)
    (inside / "ok.txt").write_text("inside")
    monkeypatch.setattr(UP, "UPLOADS_ROOT", str(root))
    conn = db.get_db()
    try:
        _seed(conn, "pq4", ["custom/pq4/ok.txt", str(outside), "../outside2.txt"])
        r = MD.delete_module(conn, "pq4", with_records=True)
    finally:
        conn.close()
    print("Q4 RESULT", r, "inside_exists", (inside / "ok.txt").exists(), "outside_exists", outside.exists(), "outside2_exists", outside2.exists())
    assert not (inside / "ok.txt").exists()          # 正對照：根目錄內的檔會被刪
    assert outside.exists() and outside2.exists(), "ESCAPE: file outside UPLOADS_ROOT was deleted"
