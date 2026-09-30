# -*- coding: utf-8 -*-
"""去識別化 S1／S2：`deid_hashlist.py`（清單產生器）與 `deid_scan.py`（掃描器）。

本檔的識別值**全是虛構的**（示範公司、示範人名、example 網域）；不含任何本公司資料。
判準：清單檔裡找不到明文；掃描器對各種寫法（全形、分隔符、+886、HTML 實體、JSON \\u 跳脫、PNG 文字段）都掃得到；
輸出只有「路徑:行號:類別:值代碼」；換金鑰／清單過期／金絲雀缺失都會被擋。
"""
import json
import os
import sqlite3
import struct
import sys
import zlib
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import deid_hashlist as HL  # noqa: E402
import deid_scan as S  # noqa: E402

COMPANY = "示範資訊股份有限公司"
PERSON = "王示範"
CUSTOMER = "虛構客戶事業有限公司"
SUPPLIER = "假想供應行"
PHONE = "0412345678"
EMAIL = "boss@corp-demo.example"
ADDRESS = "臺中市西屯區示範路123號"
ACCOUNT = "1234567890123"


def _valid_tax():
    # 第 7 碼不能是 7（那是檢查碼的特例：兩個相鄰末碼會同時合法，做不出「錯的那一個」）
    return next("1234560%d" % d for d in range(10) if S.tw_tax_id_valid("1234560%d" % d))


TAX = _valid_tax()


@pytest.fixture
def key(tmp_path):
    p = tmp_path / "k" / "hmac.key"
    assert HL.main(["keygen", "--out", str(p)]) == 0
    return S.load_key(p)


@pytest.fixture
def db_copy(tmp_path):
    p = tmp_path / "backup.db"
    c = sqlite3.connect(p)
    c.executescript("""
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, tax_id TEXT, phone TEXT, data_json TEXT);
        CREATE TABLE suppliers (id INTEGER PRIMARY KEY, name TEXT, tax_id TEXT, phone TEXT);
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, display_name TEXT, email TEXT, phone TEXT);
        CREATE TABLE contractors (id INTEGER PRIMARY KEY, name TEXT, phone TEXT, email TEXT, address TEXT, bank_account_number TEXT, bank_account_name TEXT);
        CREATE TABLE system_settings (key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT);
    """)
    c.execute("INSERT INTO customers (name, tax_id, phone) VALUES (?,?,?)", (CUSTOMER, "", ""))
    c.execute("INSERT INTO suppliers (name) VALUES (?)", (SUPPLIER,))
    c.execute("INSERT INTO users (username, display_name, email, phone) VALUES ('u1', ?, ?, ?)", (PERSON, EMAIL, PHONE))
    c.execute("INSERT INTO contractors (name, address, bank_account_number) VALUES ('無', ?, ?)", (ADDRESS, ACCOUNT))
    c.execute("INSERT INTO system_settings VALUES ('company_profile', ?, 't')",
              (json.dumps({"name": COMPANY, "tax_id": TAX, "phone": PHONE, "email": EMAIL}, ensure_ascii=False),))
    c.commit()
    c.close()
    return p


def _export(tmp_path, db_copy, key, extra=None):
    out = tmp_path / "hashlist.json"
    args = ["export", "--db", str(db_copy), "--key", str(tmp_path / "k" / "hmac.key"), "--out", str(out)]
    if extra is not None:
        ex = tmp_path / "extra.json"
        ex.write_text(json.dumps(extra, ensure_ascii=False), encoding="utf-8")
        args += ["--extra", str(ex)]
    assert HL.main(args) == 0
    return out


def _tree(tmp_path, files):
    root = tmp_path / "pkg"
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            p.write_bytes(body)
        else:
            p.write_text(body, encoding="utf-8")
    return root


def _hl(tmp_path, db_copy, key, extra=None):
    return S.load_hashlist(_export(tmp_path, db_copy, key, extra), key)


# ── 金鑰與清單 ─────────────────────────────────────────────────────────────────

