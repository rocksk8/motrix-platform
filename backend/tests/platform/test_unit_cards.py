"""單位卡與總索引的守門（PLAYBOOK §G2；產生器 tools/platform/unit_index.py）。

規則：
1. 這次分支改到的 L0／L1 檔（對 origin/platform 的合流點比，含未提交與新檔）必須有單位卡——漸進導入，改到誰就補誰。
2. 已經有卡的單位，卡都要合格（不論這次有沒有改到）：必填欄位齊全、[單位]／[層] 正確、
   [公開介面]＝G1 快照中該單位的頂層名稱、[契約題] 的檔存在。
   ⇒ 快照因為別處的 import 而變（跨模組底線名稱）時，卡也會被要求跟上。
3. docs/platform/UNIT-INDEX.md 與重產結果相同。

origin/platform 不存在（例如部署包、沒有 remote 的 clone）⇒ 規則 1 skip 並寫明原因；規則 2、3 照跑。
"""
import functools
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BASE_REF = "origin/platform"
_spec = importlib.util.spec_from_file_location("_unit_index", REPO / "tools" / "platform" / "unit_index.py")
U = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(U)
#: dep_scan.build() 約 9 秒；同一個 pytest 行程內原始碼不變 ⇒ 只算一次
U.direct_users = functools.lru_cache(maxsize=1)(U.direct_users)


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def changed_files(repo=REPO, base_ref=BASE_REF):
    """本分支相對 base_ref 合流點改到的檔（已提交＋未提交＋未追蹤的新檔；已刪除的不算）。base_ref 不存在 ⇒ None。"""
    try:
        mb = _git(repo, "merge-base", base_ref, "HEAD").strip()
    except subprocess.CalledProcessError:
        return None
    names = set(_git(repo, "diff", "--name-only", "--diff-filter=d", mb).split("\n"))
    names |= set(_git(repo, "ls-files", "--others", "--exclude-standard").split("\n"))
    return sorted(n for n in names if n)


#: 規則 1「改到就要補卡」目前只強制這些路徑（主持 2026-09-26：使用者裁示「轉移流程優先」，
#: 模組搬遷期間各包大量改到 helper，全面強制會讓每一班列車都卡在補卡）。D1 搬遷完成後擴大到 backend/helpers/ 等 L1。
ENFORCED_PREFIXES = ("backend/core/",)


def missing_cards(changed, snapshot, backend=U.BACKEND, enforced=ENFORCED_PREFIXES):
    """改到的檔中屬於 G1 單位、在強制範圍內、卻沒有單位卡的 ⇒ [(單位, 路徑)]。"""
    out = []
    for rel in changed:
        if not any(rel.replace("\\", "/").startswith(pre) for pre in enforced):
            continue
        u = U.path_unit(rel)
        if u is None or u not in snapshot:
            continue
        p = U.unit_path(u, backend)
        if p.is_file() and U.parse_card(U.module_docstring(p))[0] is None:
            out.append((u, rel))
    return out


def card_problems(snapshot, root=REPO):
    """所有已有卡的單位 ⇒ {單位: [問題…]}（只列有問題的）。"""
    bad = {}
    for u, info in U.cards(snapshot, root / "backend").items():
        if info["card"] is None:
            continue
        probs = info["format_problems"] + U.check_card(u, info["card"], snapshot[u], root)
        if probs:
            bad[u] = probs
    return bad


@pytest.fixture(scope="module")
def snapshot():
    return U.load_snapshot()


# ── 正對照 ────────────────────────────────────────────────────────────────

def test_parser_sees_the_cards(snapshot):
    """解析器壞掉時其餘幾題會安靜地綠 ⇒ 先證明讀得到真實的卡（L0 core/ 已全部補卡）。"""
    assert len(snapshot) >= 40, sorted(snapshot)
    info = U.cards(snapshot)
    plat = sorted(u for u in snapshot if u.startswith("plat:"))
    assert plat and all(info[u]["card"] for u in plat), [u for u in plat if not info[u]["card"]]
    ev = info["plat:events"]["card"]
    assert set(U.REQUIRED) <= set(ev) and "publish" in U.split_list(ev["公開介面"])


def test_git_diff_is_readable():
    got = changed_files()
    if got is None:
        pytest.skip("%s 不存在：無法判定本分支改到的檔（部署包／無 remote 的 clone）" % BASE_REF)
    assert isinstance(got, list)


# ── 守門 ─────────────────────────────────────────────────────────────────

def test_changed_l0_l1_files_have_cards(snapshot):
    changed = changed_files()
    if changed is None:
        pytest.skip("%s 不存在：規則 1 無法判定" % BASE_REF)
    miss = missing_cards(changed, snapshot)
    assert not miss, ("本分支改到的 L0／L1 檔沒有單位卡（PLAYBOOK §G2；格式見 tools/platform/unit_index.py）：\n  "
                      + "\n  ".join("%s  %s" % x for x in miss))


def test_existing_cards_are_valid(snapshot):
    bad = card_problems(snapshot)
    assert not bad, "單位卡不合格：\n" + "\n".join(
        "  %s\n    %s" % (u, "\n    ".join(p)) for u, p in sorted(bad.items()))


@pytest.mark.skipif(__import__("os").environ.get("MOTRIX_TRAIN") != "1",
                    reason="產生檔只由列車提交（PLAYBOOK §G3）：UNIT-INDEX 是否最新只在 MOTRIX_TRAIN=1 驗")
def test_unit_index_is_current():
    assert U.main(["--check"]) == 0, "docs/platform/UNIT-INDEX.md 過期 ⇒ python tools/platform/unit_index.py 重產"


# ── 反向控制：每一種違規都要轉紅 ─────────────────────────────────────────

