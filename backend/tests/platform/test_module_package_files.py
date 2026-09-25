"""G2：每個模組資料夾都要有 README.md、CHANGELOG.md、SPEC.md、module.json 的 data 與 license_key；
CHANGELOG 最上面的版號＝module.json 的 version（MODULE-GUIDE §5、§6；license_key 為 9c② 裁示）。
SPEC.md（PLAYBOOK §B 步驟 7，主持裁示 2026-09-26）：要有 `## 規格條件`；該節沒有任何編號宣告時要寫明「本模組沒有專屬編號」
（空節與「忘了搬編號」長得一樣）。

判定函式 check_module_dir() 對任何資料夾都適用 ⇒ 反向控制在 tmp 建合成模組，不綁特定 L2 模組。
"""
import json
import re
import shutil
from pathlib import Path

import pytest

from core import source_tree

_VERSION_HEAD = re.compile(r"^##\s+(\d+\.\d+\.\d+)\b", re.M)
# 規格條件的三種宣告（同 STATE.md）：條列 `- **X1.**`、表格列 `| **X1** |`、`### X1 ·`
_SPEC_DECL = re.compile(r"^(?:\s*-\s+\*\*[A-Z][A-Za-z-]*\d+|\|\s*\*\*[A-Z][A-Za-z-]*\d+|###\s+[A-Z][A-Za-z-]*\d+)", re.M)
NO_SPEC_IDS = "本模組沒有專屬編號"


def check_spec(text):
    """SPEC.md 內容 ⇒ 問題清單。"""
    m = re.search(r"^## 規格條件[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if m is None:
        return ["SPEC.md 缺「## 規格條件」一節"]
    if not _SPEC_DECL.search(m.group(1)) and NO_SPEC_IDS not in m.group(1):
        return ["SPEC.md 的規格條件沒有任何編號宣告，也沒有寫明「%s」" % NO_SPEC_IDS]
    return []


def check_module_dir(d):
    """一個模組資料夾 ⇒ 問題清單（空＝合格）。"""
    d = Path(d)
    problems = []
    for name in ("README.md", "CHANGELOG.md", "SPEC.md", "module.json"):
        if not (d / name).is_file():
            problems.append("缺 %s" % name)
    if (d / "SPEC.md").is_file():
        problems += check_spec((d / "SPEC.md").read_text(encoding="utf-8"))
    if not (d / "module.json").is_file():
        return problems
    try:
        m = json.loads((d / "module.json").read_text(encoding="utf-8"))
    except ValueError as e:
        return problems + ["module.json 不是合法 JSON：%s" % e]
    data = m.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("tables"), list) or not isinstance(data.get("files"), list):
        problems.append("module.json 的 data 要有 tables 與 files 兩個清單（沒有也要寫空清單）")
    lk = m.get("license_key")
    if not isinstance(lk, str) or not lk.strip():
        problems.append("module.json 缺 license_key（預設＝資料夾名 %s）" % d.name)
    version = m.get("version")
    if (d / "CHANGELOG.md").is_file():
        top = _VERSION_HEAD.search((d / "CHANGELOG.md").read_text(encoding="utf-8"))
        if top is None:
            problems.append("CHANGELOG.md 找不到「## X.Y.Z」版號標題")
        elif top.group(1) != version:
            problems.append("CHANGELOG 最上面的版號 %s ≠ module.json version %s" % (top.group(1), version))
    return problems


def test_every_module_has_its_package_files():
    dirs = source_tree.module_dirs()
    if not dirs:
        pytest.skip("沒有任何已安裝模組（modules/*/module.json）⇒ 無對象")
    bad = {d.name: check_module_dir(d) for d in dirs}
    bad = {k: v for k, v in bad.items() if v}
    assert not bad, "模組資料夾不合格：\n" + "\n".join("  %s：%s" % (k, "；".join(v)) for k, v in sorted(bad.items()))