def test_keygen_refuses_to_overwrite_and_prints_only_path_and_key_id(tmp_path, capsys):
    p = tmp_path / "hmac.key"
    assert HL.main(["keygen", "--out", str(p)]) == 0
    out = capsys.readouterr().out
    k = p.read_bytes()
    assert len(k) == 32 and S.key_id(k) in out and k.hex() not in out and str(k) not in out
    assert HL.main(["keygen", "--out", str(p)]) == 1 and p.read_bytes() == k          # 已存在 ⇒ 拒絕、內容不變


def test_hashlist_file_contains_no_plaintext_and_has_the_canary(tmp_path, db_copy, key):
    out = _export(tmp_path, db_copy, key)
    raw = out.read_text(encoding="utf-8")
    for v in (COMPANY, PERSON, CUSTOMER, SUPPLIER, PHONE, EMAIL, ADDRESS, ACCOUNT, TAX, "corp-demo", "示範", "王"):
        assert v not in raw, "清單檔含明文：%r" % v
    for v in (S.normalize(x) for x in (COMPANY, PERSON, EMAIL, ADDRESS)):
        assert v not in raw
    data = json.loads(raw)
    assert data["v"] == 1 and data["key_id"] == S.key_id(key) and "created" in data
    assert set(data["source_counts"]) >= {"company", "person", "customer", "supplier", "phone", "taxid", "email", "address", "account", "canary"}
    assert S.canary_check(S.load_hashlist(out, key)) is None
    assert key.hex() not in raw


def test_export_opens_the_database_read_only_and_tolerates_missing_tables(tmp_path, key):
    p = tmp_path / "bare.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, display_name TEXT)")
    c.execute("INSERT INTO users (display_name) VALUES ('林某某')")
    c.commit()
    c.close()
    before = p.read_bytes()
    out = tmp_path / "h.json"
    assert HL.main(["export", "--db", str(p), "--key", str(tmp_path / "k" / "hmac.key"), "--out", str(out)]) == 0
    assert p.read_bytes() == before, "export 動到了資料庫複本"
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["source_counts"].get("person") == 1 and "customer" not in d["source_counts"]


def test_wrong_key_expired_and_near_expiry_lists_are_refused_or_flagged(tmp_path, db_copy, key):
    out = _export(tmp_path, db_copy, key)
    other = tmp_path / "other.key"
    HL.main(["keygen", "--out", str(other)])
    with pytest.raises(ValueError):
        S.load_hashlist(out, S.load_key(other))
    hl = S.load_hashlist(out, key)
    created = date.fromisoformat(hl.created[:10])
    prob, note = S.check_freshness(hl, today=created + timedelta(days=31))
    assert prob and "過期" in prob
    prob, note = S.check_freshness(hl, today=created + timedelta(days=24))
    assert prob is None and note and "到期" in note
    assert S.check_freshness(hl, today=created + timedelta(days=3)) == (None, None)


def test_a_list_without_the_canary_is_reported(tmp_path, db_copy, key):
    hl = _hl(tmp_path, db_copy, key)
    for h, k in list(hl.kind_of.items()):
        if k == "canary":
            del hl.kind_of[h]
    assert S.canary_check(hl) and "金絲雀" in S.canary_check(hl)


# ── 雜湊層：各種寫法都掃得到 ───────────────────────────────────────────────────────

