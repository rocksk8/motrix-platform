"""單據原始版本存檔與編輯紀錄（2026-09-14 使用者要求：「產生當下自動備存一個，
如果有編修，需保留原始單據跟編輯紀錄在系統」）。

補的三個落差：
  ① **建立當下沒有備存**——原本只有簽核／已簽核／結案／解鎖編輯四個事件會存 PDF，
     「原始單據」那一份從來沒被留下來過。
  ② **存檔 PDF 會被覆蓋**——檔名只到「日」，同日同人第 20 次修改會靜默蓋掉
     當天的第一份，也就是最早、最該留的那一份。
  ③ **一般編輯沒有紀錄**——`editHistory` 原本只有解鎖編輯與精算存檔會寫，
     草稿階段改了幾次、誰改的、改了什麼，系統裡查不到。
"""
import json
import os

import pytest


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def su(client, make_user):
    u, p = make_user(role="superadmin")
    return _login(client, u, p)


@pytest.fixture
def pdf_jobs(monkeypatch):
    """攔下 PDF 產生（測試環境不保證有 Edge，而且不該真的跑 headless 瀏覽器），
    記錄下「誰被要求存了什麼事件的 PDF」。

    patch 的是 `routers.quotations` 上綁好的那個名字，不是 pdf_gen 原始出處——
    router 是 `from pdf_gen import _generate_quotation_pdf`，patch 出處不會影響
    它已經綁定的參照。
    """
    import routers.quotations as rq
    calls = []
    monkeypatch.setattr(rq, "_generate_quotation_pdf",
                        lambda quote_no, actor='', action_type='簽核':
                        calls.append({"no": quote_no, "actor": actor, "event": action_type}))
    return calls


def _create(client, headers, **over):
    payload = {
        "status": "草稿",
        "data": {
            "customerName": over.get("customerName", "京城凱悅"),
            "projectName":  over.get("projectName", "影視對講機"),
            "quoteDate":    "2026-09-14",
            "validDays":    30,
            "salesPerson":  "高晟耀",
            "items":        over.get("items", []),
            "tot":          over.get("tot", {"total": 1000, "pretax": 952}),
        },
    }
    r = client.post("/api/quotations", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["quote_no"]


def _get_data(quote_no):
    from db import get_db
    conn = get_db()
    row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?",
                       (quote_no,)).fetchone()
    conn.close()
    return json.loads(row["data_json"] or "{}")


# ── ① 建立當下自動備存 ──────────────────────────────────────────────────────

def test_create_triggers_original_snapshot(client, su, pdf_jobs):
    no = _create(client, su)
    events = [c["event"] for c in pdf_jobs if c["no"] == no]
    assert "建立" in events, "建立報價單時必須自動備存一份原始單據"


def test_create_snapshot_records_the_actual_creator(client, su, pdf_jobs, make_user):
    """存檔要記真正的操作者（session），不是 client 送的 created_by——
    後者可以被任意冒名（2026-09-10 稽核已針對同一支端點修過建立者欄位）。"""
    u, p = make_user(username="tsai", role="superadmin")
    headers = _login(client, u, p)
    no = _create(client, headers)
    job = next(c for c in pdf_jobs if c["no"] == no and c["event"] == "建立")
    # make_user 把 display_name 設成 username，所以這裡驗的是「有沒有帶到
    # session 的身分」而不是字面上的中文名
    assert job["actor"] == "tsai"


# ── ② 存檔版本不會被覆蓋 ────────────────────────────────────────────────────

def test_archived_filename_includes_seconds(client, monkeypatch, tmp_path):
    """同一天、同一個人連續存檔多次，不可以寫到同一個檔名。

    觀測點是**磁碟上實際存在幾個檔案**，不是檔名字串長什麼樣——後者換個格式
    就要改測試，前者才是真正要保證的性質。
    """
    import pdf_gen

    monkeypatch.setattr(pdf_gen, "_get_pdf_base", lambda: str(tmp_path))
    monkeypatch.setattr(pdf_gen, "_get_edge_path", lambda: "edge.exe")
    monkeypatch.setattr(pdf_gen, "_build_quote_html", lambda *a, **k: "<html></html>")
    monkeypatch.setattr(pdf_gen, "_pdf_audit", lambda *a, **k: None)
    monkeypatch.setattr(pdf_gen, "_record_doc_version", lambda *a, **k: None)

    written = []

    def _fake_run(cmd, **kw):
        out = next(a.split("=", 1)[1] for a in cmd if a.startswith("--print-to-pdf="))
        with open(out, "wb") as f:
            f.write(b"%PDF-1.4 fake")
        written.append(out)
        return None

    # 2026-09-15：原本攔的是 `pdf_gen.subprocess.run`。Edge 的呼叫已收斂成
    # `helpers/startup.py::run_edge_pdf()`（semaphore ＋ 逾時 ＋ 逾時記 log 都在
    # 裡面，見該處說明），pdf_gen 不再自己碰 subprocess，所以改攔那一支。
    monkeypatch.setattr(pdf_gen, "run_edge_pdf", _fake_run)

    from db import get_db
    conn = get_db()
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
        "data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        ("MQ-202609-999", "草稿", "客戶", "專案", "{}", "2026-09-14", "2026-09-14"))
    conn.commit()
    conn.close()

    for _ in range(3):
        pdf_gen._generate_quotation_pdf("MQ-202609-999", "高晟耀", "修改")

    assert len(set(written)) == 3, "三次存檔應產生三個不同檔案，不可互相覆蓋"
    # ⚠️ 目錄名是 `date.today()`，**不可以寫死日期**——初稿寫死 "2026-09-14"，
    # 跨過午夜之後這題就紅了（2026-09-15 實際踩到）。
    from datetime import date as _date
    day_dir = tmp_path / _date.today().isoformat()
    assert len(os.listdir(day_dir)) == 3


