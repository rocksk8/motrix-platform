"""合回時依 origin 自動取 CORE 版號並重產 G1 快照（PLAYBOOK §C-7；2026-09-26 一晚撞號 6 次以上）。

用法（repo 根目錄；rebase 之後，或 rebase 停在 backend/core/CHANGELOG.md 衝突時）：
  python tools/platform/core_bump.py [--onto origin/platform] [--mine REF]            只列出會怎麼改（exit 3＝要改、0＝不用）
  python tools/platform/core_bump.py [--onto origin/platform] [--mine REF] --apply    寫入

  --mine：我的 CHANGELOG 從哪裡讀（預設工作樹）。rebase 衝突中工作樹那份是衝突標記 ⇒ 給 rebase 前的分支尖端
          （例：`--mine ORIG_HEAD` 或分支名）。

規則：
  我的段落＝我的 CHANGELOG 最上面、標題行不出現在 onto CHANGELOG 的那些「## 主.次」段落（遇到 onto 也有的就停）。
  需要的升版＝onto 快照的介面 vs 目前工作樹的介面（同 _l1_interface：新增⇒次版號、修改／刪除⇒主版號）。
  重新編號：從 onto 的 CORE_VERSION 往上，我的段落由下往上依序 +1 次版號；需要主版號時最下面那段升主版號。
  寫入：CHANGELOG＝onto 的全文，最上面插入我的段落（標題的版號換成新號並註記暫用號）；
        registry.CORE_VERSION＝最上面那段的版號；G1 快照＝onto 的快照再以新版號重產。
  我沒有段落、介面也沒變 ⇒ 什麼都不做。介面有變卻沒有段落 ⇒ 拒絕（要先寫 CHANGELOG，工具不替人寫內容）。
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REGISTRY_REL = "backend/core/registry.py"
CHANGELOG_REL = "backend/core/CHANGELOG.md"
SNAPSHOT_REL = "backend/tests/platform/l1_interface_snapshot.json"
#: 「## 主.次」段落標題；`(?![\d.])` 擋掉三段版號（## 1.4.1 不是 CORE 版號段落；`\b` 擋不住，4 與 . 之間也算邊界）
HEADER = re.compile(r"^## +(\d+)\.(\d+)(?![\d.])(.*)$", re.M)


def split_sections(text):
    """⇒ (前言, [(標題行, 版號 (主,次), 內文)])；只認「## 主.次」段落。"""
    ms = list(HEADER.finditer(text))
    if not ms:
        return text, []
    pre = text[:ms[0].start()]
    out = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        out.append((m.group(0), (int(m.group(1)), int(m.group(2))), text[m.end():end]))
    return pre, out


def my_sections(mine_text, onto_text):
    """我的 CHANGELOG 最上面、onto 沒有的段落。

    以**內文**比對，不以標題行：段落合回時 core_bump 會改寫標題（換版號、加「暫用 X → Y」註記），
    以標題比對會把已經合回的段落又當成我的、再編一次號（2026-09-26 C3 疊在 C1 上時實際發生：C1 的內容重複成 1.14）。
    標題也相同的一樣算已合回（內文空白的段落靠標題辨認）。"""
    onto = split_sections(onto_text)[1]
    onto_bodies = {body.strip() for _, _, body in onto if body.strip()}
    onto_headers = {h for h, _, _ in onto}
    out = []
    for h, v, body in split_sections(mine_text)[1]:
        if h in onto_headers or (body.strip() and body.strip() in onto_bodies):
            break
        out.append((h, v, body))
    return out


def renumber(onto_version, count, need):
    """onto 的 (主,次) ⇒ 我的 count 段由下往上的新版號（清單由上往下）。"""
    major, minor = onto_version
    out = []
    for i in range(count):
        if i == 0 and need == "major":
            major, minor = major + 1, 0
        else:
            minor += 1
        out.append((major, minor))
    return list(reversed(out))


def rebuild(onto_text, sections, versions):
    """onto 全文，最上面插入我的段落（換新號；原號不同時在標題行尾註記）。"""
    pre, onto_secs = split_sections(onto_text)
    mine = []
    for (h, old, body), new in zip(sections, versions):
        m = HEADER.match(h)
        tail = m.group(3)
        if old != new:
            tail += "〔core_bump：暫用 %d.%d → %d.%d〕" % (old + new)
        mine.append("## %d.%d%s%s" % (new[0], new[1], tail, body))
    rest = onto_text[len(pre):]
    return pre + "".join(mine) + rest