def test_hash_layer_finds_each_kind_in_many_spellings(tmp_path, db_copy, key):
    hl = _hl(tmp_path, db_copy, key)
    root = _tree(tmp_path, {
        "a/company.py": '# 公司：%s\n' % COMPANY,
        "a/company_spaced.txt": "示範 資訊　股份 有限公司\n",
        "a/tax.txt": "統編 %s\n" % ("%s-%s" % (TAX[:4], TAX[4:])),
        "a/tax_fullwidth.txt": "統編：%s\n" % TAX.translate({ord(c): ord(c) + 0xFEE0 for c in "0123456789"}),
        "a/phone_intl.txt": "Tel: +886-4-1234-5678\n",
        "a/phone_plain.txt": "Tel: 04 1234 5678\n",
        "a/email.html": "<a>boss&#64;corp-demo.example</a>\n",
        "a/person.txt": "承辦人 王 示範 先生\n",
        "a/addr.txt": "地址：臺中市 西屯區 示範路 123 號\n",
        "a/acct.txt": "帳號 1234-5678-90123\n",
        "a/data.json": json.dumps({"x": {"y": "客戶 %s" % CUSTOMER}}, ensure_ascii=True),       # \\uXXXX 跳脫
        "a/none.txt": "這是一段完全無關的文字 Lorem ipsum 20260930\n",
    })
    hits = S.scan(root, hl)
    by = {}
    for h in hits:
        by.setdefault(h.path, set()).add(h.kind)
    assert "company" in by["a/company.py"] and "company" in by["a/company_spaced.txt"]
    assert "taxid" in by["a/tax.txt"] and "taxid" in by["a/tax_fullwidth.txt"]
    assert "phone" in by["a/phone_intl.txt"] and "phone" in by["a/phone_plain.txt"]
    assert "email" in by["a/email.html"] and "person" in by["a/person.txt"] and "address" in by["a/addr.txt"]
    assert "account" in by["a/acct.txt"] and "customer" in by["a/data.json"]
    assert "a/none.txt" not in by, by.get("a/none.txt")


def test_hit_reports_carry_no_plaintext(tmp_path, db_copy, key, capsys):
    root = _tree(tmp_path, {"x.txt": "%s %s %s\n" % (COMPANY, TAX, EMAIL)})
    hl_path = _export(tmp_path, db_copy, key)
    rc = S.main([str(root), "--hashlist", str(hl_path), "--key", str(tmp_path / "k" / "hmac.key")])
    out = capsys.readouterr().out
    assert rc == 1 and "DEID_HIT" in out and "x.txt:1:" in out
    for v in (COMPANY, TAX, EMAIL, PERSON):
        assert v not in out and S.normalize(v) not in out
    assert "DEID_SCAN_FAIL" in out


def test_png_text_chunk_is_scanned(tmp_path, db_copy, key):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"tEXt", b"Author\x00" + COMPANY.encode("utf-8")) + chunk(b"IEND", b"")
    hl = _hl(tmp_path, db_copy, key)
    hits = S.scan(_tree(tmp_path, {"img/logo.png": png}), hl)
    assert hits and hits[0].kind == "company" and hits[0].path == "img/logo.png"


def test_json_parsed_value_is_not_double_counted_with_the_raw_line(tmp_path, db_copy, key):
    hl = _hl(tmp_path, db_copy, key)
    hits = S.scan(_tree(tmp_path, {"d.json": json.dumps({"n": COMPANY}, ensure_ascii=False)}), hl)
    hits = [h for h in hits if h.kind == "company"]                       # 樣式層的 company_pattern 是另一件事（W4 補的）
    assert len(hits) == 1 and hits[0].line == 1, hits


def test_short_values_are_skipped_and_counted_and_adjacent_rule_finds_the_expanded_form(tmp_path, db_copy, key):
    extra = [{"kind": "company", "value": "示範", "adjacent": ["整合", "公司"]}, {"kind": "company", "value": "示"}]
    out = _export(tmp_path, db_copy, key, extra)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["skipped_short"] >= 1
    hl = S.load_hashlist(out, key)
    root = _tree(tmp_path, {"a.txt": "示範整合方案\n", "b.txt": "公司示範中心\n", "c.txt": "示範講座\n", "d.txt": "示 範\n"})
    by = {h.path for h in S.scan(root, hl)}
    assert {"a.txt", "b.txt"} <= by and "c.txt" not in by and "d.txt" not in by


# ── 樣式層 ──────────────────────────────────────────────────────────────────────