def test_record_doc_version_appends_index_to_data_json(client, tmp_path, monkeypatch):
    """索引寫進單據自己的 data_json，不是只寫 audit_log——audit_log 有 730 天
    保留期，兩年後索引會消失、檔案卻還在，等於有備存卻找不到。"""
    import pdf_gen
    from db import get_db

    monkeypatch.setattr(pdf_gen, "_get_pdf_base", lambda: str(tmp_path))
    day = tmp_path / "2026-09-14"
    day.mkdir()
    pdf = day / "MQ-202609-001_建立_20260914_210300_高晟耀.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    conn = get_db()
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
        "data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        ("MQ-202609-001", "草稿", "客戶", "專案", "{}", "2026-09-14", "2026-09-14"))
    conn.commit()
    conn.close()

    pdf_gen._record_doc_version("MQ-202609-001", "建立", "高晟耀", str(pdf))

    versions = _get_data("MQ-202609-001")["docVersions"]
    assert len(versions) == 1
    v = versions[0]
    assert v["seq"] == 1 and v["event"] == "建立" and v["by"] == "高晟耀"
    assert v["size"] == len(b"%PDF-1.4 fake")
    # 相對路徑，不是絕對路徑——pdf_base_path 是 superadmin 可改的設定，
    # 存絕對路徑會在改設定那天整批失效
    assert not os.path.isabs(v["file"])
    assert v["file"].startswith("2026-09-14/")


# ── ③ 一般編輯留下編輯紀錄 ──────────────────────────────────────────────────

def test_normal_edit_records_changed_fields(client, su, pdf_jobs):
    no = _create(client, su)
    data = _get_data(no)
    data["customerName"] = "台北凱悅"
    data["tot"] = {"total": 2000, "pretax": 1905}

    r = client.put(f"/api/quotations/{no}", json={"status": "草稿", "data": data}, headers=su)
    assert r.status_code == 200, r.text

    history = _get_data(no)["editHistory"]
    assert len(history) == 1
    entry = history[0]
    assert entry["type"] == "quote_update"
    fields = {c["field"] for c in entry["changes"]}
    assert "客戶名稱" in fields and "含稅總額" in fields
    change = next(c for c in entry["changes"] if c["field"] == "客戶名稱")
    assert change["from"] == "京城凱悅" and change["to"] == "台北凱悅"


def test_no_op_save_does_not_pollute_history(client, su, pdf_jobs):
    """autoSave 跟手動存檔共用同一支端點，每次都寫一筆會讓紀錄被無意義條目
    淹沒，真正的修改反而查不到。"""
    no = _create(client, su)
    data = _get_data(no)

    for _ in range(3):
        r = client.put(f"/api/quotations/{no}", json={"status": "草稿", "data": data}, headers=su)
        assert r.status_code == 200, r.text

    assert _get_data(no).get("editHistory", []) == []


def test_untracked_field_change_is_still_recorded(client, su, pdf_jobs):
    """改到追蹤清單外的欄位不會被逐一列出（那等於把整份 data_json 抄進紀錄），
    但**也不可以被靜默忽略**——至少要留下「這個時間點有人動過」。"""
    no = _create(client, su)
    data = _get_data(no)
    data["某個沒被追蹤的欄位"] = "有人改了這裡"

    r = client.put(f"/api/quotations/{no}", json={"status": "草稿", "data": data}, headers=su)
    assert r.status_code == 200, r.text

    history = _get_data(no)["editHistory"]
    assert len(history) == 1
    assert history[0]["changes"][0]["field"] == "其他內容"


def test_edit_history_records_who(client, su, pdf_jobs, make_user):
    no = _create(client, su)
    u, p = make_user(username="huang", role="superadmin")
    other = _login(client, u, p)

    data = _get_data(no)
    data["projectName"] = "門禁系統"
    r = client.put(f"/api/quotations/{no}", json={"status": "草稿", "data": data}, headers=other)
    assert r.status_code == 200, r.text

    entry = _get_data(no)["editHistory"][0]
    assert entry["by"] == "huang" and entry["byDisplay"] == "huang"


