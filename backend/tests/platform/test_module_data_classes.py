"""G3：module.json 的 data 分類要跟備份的實際行為一致（MODULE-GUIDE §3.2～§3.4）。

  T1 業務資料  ⇒ 必須在每日 JSON 備份裡（archive.backed_up_table_names()），且不在排除清單
  T2 含祕密欄位 ⇒ 必須在每日 JSON 備份裡（⚠ 祕密欄位是否排除：未守門，G3b）
  T3 可重建    ⇒ 不可以在每日 JSON 備份裡，且排除清單要寫理由（test_system_audit 的 _NOT_IN_JSON_BACKUP）
  F2 個資檔案  ⇒ archive 必須有對應的個資分流（目前實作的只有 payslip_archive_path → 系統存檔_個資/勞報單存檔）
  每一張表／每一個檔都要有分類，類別只能是上面幾種。

判定函式對任何 data 宣告都適用 ⇒ 反向控制用合成宣告，不綁特定 L2 模組。
"""
import json

import pytest

from core import source_tree

TABLE_CLASSES = ("T1", "T2", "T3")
FILE_CLASSES = ("F1", "F2", "F3")
def pii_routed_settings(archive_src=None):
    """archive 真的有做個資分流的設定鍵（稽核 G-3：從 archive 推導，不寫死）。

    從 `_mirror_pii_archives` 與它呼叫的函式裡，找 `_paths.PDF_ARCHIVES["<單據>"]` ⇒ core.paths 的設定鍵。
    archive 拿掉分流 ⇒ 集合變空 ⇒ 宣告 F2 的檔案轉紅。
    """
    import ast
    from core import paths as _paths
    from core import source_tree
    src = archive_src if archive_src is not None else (source_tree.BACKEND / "archive.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    root = funcs.get("_mirror_pii_archives")
    if root is None:
        return set()
    todo, seen, keys = [root], set(), set()
    while todo:
        fn = todo.pop()
        if fn.name in seen:
            continue
        seen.add(fn.name)
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in funcs:
                todo.append(funcs[n.func.id])
            if (isinstance(n, ast.Subscript) and isinstance(n.value, ast.Attribute) and n.value.attr == "PDF_ARCHIVES"
                    and isinstance(n.slice, ast.Constant) and n.slice.value in _paths.PDF_ARCHIVES):
                keys.add(_paths.PDF_ARCHIVES[n.slice.value][0])
    return keys


PII_ROUTED_SETTINGS = None   # 由 pii_routed_settings() 現場推導；保留名字給 check_data 的預設參數


def _backed():
    import archive
    return set(archive.backed_up_table_names())


def _excluded():
    from tests.test_system_audit_2026_09_14 import _NOT_IN_JSON_BACKUP
    return dict(_NOT_IN_JSON_BACKUP)


def check_data(data, backed, excluded, pii_settings=None, declared_tables=None):
    """一份 module.json 的 data ⇒ 問題清單。

    declared_tables：module.json 頂層 `tables`（模組擁有的表）；給了就要求它＝data.tables 的名稱集合
    （稽核 G-3：沒有宣告分類的表，就不在任何一條備份規則之下）。
    """
    pii_settings = pii_routed_settings() if pii_settings is None else pii_settings
    problems = []
    if declared_tables is not None:
        named = {t.get("name") for t in data.get("tables", [])}
        missing, extra = sorted(set(declared_tables) - named), sorted(named - set(declared_tables))
        if missing:
            problems.append("擁有的表沒有宣告分類（data.tables 缺）：%s" % missing)
        if extra:
            problems.append("data.tables 列了不是本模組擁有的表：%s" % extra)
    for t in data.get("tables", []):
        name, cls = t.get("name"), t.get("class")
        if cls not in TABLE_CLASSES:
            problems.append("表 %s：分類 %r 不是 %s 之一" % (name, cls, "／".join(TABLE_CLASSES)))
            continue
        if cls in ("T1", "T2"):
            if name not in backed:
                problems.append("表 %s 宣告 %s，但不在每日 JSON 備份裡" % (name, cls))
            if name in excluded:
                problems.append("表 %s 宣告 %s，卻列在備份排除清單" % (name, cls))
        else:
            if name in backed:
                problems.append("表 %s 宣告 T3（可重建），卻在每日 JSON 備份裡" % name)
            if name not in excluded:
                problems.append("表 %s 宣告 T3，排除清單沒有它（要寫出為什麼可以重建）" % name)
    for f in data.get("files", []):
        key, cls = f.get("key"), f.get("class")
        if cls not in FILE_CLASSES:
            problems.append("檔案 %s：分類 %r 不是 %s 之一" % (key, cls, "／".join(FILE_CLASSES)))
        elif cls == "F2" and f.get("setting") not in pii_settings:
            problems.append("檔案 %s 宣告 F2，但 archive 沒有它的個資分流（setting=%r）" % (key, f.get("setting")))
    return problems


def test_scanner_sees_the_backup_lists():
    """正對照：兩份清單都讀得到東西（讀不到時下面那題會安靜地綠）。"""
    assert {"quotations", "customers", "users"} <= _backed()
    assert len(_excluded()) > 5


def test_every_module_data_matches_the_backup():
    dirs = source_tree.module_dirs()
    if not dirs:
        pytest.skip("沒有任何已安裝模組 ⇒ 無對象")
    backed, excluded = _backed(), _excluded()
    bad = {}
    for d in dirs:
        m = json.loads((d / "module.json").read_text(encoding="utf-8"))
        tables = list(m.get("tables", []))
        mig = d / "migrations"
        if mig.is_dir():                                   # 模組自有 migration 建的表也算擁有（P7b 之後才會出現）
            import re as _re
            for f in mig.glob("*.py"):
                tables += _re.findall(r"CREATE TABLE(?: IF NOT EXISTS)?\s+[\"`]?(\w+)", f.read_text(encoding="utf-8"))
        p = check_data(m.get("data") or {}, backed, excluded, declared_tables=tables)
        if p:
            bad[d.name] = p
    assert not bad, "module.json 的 data 與備份不一致：\n" + "\n".join(
        "  %s：%s" % (k, "；".join(v)) for k, v in sorted(bad.items()))


# ── 反向控制（合成宣告）───────────────────────────────────────────────────────

BACKED = {"a_t1", "a_t2"}
EXCLUDED = {"a_t3": "快取，可由來源重算"}


def test_scanner_derives_the_pii_routing_from_archive():
    """正對照：現在的 archive 確實有勞報單的個資分流（推導不到時 F2 檔案一律紅，方向是安全的）。"""
    assert "payslip_archive_path" in pii_routed_settings()


def test_rc_archive_without_pii_routing_empties_the_set():
    """反向控制：archive 拿掉 _mirror_pii_archives 對勞報單的分流 ⇒ 推導結果變空 ⇒ F2 宣告會紅。"""
    from core import source_tree
    src = (source_tree.BACKEND / "archive.py").read_text(encoding="utf-8")
    mutated = src.replace("def _mirror_pii_archives(", "def _mirror_pii_archives_removed(")
    assert pii_routed_settings(mutated) == set()
    data = {"files": [{"key": "slips", "class": "F2", "setting": "payslip_archive_path"}]}
    assert any("個資分流" in p for p in check_data(data, BACKED, EXCLUDED, pii_settings=set()))


def test_rc_owned_table_without_classification_is_caught():
    """稽核 B3：頂層 tables 有、data.tables 沒有 ⇒ 紅；反過來列了別人的表也紅。"""
    data = {"tables": [{"name": "a_t1", "class": "T1"}]}
    assert any("缺" in p for p in check_data(data, BACKED, EXCLUDED, set(), declared_tables=["a_t1", "a_t2"]))
    assert any("不是本模組擁有" in p for p in check_data(data, BACKED, EXCLUDED, set(), declared_tables=[]))
    assert check_data(data, BACKED, EXCLUDED, set(), declared_tables=["a_t1"]) == []


def test_rc_good_declaration_passes():
    data = {"tables": [{"name": "a_t1", "class": "T1"}, {"name": "a_t2", "class": "T2"},
                       {"name": "a_t3", "class": "T3"}],
            "files": [{"key": "slips", "class": "F2", "setting": "payslip_archive_path"},
                      {"key": "pdf", "class": "F1", "setting": "pdf_base_path"}]}
    assert check_data(data, BACKED, EXCLUDED) == []


@pytest.mark.parametrize("data,expect", [
    ({"tables": [{"name": "missing", "class": "T1"}]}, "不在每日 JSON 備份裡"),
    ({"tables": [{"name": "a_t3", "class": "T1"}]}, "不在每日 JSON 備份裡"),
    ({"tables": [{"name": "a_t1", "class": "T3"}]}, "卻在每日 JSON 備份裡"),
    ({"tables": [{"name": "brand_new", "class": "T3"}]}, "排除清單沒有它"),
    ({"tables": [{"name": "a_t1"}]}, "分類 None"),
    ({"tables": [{"name": "a_t1", "class": "T9"}]}, "分類 'T9'"),
    ({"files": [{"key": "ids", "class": "F2", "setting": "id_scan_path"}]}, "沒有它的個資分流"),
    ({"files": [{"key": "x", "class": "F7"}]}, "分類 'F7'"),
])
def test_rc_each_mismatch_is_caught(data, expect):
    problems = check_data(data, BACKED, EXCLUDED)
    assert any(expect in p for p in problems), problems


def test_rc_t1_listed_in_exclusion_is_caught():
    assert any("排除清單" in p for p in check_data({"tables": [{"name": "a_t1", "class": "T1"}]},
                                                    BACKED, dict(EXCLUDED, a_t1="誤列")))