GOOD = '''"""示範單位。

[單位] plat:demo    [層] L0    [穩定度] 契約
[公開介面] alpha, beta,
    GAMMA
[不變式] x
[契約題] tests/platform/test_unit_cards.py

其餘說明。
"""
'''
PUBLIC = {"alpha", "beta", "GAMMA"}


def _check(src, public=PUBLIC, unit="plat:demo"):
    import ast
    card, fmt = U.parse_card(ast.get_docstring(ast.parse(src), clean=True))
    assert card is not None
    return fmt + U.check_card(unit, card, public, REPO)


def test_rc_good_card_passes():
    assert _check(GOOD) == []


_DROP = {
    "單位": ("[單位] plat:demo    ", ""),
    "層": ("[層] L0    ", ""),
    "穩定度": ("    [穩定度] 契約", ""),
    "公開介面": ("[公開介面] alpha, beta,\n    GAMMA\n", ""),
    "契約題": ("[契約題] tests/platform/test_unit_cards.py\n", ""),
}


@pytest.mark.parametrize("field", U.REQUIRED)
def test_rc_missing_field_is_red(field):
    old, new = _DROP[field]
    assert old in GOOD
    probs = _check(GOOD.replace(old, new))
    assert any("缺欄位 [%s]" % field in p for p in probs), probs


def test_rc_empty_field_is_red():
    probs = _check(GOOD.replace("[穩定度] 契約", "[穩定度]"))
    assert any("缺欄位 [穩定度]" in p for p in probs), probs


def test_rc_extra_public_name_is_red():
    probs = _check(GOOD, public=PUBLIC - {"GAMMA"})
    assert any("多列" in p and "GAMMA" in p for p in probs), probs


def test_rc_missing_public_name_is_red():
    probs = _check(GOOD, public=PUBLIC | {"delta"})
    assert any("少了" in p and "delta" in p for p in probs), probs


def test_rc_contract_file_missing_is_red():
    probs = _check(GOOD.replace("test_unit_cards.py", "test_no_such_file.py"))
    assert any("不存在" in p for p in probs), probs


def test_rc_wrong_unit_or_layer_is_red():
    assert any("[單位]" in p for p in _check(GOOD, unit="plat:other"))
    assert any("[層]" in p for p in _check(GOOD.replace("[層] L0", "[層] L1")))


def test_rc_split_card_and_unknown_field_are_red():
    assert any("卡片外" in p for p in _check(GOOD.replace("[不變式] x\n", "\n[不變式] x\n")))
    assert any("未知欄位" in p for p in _check(GOOD.replace("[不變式] x", "[不變試] x")))


def test_rc_changed_file_without_card_is_caught(snapshot):
    """改到一個沒卡的 L1 檔（helper:auth 目前沒有卡）⇒ 抓得到；改到有卡的、非 L1 的 ⇒ 不抓。"""
    rel_nocard = next(("backend/helpers/%s.py" % u.split(":", 1)[1]) for u in sorted(snapshot)
                      if u.startswith("helper:") and U.cards({u: snapshot[u]})[u]["card"] is None)
    files = [rel_nocard, "backend/core/events.py", "backend/routers/cashier.py", "docs/x.md"]
    miss = missing_cards(files, snapshot, enforced=("backend/",))       # 範圍擴大到全部 ⇒ 抓得到
    assert [r for _, r in miss] == [rel_nocard]
    assert missing_cards(files, snapshot) == []                         # 目前的強制範圍（backend/core/）不含 helper


def test_rc_core_file_without_card_is_caught_in_current_scope(snapshot, tmp_path):
    """目前的強制範圍：core/ 底下沒有卡的單位 ⇒ 抓得到（用暫存 backend，真的拿掉一張卡）。"""
    import shutil
    b = tmp_path / "backend"
    shutil.copytree(U.BACKEND / "core", b / "core")
    p = b / "core" / "events.py"
    src = p.read_text(encoding="utf-8")
    import re as _re
    p.write_text(_re.sub(r"(?m)^\[[^\]]+\].*\n", "", src), encoding="utf-8")      # 拿掉整張卡
    miss = missing_cards(["backend/core/events.py"], snapshot, backend=b)
    assert [r for _, r in miss] == ["backend/core/events.py"]


def test_rc_git_diff_sees_committed_uncommitted_and_new_files(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    for a in (("init", "-q"), ("config", "user.email", "t@example.invalid"), ("config", "user.name", "t")):
        _git(r, *a)
    for name in ("a.py", "b.py", "c.py"):
        (r / name).write_text("x = 1\n", encoding="utf-8")
    _git(r, "add", "--", "a.py", "b.py", "c.py")
    _git(r, "commit", "-q", "-m", "base")
    _git(r, "update-ref", "refs/remotes/origin/platform", "HEAD")
    (r / "a.py").write_text("x = 2\n", encoding="utf-8")
    _git(r, "commit", "-q", "-m", "committed", "--", "a.py")
    (r / "b.py").write_text("x = 3\n", encoding="utf-8")          # 未提交
    (r / "new.py").write_text("y = 1\n", encoding="utf-8")        # 未追蹤
    (r / "c.py").unlink()                                          # 刪除 ⇒ 不算
    assert changed_files(r) == ["a.py", "b.py", "new.py"]
    assert changed_files(r, "origin/nope") is None


def test_rc_stale_index_is_red(tmp_path):
    out = tmp_path / "UNIT-INDEX.md"
    assert U.main(["--out", str(out)]) == 0
    assert U.main(["--check", "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    out.write_text(text.replace("| `plat:events` | L0 |", "| `plat:events` | L1 |"), encoding="utf-8")
    assert U.main(["--check", "--out", str(out)]) == 1
    out.unlink()
    assert U.main(["--check", "--out", str(out)]) == 1, "索引不存在也要紅"
