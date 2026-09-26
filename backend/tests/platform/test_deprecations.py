"""淘汰中的公開名稱：登記表 `docs/platform/deprecations.json` 與程式碼的一致性（主持裁示 2026-09-26，稽核 D M5-M1）。

☠️ 缺這道之前：L1 薄殼寫著「下一個主版號刪除」，而 CORE_VERSION 改成 "2.0" 時殼照樣在、守門全綠——
   「寫下何時刪」不會自己觸發（記憶〈計數器要有落點〉）。
① 到期：CORE 主版號 ≥ `remove_at_major` 而名稱還在該檔頂層 ⇒ 紅
② 反掃：產品程式（`core.source_tree.product_files`）出現「淘汰」卻沒有任何登記指向那一檔 ⇒ 紅（避免漏登）
③ 登記有效：名稱要真的在該檔頂層定義（打錯字或刪了卻沒拿掉登記 ⇒ 紅）
每一條都有合成反向控制（不綁真實檔案）。
"""
import ast
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
REG = REPO / "docs" / "platform" / "deprecations.json"
MARK = "淘汰"


def top_level_names(src):
    """頂層名稱，外加類別的成員寫成 `Class.member`（淘汰的可以是一個方法，例：IP-12 的 `_CaseAccess.summary`）。"""
    names = set()
    for n in ast.parse(src).body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        if isinstance(n, ast.ClassDef):
            for m in n.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add("%s.%s" % (n.name, m.name))
                elif isinstance(m, ast.Assign):
                    names |= {"%s.%s" % (n.name, t.id) for t in m.targets if isinstance(t, ast.Name)}
        elif isinstance(n, ast.Assign):
            names |= {t.id for t in n.targets if isinstance(t, ast.Name)}
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.add(n.target.id)
        elif isinstance(n, ast.ImportFrom):
            names |= {a.asname or a.name for a in n.names}
    return names


def major(core_version):
    return int(str(core_version).split(".")[0])


def expired(entries, core_version, read):
    """read(file) ⇒ 原始碼或 None（檔已不在）。回「到期而名稱還在」的清單。"""
    out = []
    for e in entries:
        src = read(e["file"])
        if src is not None and major(core_version) >= int(e["remove_at_major"]) and e["name"] in top_level_names(src):
            out.append("%s::%s（淘汰於 CORE %s，%s.0 起應刪除；改用 %s）"
                       % (e["file"], e["name"], e["since_core"], e["remove_at_major"], e["replacement"]))
    return out


def unregistered(files_src, entries):
    """files_src：{相對路徑: 原始碼}。出現「淘汰」而沒有任何登記指向它的檔。"""
    listed = {e["file"] for e in entries}
    return sorted(f for f, s in files_src.items() if MARK in s and f not in listed)


def invalid(entries, read):
    out = []
    for e in entries:
        missing = [k for k in ("file", "name", "since_core", "remove_at_major", "replacement") if not e.get(k)]
        if missing:
            out.append("%s：缺欄位 %s" % (e, missing))
            continue
        from core import source_tree
        if not source_tree.module_installed(e["file"]):
            continue                              # 那個檔在一個沒安裝的模組裡（選配／反向控制）：登記照留，不比
        src = read(e["file"])
        if src is None or e["name"] not in top_level_names(src):
            out.append("%s::%s：登記了但該檔頂層沒有這個名稱" % (e["file"], e["name"]))
    return out


def _real():
    from core import registry, source_tree
    entries = json.loads(REG.read_text(encoding="utf-8"))["entries"]

    def read(rel):
        p = source_tree.BACKEND / rel
        return p.read_text(encoding="utf-8") if p.is_file() else None
    files = {source_tree.rel(p): p.read_text(encoding="utf-8") for p in source_tree.product_files() if p.suffix == ".py"}
    return entries, read, files, registry.CORE_VERSION


def test_no_deprecated_name_outlives_its_major():
    entries, read, _files, cv = _real()
    assert not expired(entries, cv, read), "\n".join(expired(entries, cv, read))


def test_every_deprecation_marker_is_registered():
    entries, _read, files, _cv = _real()
    bad = unregistered(files, entries)
    assert not bad, "程式寫了「淘汰」卻沒有登記進 docs/platform/deprecations.json：" + ", ".join(bad)


def test_every_registration_points_at_a_real_name():
    entries, read, _files, _cv = _real()
    bad = invalid(entries, read)
    assert not bad, "\n".join(bad)


def test_positive_control_the_real_registry_is_not_empty():
    entries, read, files, _cv = _real()
    assert any(e["file"] == "helpers/receivables.py" for e in entries), "正對照：receivables 薄殼要在登記表上"
    assert "helpers/receivables.py" in files and MARK in files["helpers/receivables.py"]


def test_rc_expiry_turns_red_at_the_next_major():
    src = "def old():\n    pass\nNEW = 1\n"
    e = [{"file": "helpers/x.py", "name": "old", "since_core": "1.36", "remove_at_major": 2, "replacement": "new()"}]
    read = lambda f: src if f == "helpers/x.py" else None
    assert expired(e, "1.99", read) == []                       # 還沒到
    assert len(expired(e, "2.0", read)) == 1                    # 主版號到了而名稱還在 ⇒ 紅
    assert expired(e, "2.0", lambda f: "NEW = 1\n") == []      # 刪掉了 ⇒ 綠


def test_rc_class_member_names():
    src = "class K:\n    def gone(self):\n        pass\n"
    e = [{"file": "helpers/k.py", "name": "K.gone", "since_core": "1.37", "remove_at_major": 2, "replacement": "x"}]
    read = lambda f: src
    assert invalid(e, read) == [] and len(expired(e, "2.0", read)) == 1
    assert len(invalid([dict(e[0], name="K.typo")], read)) == 1


def test_rc_unregistered_marker_and_invalid_entry():
    files = {"helpers/a.py": "# 淘汰中：下一個主版號刪除\ndef f(): pass\n", "helpers/b.py": "def g(): pass\n"}
    assert unregistered(files, []) == ["helpers/a.py"]
    assert unregistered(files, [{"file": "helpers/a.py"}]) == []
    e = [{"file": "helpers/b.py", "name": "typo", "since_core": "1.0", "remove_at_major": 2, "replacement": "x"}]
    assert len(invalid(e, lambda f: files.get(f))) == 1
    assert len(invalid([{"file": "helpers/b.py", "name": "g"}], lambda f: files.get(f))) == 1   # 缺欄位