def plan(mine_text, onto_text, onto_version, need):
    """⇒ (新 CHANGELOG 全文或 None, 新版號字串或 None, 訊息)。"""
    secs = my_sections(mine_text, onto_text)
    if not secs:
        if need:
            return None, None, "介面有變動（需要 %s 升版）卻沒有自己的 CHANGELOG 段落 ⇒ 先寫 core/CHANGELOG.md" % need
        return None, None, "沒有自己的段落、介面也沒變 ⇒ 不用改"
    versions = renumber(onto_version, len(secs), need)
    new_text = rebuild(onto_text, secs, versions)
    ver = "%d.%d" % versions[0]
    moves = "、".join("%d.%d→%d.%d" % (s[1] + v) for s, v in zip(secs, versions))
    return new_text, ver, "onto CORE_VERSION %d.%d；我的段落 %d 段（%s）；需要升版：%s" % (
        onto_version + (len(secs), moves, need or "無（行為變更仍取次版號）"))


# ── git／檔案 ────────────────────────────────────────────────────────────

def _git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def _show(ref, rel):
    return _git("show", "%s:%s" % (ref, rel))


def _version_of(registry_src):
    m = re.search(r'^CORE_VERSION\s*=\s*"(\d+)\.(\d+)"', registry_src, re.M)
    return (int(m.group(1)), int(m.group(2)))


def _interface_tools():
    sys.path.insert(0, str(REPO / "backend"))
    sys.path.insert(0, str(REPO / "backend" / "tests" / "platform"))
    import _l1_interface as G   # noqa: E402
    return G


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--onto", default="origin/platform")
    ap.add_argument("--mine", help="我的 CHANGELOG 從哪個 ref 讀（預設工作樹）")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)

    onto_text = _show(a.onto, CHANGELOG_REL)
    onto_version = _version_of(_show(a.onto, REGISTRY_REL))
    onto_snap = json.loads(_show(a.onto, SNAPSHOT_REL))
    mine_text = _show(a.mine, CHANGELOG_REL) if a.mine else (REPO / CHANGELOG_REL).read_text(encoding="utf-8")
    if "<<<<<<<" in mine_text:
        print("工作樹的 CHANGELOG 還有衝突標記 ⇒ 用 --mine <rebase 前的分支尖端> 指定我的版本")
        return 2

    G = _interface_tools()
    added, changed, removed = G.diff(onto_snap["interface"], G.current_interface())
    need = G.required_bump(added, changed, removed)
    new_text, ver, msg = plan(mine_text, onto_text, onto_version, need)
    print(msg)
    if new_text is None:
        return 1 if need else 0
    cur_text = (REPO / CHANGELOG_REL).read_text(encoding="utf-8")
    cur_ver = "%d.%d" % _version_of((REPO / REGISTRY_REL).read_text(encoding="utf-8"))
    if new_text == cur_text and ver == cur_ver and G.load_snapshot().get("core_version") == ver:
        print("版號已正確（%s），不用改" % ver)
        return 0
    if not a.apply:
        print("會改：%s（CORE_VERSION → %s）、%s、%s；加 --apply 寫入" % (CHANGELOG_REL, ver, REGISTRY_REL, SNAPSHOT_REL))
        return 3
    (REPO / CHANGELOG_REL).write_text(new_text, encoding="utf-8", newline="\n")
    reg = REPO / REGISTRY_REL
    src = reg.read_text(encoding="utf-8")
    reg.write_text(re.sub(r'^CORE_VERSION\s*=\s*"[^"]*"', 'CORE_VERSION = "%s"' % ver, src, count=1, flags=re.M),
                   encoding="utf-8", newline="\n")
    (REPO / SNAPSHOT_REL).write_text(_show(a.onto, SNAPSHOT_REL), encoding="utf-8", newline="\n")
    rc = G.main(["--update"])
    print("已寫入：CORE_VERSION %s；G1 快照由 %s 的快照重產（%s）" % (ver, a.onto, "成功" if rc == 0 else "失敗 rc=%s" % rc))
    return rc


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
