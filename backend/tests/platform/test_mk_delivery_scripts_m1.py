# -*- coding: utf-8 -*-
"""發布／基準推送腳本範本化（tools/platform/mk_delivery_scripts.py）：代換完整、不留佔位、檢查邏輯逐字保留、語法可被 bash 解析。"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TOOLS = REPO / "tools" / "platform"
if not (TOOLS / "mk_delivery_scripts.py").is_file():
    pytest.skip("mk_delivery_scripts.py 不在這個安裝包", allow_module_level=True)
sys.path.insert(0, str(TOOLS))
import mk_delivery_scripts as M  # noqa: E402

G, OLD = "a" * 40, "b" * 40


def _pub(**kw):
    a = dict(train=54, gated=G, pkgname="20261012_010101_aaaaaaaaa", branch="train/t54-int", wt="b7-t54", pkgroot="b7-t54-pkg",
             draft="20261012-train54-apply-DRAFT.md", audit_text="PENDING", drill_text="drill ok", letters_from="bc", letters_to="bt", letter_count=3)
    a.update(kw)
    return M.render_publish(**a)


def test_cn_number_and_letters():
    assert [M.cn_number(n) for n in (1, 9, 10, 11, 20, 47, 53, 99)] == ["一", "九", "十", "十一", "二十", "四十七", "五十三", "九十九"]
    with pytest.raises(ValueError):
        M.cn_number(100)
    assert M.letters_seq("bc", 3) == ["bc", "bd", "be"]
    assert M.letters_seq("by", 4) == ["by", "bz", "ca", "cb"]
    with pytest.raises(ValueError):
        M.letters_seq("b", 2)


def test_publish_has_no_placeholder_left_and_carries_the_parameters():
    s = _pub(prev=52)
    assert "@@" not in s
    for must in (G, "train/t54-int", "b7-t54-pkg", "20261012-train54-apply-DRAFT.md", "publish_t54.sh", "verify54.log", "五十二", "五十四"):
        assert must in s, must
    assert "['bc', 'bd', 'be']" in s and "['bt', 'bu', 'bv']" in s


def test_publish_keeps_every_safety_check():
    s = _pub()
    for must in ('[ "$HEAD_NOW" = "$GATED" ]', '[ "$REMOTE" = "$GATED" ]', '[ "$MC" = "$GATED" ]', "--expect-db-version 118",
                 '[ "$AUDIT_TEXT" != "PENDING" ]', "--private-key", '[ ! -e "$DST" ]', "forbidden files in package", "(--check: nothing published, nothing written)"):
        assert must in s, "安全檢查被範本弄丟：" + must
    code = [ln for ln in s.splitlines() if not ln.lstrip().startswith("#")]
    assert not any("--force" in ln or "push -f" in ln for ln in code)


def test_texts_with_single_quotes_are_shell_safe():
    s = _pub(audit_text="it's fine", drill_text="a'b")
    assert "AUDIT_TEXT='it'\\''s fine'" in s and "DRILL_TEXT='a'\\''b'" in s


def test_patches_are_embedded_and_bad_input_is_refused():
    s = _pub(patches=[["old text", "new text"]])
    assert "['old text', 'new text']" in s
    with pytest.raises(ValueError):
        _pub(gated="short")


def test_push_baseline_is_fast_forward_only_and_parameterised():
    s = M.render_push(54, G, OLD, "train/t54-int")
    assert "@@" not in s and OLD in s and G in s and "chore/t54-baseline-d8" in s and "prod/" + G[:8] in s
    code = [ln for ln in s.splitlines() if not ln.lstrip().startswith("#")]
    assert not any("--force" in ln or "push -f" in ln for ln in code) and "git push origin" in s and "--ff-only" in s and "git merge-base --is-ancestor" in s
    with pytest.raises(ValueError):
        M.render_push(54, G, "zz", "x")


@pytest.mark.skipif(shutil.which("bash") is None, reason="沒有 bash")
def test_rendered_scripts_parse_with_bash(tmp_path):
    for name, text in (("p.sh", _pub()), ("q.sh", M.render_push(54, G, OLD, "train/t54-int"))):
        f = tmp_path / name
        f.write_text(text, encoding="utf-8", newline="\n")
        r = subprocess.run(["bash", "-n", name], cwd=str(tmp_path), capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
