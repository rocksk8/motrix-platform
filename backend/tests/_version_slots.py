"""版號佔位（version slots）：分支寫佔位、列車上才取號（PLAYBOOK §G6；使用者 2026-09-30「撞號太多次了，想辦法解決」）。

[用途] 守門與 tools/platform/train_number.py 共用的判定：什麼是佔位、目前准不准有佔位、樹裡有哪些佔位。
四種佔位（分支上寫；列車 `train_number.py assign` 換成真號）：
  模組／CORE CHANGELOG 標題   `## (next) — <日期>（<分支>）…`；`(next:minor)`／`(next:major)` 指定升版幅度（模組預設修正號、CORE 預設次版號）
  version_manifest 條目        `"version": "next"`（date／time／content 照填）
  G1 快照                      `"core_version": "next"`（`core_bump.py --pending` 寫；registry.CORE_VERSION 不動）
  core migration               `register("core", NEXT, fn)`（runtime 不記版號、每次啟動重跑；列車換成連續整數）
准不准：MOTRIX_TRAIN=1、分支 platform／master／main／train/*、HEAD 是 prod/* 標籤 ⇒ 不准（有就紅）；
        其他（wip/*、一般分支、detached）⇒ 准。git 查不到 ⇒ 不准（寧可紅）。
"""
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER = "next"
#: `## (next)`、`## (next:minor)`、`## (next:major)`；group(1)＝幅度（None＝預設）
HEADING = re.compile(r"^##[ \t]+\(next(?::(patch|minor|major))?\)", re.M)
#: 佔位標題「看起來像」但寫錯（例 `## (Next)`、`## next`、`## (next:big)`）⇒ 守門擋，工具不猜
HEADING_LOOSE = re.compile(r"^##[ \t]+\(?\s*next\b", re.M | re.I)
#: 只認行首的登記（docstring／註解裡提到的不算；與 train_number.MIG_LINE 同一個錨點）
MIGRATION = re.compile(r"""^register\(\s*["']core["']\s*,\s*NEXT\s*,""", re.M)
PROTECTED_BRANCHES = ("platform", "master", "main")


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", timeout=60)
    return r.stdout.strip() if r.returncode == 0 else None


def placeholders_allowed(repo=ROOT, environ=None):
    """⇒ (准不准, 理由)。"""
    env = os.environ if environ is None else environ
    if env.get("MOTRIX_TRAIN") == "1":
        return False, "MOTRIX_TRAIN=1（列車）"
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if branch is None:
        return False, "讀不到目前分支（git 失敗）⇒ 當成不准"
    if branch in PROTECTED_BRANCHES or branch.startswith("train/"):
        return False, "分支 %s" % branch
    if branch == "HEAD":
        tags = (_git(repo, "tag", "--points-at", "HEAD") or "").split()
        if any(t.startswith("prod/") for t in tags):
            return False, "HEAD 是正式機標籤 %s" % ",".join(t for t in tags if t.startswith("prod/"))
    return True, "分支 %s" % branch


def module_changelogs(root=ROOT):
    mods = Path(root) / "backend" / "modules"
    return sorted(p for p in mods.glob("*/CHANGELOG.md")) if mods.is_dir() else []


def find_placeholders(root=ROOT):
    """⇒ [「位置：說明」]，樹裡所有佔位（不論准不准）。"""
    root = Path(root)
    out = []
    for cl in module_changelogs(root) + [root / "backend" / "core" / "CHANGELOG.md"]:
        if cl.is_file():
            for m in HEADING.finditer(cl.read_text(encoding="utf-8")):
                out.append("%s：%s" % (cl.relative_to(root).as_posix(), m.group(0)))
    man = root / "backend" / "version_manifest.json"
    if man.is_file():
        for e in json.loads(man.read_text(encoding="utf-8-sig")):
            if e.get("version") == PLACEHOLDER:
                out.append("backend/version_manifest.json：%s version=next" % e.get("module"))
    snap = root / "backend" / "tests" / "platform" / "l1_interface_snapshot.json"
    if snap.is_file() and json.loads(snap.read_text(encoding="utf-8")).get("core_version") == PLACEHOLDER:
        out.append("backend/tests/platform/l1_interface_snapshot.json：core_version=next")
    mig = root / "backend" / "core" / "migrations.py"
    if mig.is_file():
        for m in MIGRATION.finditer(mig.read_text(encoding="utf-8")):
            out.append("backend/core/migrations.py：%s" % m.group(0))
    return out


def malformed_headings(text):
    """看起來想寫佔位、卻不是合法格式的標題行。"""
    out = []
    for m in HEADING_LOOSE.finditer(text):
        if not HEADING.match(text, m.start()):
            end = text.find("\n", m.start())
            out.append(text[m.start():end if end >= 0 else len(text)])
    return out