def test_pattern_layer_without_a_key(tmp_path):
    root = _tree(tmp_path, {
        "p/email.txt": "聯絡 someone@real-company.com.tw\n",
        "p/ok_email.txt": "someone@example.com, a@b.test\n",
        "p/ip.txt": "host 192.168.10.7 and 10.0.0.5\n",
        "p/path.txt": "cd C:\\Users\\someone\\Desktop\\proj\n",
        "p/tax_ok.txt": "統編 %s\n" % TAX,
        "p/tax_bad.txt": "統編 %s\n" % next("1234560%d" % d for d in range(10) if not S.tw_tax_id_valid("1234560%d" % d)),
        "p/phone.txt": "電話 04-2222-3333\n",
        "p/addr.txt": "臺中市西屯區示範路45號\n",
    })
    by = {}
    for h in S.scan(root):
        by.setdefault(h.path, set()).add(h.kind)
    assert "email" in by["p/email.txt"] and "p/ok_email.txt" not in by
    assert "private_ip" in by["p/ip.txt"] and "dev_path" in by["p/path.txt"]
    assert "taxid_pattern" in by["p/tax_ok.txt"] and "p/tax_bad.txt" not in by
    assert "phone_pattern" in by["p/phone.txt"] and "address_pattern" in by["p/addr.txt"]


def test_tw_tax_id_checksum():
    assert S.tw_tax_id_valid(TAX) and not S.tw_tax_id_valid("1234560" + str((int(TAX[-1]) + 1) % 10))
    assert not S.tw_tax_id_valid("1234567") and not S.tw_tax_id_valid("abcdefgh")


def test_fiction_registry_suppresses_only_the_registered_value(tmp_path):
    root = _tree(tmp_path, {"f.txt": "someone@real-company.com.tw other@other-company.com.tw\n"})
    code = S.value_code("email", "someone@real-company.com.tw")
    hits = S.scan(root, fiction=[{"value_id": code, "reason": "虛構示範"}])
    assert [h.kind for h in hits] == ["email"] and hits[0].value_id != code


def test_allow_registry_requires_exact_counts_and_forbids_company_kinds(tmp_path):
    root = _tree(tmp_path, {"f.txt": "a@real-a.com.tw\n", "g.txt": "a@real-a.com.tw\na@real-a.com.tw\n"})
    code = S.value_code("email", "a@real-a.com.tw")
    ok = S.scan(root, allow=[{"path": "f.txt", "value_id": code, "count": 1, "reason": "x", "expires": "2999-01-01"}])
    assert {h.path for h in ok} == {"g.txt"}
    wrong = S.scan(root, allow=[{"path": "g.txt", "value_id": code, "count": 1, "reason": "x", "expires": "2999-01-01"}])
    assert {h.path for h in wrong} == {"f.txt", "g.txt"}, "次數對不上必須照紅"
    probs = S.allow_problems([{"path": "f.txt", "value_id": code, "count": 1, "reason": "x", "expires": "2999-01-01", "kind": "company"},
                              {"path": "f.txt", "value_id": code, "count": 1, "reason": "x", "expires": "2000-01-01"},
                              {"path": "f.txt"}])
    assert any("不得放行本公司類別" in p for p in probs) and any("已過期" in p for p in probs) and any("缺欄位" in p for p in probs)


def test_scan_skips_git_and_pycache_dirs(tmp_path):
    root = _tree(tmp_path, {".git/x.txt": "someone@real-company.com.tw\n", "__pycache__/y.txt": "someone@real-company.com.tw\n", "ok.txt": "hi\n"})
    assert S.scan(root) == []


def test_main_without_hashlist_runs_the_pattern_layer_only(tmp_path, capsys):
    root = _tree(tmp_path, {"a.txt": "clean\n"})
    assert S.main([str(root)]) == 0 and "DEID_SCAN_OK" in capsys.readouterr().out


# ── W4 出貨稽核補的四類（2026-09-30）：單據編號、公司全名樣式、密碼陳述、密碼集合常數 ─────────────────────

def _kinds(root):
    return sorted({h.kind for h in S.scan(root)})