# ── 反向控制：合成模組逐一拿掉一項 ────────────────────────────────────────────

def _good(tmp_path):
    d = tmp_path / "zz_mod"
    d.mkdir()
    (d / "README.md").write_text("# zz\n", encoding="utf-8")
    (d / "SPEC.md").write_text("# zz\n\n## 規格條件\n\n- **ZZ1.** 甲\n", encoding="utf-8")
    (d / "CHANGELOG.md").write_text("# zz 更新紀錄\n\n## 1.2.0 — 2026-09-25\n- 新增\n\n## 1.1.0 — 2026-09-20\n", encoding="utf-8")
    (d / "module.json").write_text(json.dumps({"key": "zz_mod", "version": "1.2.0", "license_key": "zz_mod",
                                               "data": {"tables": [], "files": []}}), encoding="utf-8")
    return d


def test_rc_good_synthetic_module_passes(tmp_path):
    assert check_module_dir(_good(tmp_path)) == []


@pytest.mark.parametrize("mutate,expect", [
    (lambda d: (d / "README.md").unlink(), "缺 README.md"),
    (lambda d: (d / "CHANGELOG.md").unlink(), "缺 CHANGELOG.md"),
    (lambda d: (d / "SPEC.md").unlink(), "缺 SPEC.md"),
    (lambda d: (d / "SPEC.md").write_text("# zz\n\n- **ZZ1.** 甲\n", encoding="utf-8"), "缺「## 規格條件」"),
    (lambda d: (d / "SPEC.md").write_text("# zz\n\n## 規格條件\n\n（待補）\n\n## 範圍\n- **ZZ1.** 不在規格條件節\n",
                                          encoding="utf-8"), "沒有任何編號宣告"),
    (lambda d: _edit_json(d, lambda m: m.pop("data")), "data"),
    (lambda d: _edit_json(d, lambda m: m["data"].pop("files")), "data"),
    (lambda d: _edit_json(d, lambda m: m.pop("license_key")), "license_key"),
    (lambda d: _edit_json(d, lambda m: m.update(license_key="  ")), "license_key"),
    (lambda d: _edit_json(d, lambda m: m.update(version="1.3.0")), "≠ module.json version"),
    (lambda d: (d / "CHANGELOG.md").write_text("# 無版號\n", encoding="utf-8"), "找不到"),
])
def test_rc_each_missing_item_is_caught(tmp_path, mutate, expect):
    d = _good(tmp_path)
    mutate(d)
    problems = check_module_dir(d)
    assert any(expect in p for p in problems), problems


@pytest.mark.parametrize("body", [
    "- **ZZ1.** 條列",
    "| 編號 | 條件 |\n|---|---|\n| **ZZ1** | 表格 |",
    "### ZZ1 · 標題",
    "本模組沒有專屬編號（拿掉本模組時 test_spec_coverage 仍綠，2026-09-26 驗）",
])
def test_rc_spec_forms_that_pass(tmp_path, body):
    d = _good(tmp_path)
    (d / "SPEC.md").write_text("# zz\n\n## 規格條件\n\n%s\n\n## 範圍\n" % body, encoding="utf-8")
    assert check_module_dir(d) == []


def test_rc_only_the_top_changelog_version_counts(tmp_path):
    """舊版號在下面、新版號在上面：比的是最上面那一個（版號升了卻只在底下補一段 ⇒ 紅）。"""
    d = _good(tmp_path)
    (d / "CHANGELOG.md").write_text("# zz\n\n## 1.1.0 — 2026-09-20\n\n## 1.2.0 — 2026-09-25\n", encoding="utf-8")
    assert any("1.1.0" in p for p in check_module_dir(d))


def _edit_json(d, fn):
    p = d / "module.json"
    m = json.loads(p.read_text(encoding="utf-8"))
    fn(m)
    p.write_text(json.dumps(m), encoding="utf-8")