# ── 查詢端點 ────────────────────────────────────────────────────────────────

def test_versions_endpoint_returns_both_timelines(client, su, pdf_jobs, tmp_path, monkeypatch):
    import pdf_gen
    import routers.quotations as rq
    # 兩個模組各自綁了一份 _get_pdf_base 參照（router 是 from pdf_gen import ...），
    # 只 patch 其中一邊，端點解析到的會是真實設定路徑、檔案當然找不到
    monkeypatch.setattr(pdf_gen, "_get_pdf_base", lambda: str(tmp_path))
    monkeypatch.setattr(rq, "_get_pdf_base", lambda: str(tmp_path))

    no = _create(client, su)
    data = _get_data(no)
    data["projectName"] = "改過的專案"
    client.put(f"/api/quotations/{no}", json={"status": "草稿", "data": data}, headers=su)

    day = tmp_path / "2026-09-14"
    day.mkdir()
    pdf = day / f"{no}_建立_20260914_210300_高晟耀.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    pdf_gen._record_doc_version(no, "建立", "高晟耀", str(pdf))

    r = client.get(f"/api/quotations/{no}/versions", headers=su)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["versions"]) == 1
    assert body["versions"][0]["event"] == "建立"
    assert body["versions"][0]["available"] is True
    assert len(body["history"]) == 1
    assert body["history"][0]["type"] == "quote_update"


def test_version_marked_unavailable_when_file_is_gone(client, su, pdf_jobs, tmp_path, monkeypatch):
    """PDF 存檔目錄是可設定的路徑，可能被搬走或清理。索引還在但檔案沒了要
    誠實標示，不能讓人點下去才發現。"""
    import pdf_gen
    import routers.quotations as rq
    monkeypatch.setattr(pdf_gen, "_get_pdf_base", lambda: str(tmp_path))
    monkeypatch.setattr(rq, "_get_pdf_base", lambda: str(tmp_path))

    no = _create(client, su)
    day = tmp_path / "2026-09-14"
    day.mkdir()
    pdf = day / f"{no}_建立_20260914_210300_高晟耀.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    pdf_gen._record_doc_version(no, "建立", "高晟耀", str(pdf))
    os.remove(pdf)

    r = client.get(f"/api/quotations/{no}/versions", headers=su)
    assert r.json()["versions"][0]["available"] is False


def test_download_returns_the_archived_file_not_a_fresh_render(client, su, pdf_jobs,
                                                                tmp_path, monkeypatch):
    """這是整個功能的重點：要拿到的是**當時那一份**，不是用現在的內容重新產生。"""
    import pdf_gen
    import routers.quotations as rq
    monkeypatch.setattr(pdf_gen, "_get_pdf_base", lambda: str(tmp_path))
    monkeypatch.setattr(rq, "_get_pdf_base", lambda: str(tmp_path))

    no = _create(client, su)
    day = tmp_path / "2026-09-14"
    day.mkdir()
    pdf = day / f"{no}_建立_20260914_210300_高晟耀.pdf"
    pdf.write_bytes(b"%PDF-1.4 ORIGINAL CONTENT")
    pdf_gen._record_doc_version(no, "建立", "高晟耀", str(pdf))

    # 之後把單據內容改掉——下載回來的仍必須是原始那一份
    data = _get_data(no)
    data["customerName"] = "完全不同的客戶"
    client.put(f"/api/quotations/{no}", json={"status": "草稿", "data": data}, headers=su)

    r = client.get(f"/api/quotations/{no}/versions/1/download", headers=su)
    assert r.status_code == 200, r.text
    assert r.content == b"%PDF-1.4 ORIGINAL CONTENT"
    assert r.headers["content-type"] == "application/pdf"


def test_download_unknown_seq_is_404(client, su, pdf_jobs):
    no = _create(client, su)
    r = client.get(f"/api/quotations/{no}/versions/99/download", headers=su)
    assert r.status_code == 404


def test_version_path_traversal_is_rejected(client, su, pdf_jobs, tmp_path, monkeypatch):
    """docVersions 的值是系統自己寫的，但會經過 data_json（備份、還原、人工
    修過的資料都可能經手）。照 routers/uploads.py `_resolve_upload_path()`
    的既有慣例一律驗界。"""
    import routers.quotations as rq
    monkeypatch.setattr(rq, "_get_pdf_base", lambda: str(tmp_path))

    no = _create(client, su)
    from db import get_db
    conn = get_db()
    data = _get_data(no)
    data["docVersions"] = [{"seq": 1, "at": "2026-09-14T00:00:00", "event": "建立",
                            "by": "x", "file": "../../../backend/motrix_erp.db", "size": 1}]
    conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?",
                 (json.dumps(data, ensure_ascii=False), no))
    conn.commit()
    conn.close()

    r = client.get(f"/api/quotations/{no}/versions/1/download", headers=su)
    assert r.status_code == 404, "越界路徑必須被擋下，不能真的送出檔案"