def _pkg(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def test_w4_docno_pattern_catches_a_real_looking_quote_number_next_to_a_customer_abbreviation(tmp_path):
    """W4 (a)：`voucher.html` 的 placeholder「<客戶簡稱>報價單MQ-202608-009工資」——簡稱不在資料庫的完整名稱裡，雜湊層抓不到；單據編號樣式抓得到。"""
    root = _pkg(tmp_path, {"frontend/pages/v.html": '<textarea placeholder="海天大飯店報價單MQ-202608-009工資"></textarea>\n',
                           "backend/x.py": '"""範例：PS-202609-001 薪資單"""\n'})
    assert {(h.path, h.kind) for h in S.scan(root)} == {("frontend/pages/v.html", "docno_pattern"), ("backend/x.py", "docno_pattern")}
    assert _kinds(_pkg(tmp_path / "ok", {"a.md": "編號格式 MQ-YYYYMM-NNN；日期 2026-09-30；PO-12\n"})) == []      # 格式說明與日期不誤判


def test_w4_company_pattern_catches_full_names_without_a_hashlist_and_ignores_generic_words(tmp_path):
    """W4 (c)：`core/upgrade.py` 等內嵌公司全名——不需要清單，樣式就抓得到；「股份有限公司」這個類型字眼不誤判。"""
    root = _pkg(tmp_path, {"backend/a.py": 'NAME = "海天整合股份有限公司"\nB = "山川企業社"\n',
                           "docs/g.md": "本公司為股份有限公司；貴公司有限公司型態；該有限公司\n"})
    hits = S.scan(root)
    assert sorted((h.path, h.line, h.kind) for h in hits) == [("backend/a.py", 1, "company_pattern"), ("backend/a.py", 2, "company_pattern")]


def test_w4_secret_literal_flags_every_string_in_a_password_collection_constant_only(tmp_path):
    """W4 (b)：`_LEGACY_WEAK_PASSWORDS = ( "…", … )`——集合常數內每個字串字面值都報；同檔其他字串、名稱不含 PASSWORD 的集合不報。"""
    src = ('X = ("plain-string-a",)\n'
           '_LEGACY_WEAK_PASSWORDS = (\n'
           '    "hunter2x",\n'
           '    "sample@pw1",\n'
           ')\n'
           'OTHER = ("not-a-secret",)\n'
           'API_SECRET_KEYS: list = ["k-1234", "k-5678"]\n'
           'def f():\n'
           '    y = "after-block"\n')
    root = _pkg(tmp_path, {"backend/auth.py": src})
    assert sorted((h.line, h.kind) for h in S.scan(root)) == [(3, "secret_literal"), (4, "secret_literal"), (7, "secret_literal"), (7, "secret_literal")]
    assert len({h.value_id for h in S.scan(root)}) == 4                      # 值代碼不同、輸出不含明文
    for h in S.scan(root):
        assert "hunter2x" not in repr(h)


def test_w4_credential_pattern_flags_password_statements_in_docs_but_not_code_or_labels(tmp_path):
    root = _pkg(tmp_path, {"DR-SOP.md": "登入 demo，密碼：abc12345 仍可用\n",
                           "s.ps1": "$password = 'pw-Sample9'\n",
                           "p.html": "<script>fetch(u,{body: JSON.stringify({ password: this.form.pw, new_password: this.form.newPw })})</script>\n"
                                     "<label>設定密碼：請輸入</label> 'auth.change_password': '修改密碼',\n",
                           "c.py": "password = request.password\n"})
    assert sorted((h.path, h.kind) for h in S.scan(root)) == [("DR-SOP.md", "credential_pattern"), ("s.ps1", "credential_pattern")]


def test_w4_new_kinds_can_be_registered_as_fiction_by_value_code(tmp_path):
    """虛構登記（value_id ＝ 樣式層值代碼）對新四類同樣有效；不在登記內照擋。"""
    root = _pkg(tmp_path, {"a.py": 'N = "海天整合股份有限公司"  # MQ-202608-009\n'})
    hits = S.scan(root)
    assert {h.kind for h in hits} == {"company_pattern", "docno_pattern"}
    fiction = [{"value_id": h.value_id} for h in hits if h.kind == "docno_pattern"]
    assert {h.kind for h in S.scan(root, fiction=fiction)} == {"company_pattern"}
