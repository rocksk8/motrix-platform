"""單位卡解析與總索引產生器（PLAYBOOK §G2）。

用途：讓人和 AI 不必讀完整個檔案就看得懂 L0／L1——先讀 docs/platform/UNIT-INDEX.md，再決定開哪個檔。

用法：
    python tools/platform/unit_index.py            # 重產 docs/platform/UNIT-INDEX.md
    python tools/platform/unit_index.py --check    # 與重產結果不同 ⇒ exit 1（守門：tests/platform/test_unit_cards.py）

資料來源（都是現場讀，不讀已提交的衍生檔）：
- 單位清單與公開介面：G1 快照 backend/tests/platform/l1_interface_snapshot.json（plat:／core:／helper:）
- 直接使用者數：dep_scan.build() 的 import 圖中，直接 import 該單位的單位數（router／模組／helper／core；不含測試）
- 用途、契約題：各檔模組 docstring 裡的單位卡；沒有卡 ⇒ 用途取 docstring 第一行並標「（無單位卡）」

單位卡格式（寫在模組 docstring 內；第一行是用途，卡片是連續、不含空行的一段，空行結束）：
    [單位] plat:events   [層] L0   [穩定度] 契約（改介面照 §C-7 升版）
    [公開介面] declare, publish, subscribe      ← 頂層名稱，與 G1 快照中該單位不含「.」的名稱集合相同
    [不變式] …（選填）
    [契約題] tests/platform/test_core_events.py（相對 backend/ 或 repo 根；可多個，以 , 、 或空白分隔）
    [注意] …（選填）
一行可以放多個欄位；欄位值可以跨行（下一行不以 [欄位] 開頭即為續行）；`←` 之後到行尾是給人看的旁註，不解析。
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
SNAPSHOT = BACKEND / "tests" / "platform" / "l1_interface_snapshot.json"
OUT = ROOT / "docs" / "platform" / "UNIT-INDEX.md"

FIELDS = ("單位", "層", "穩定度", "公開介面", "不變式", "契約題", "注意")
REQUIRED = ("單位", "層", "穩定度", "公開介面", "契約題")
_FIELD_RE = re.compile(r"\[(%s)\]" % "|".join(FIELDS))
_LINE_FIELD_RE = re.compile(r"^\s*\[([^\]\s]{1,8})\]")
_SPLIT_RE = re.compile(r"[,，、\s]+")
_NONE_WORDS = {"無", "（無）", "(無)", "-", "—"}


# ───────────────────────── 單位 ⇄ 檔案 ─────────────────────────

def unit_path(unit: str, backend: Path = BACKEND) -> Path | None:
    kind, name = unit.split(":", 1)
    return {"plat": backend / "core" / (name + ".py"),
            "core": backend / (name + ".py"),
            "helper": backend / "helpers" / (name + ".py")}.get(kind)


def path_unit(rel: str) -> str | None:
    """repo 相對路徑 ⇒ 單位名（不是 L0／L1 Python 檔 ⇒ None；是否真的在 L1 範圍由呼叫端對快照判斷）。"""
    parts = rel.replace("\\", "/").split("/")
    if len(parts) < 2 or parts[0] != "backend" or not parts[-1].endswith(".py") or parts[-1] == "__init__.py":
        return None
    stem = parts[-1][:-3]
    if len(parts) == 2:
        return "core:" + stem
    if len(parts) == 3 and parts[1] == "core":
        return "plat:" + stem
    if len(parts) == 3 and parts[1] == "helpers":
        return "helper:" + stem
    return None


def layer_of(unit: str) -> str:
    return "L0" if unit.startswith("plat:") else "L1"


def load_snapshot(path: Path = SNAPSHOT) -> dict:
    """{單位: {頂層公開名稱…}}（類別成員「Class.x」由類別名稱代表，不列在卡上）。"""
    snap = json.loads(Path(path).read_text(encoding="utf-8"))["interface"]
    return {u: {k for k in v if "." not in k} for u, v in snap.items()}


# ───────────────────────── 單位卡解析 ─────────────────────────

def module_docstring(path: Path) -> str | None:
    try:
        return ast.get_docstring(ast.parse(Path(path).read_text(encoding="utf-8-sig")), clean=True)
    except (OSError, SyntaxError):
        return None


def first_line(doc: str | None) -> str:
    for line in (doc or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def parse_card(doc: str | None) -> tuple[dict | None, list[str]]:
    """docstring ⇒ (卡片欄位 dict 或 None＝沒有卡, 格式問題清單)。

    卡片＝第一個以已知 [欄位] 開頭的行起、到空行為止的連續行。卡片外又出現 [欄位] 行、
    同一欄位寫兩次、卡片內以未知 [xxx] 開頭的行 ⇒ 列為問題（不猜）。
    """
    if not doc:
        return None, []
    lines = doc.splitlines()
    starts = [i for i, ln in enumerate(lines) if _FIELD_RE.match(ln.strip())]
    if not starts:
        return None, []
    problems = []
    begin = starts[0]
    end = begin
    while end < len(lines) and lines[end].strip():
        end += 1
    for i in starts:
        if i >= end:
            problems.append("卡片外還有欄位行（卡片要連續、中間不可有空行）：%s" % lines[i].strip())
    block = []
    for ln in lines[begin:end]:
        m = _LINE_FIELD_RE.match(ln)
        if m and m.group(1) not in FIELDS:
            problems.append("未知欄位 [%s]" % m.group(1))
        block.append(ln.split("←", 1)[0])
    text = "\n".join(block)
    marks = list(_FIELD_RE.finditer(text))
    card = {}
    for j, m in enumerate(marks):
        val = text[m.end(): marks[j + 1].start() if j + 1 < len(marks) else len(text)]
        val = " ".join(val.split())
        if m.group(1) in card:
            problems.append("欄位 [%s] 重複" % m.group(1))
        card[m.group(1)] = val
    card["用途"] = first_line(doc)
    return card, problems


def split_list(value: str) -> list[str]:
    v = (value or "").strip()
    if v in _NONE_WORDS:
        return []
    return [x for x in _SPLIT_RE.split(v) if x]


def resolve_test(ref: str, root: Path = ROOT) -> Path | None:
    rel = ref.split("::", 1)[0]
    for base in (root / "backend", root):
        p = base / rel
        if p.is_file():
            return p
    return None


def check_card(unit: str, card: dict, public: set[str], root: Path = ROOT) -> list[str]:
    """一張卡對一個單位：欄位齊全、單位名與層正確、公開介面＝G1 快照、契約題檔存在。"""
    problems = []
    for f in REQUIRED:
        if not (card.get(f) or "").strip():
            problems.append("缺欄位 [%s]" % f)
    if card.get("單位") and card["單位"].split()[0] != unit:
        problems.append("[單位] 寫 %s，實際是 %s" % (card["單位"].split()[0], unit))
    if card.get("層") and card["層"].split()[0] != layer_of(unit):
        problems.append("[層] 寫 %s，實際是 %s" % (card["層"].split()[0], layer_of(unit)))
    if "公開介面" in card:
        listed = set(split_list(card["公開介面"]))
        extra, missing = sorted(listed - public), sorted(public - listed)
        if extra:
            problems.append("[公開介面] 多列了快照沒有的名稱：%s" % ", ".join(extra))
        if missing:
            problems.append("[公開介面] 少了快照有的名稱：%s" % ", ".join(missing))
    if card.get("契約題"):
        refs = split_list(card["契約題"])
        if not refs:
            problems.append("[契約題] 沒有列任何檔")
        for r in refs:
            if resolve_test(r, root) is None:
                problems.append("[契約題] 檔案不存在：%s" % r)
    return problems


def cards(snapshot: dict | None = None, backend: Path = BACKEND) -> dict:
    """{單位: {"path", "doc_first", "card"(或 None), "format_problems"}}——給索引、守門與選題工具共用。"""
    snapshot = load_snapshot() if snapshot is None else snapshot
    out = {}
    for u in sorted(snapshot):
        p = unit_path(u, backend)
        doc = module_docstring(p) if p and p.is_file() else None
        card, fmt = parse_card(doc)
        out[u] = {"path": p, "doc_first": first_line(doc), "card": card, "format_problems": fmt}
    return out


# ───────────────────────── 總索引 ─────────────────────────

def _load_dep_scan():
    spec = importlib.util.spec_from_file_location("_unit_index_dep_scan", ROOT / "tools" / "platform" / "dep_scan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def direct_users(graph_units: dict | None = None) -> dict:
    """{單位: 直接 import 它的單位數}（dep_scan 的 import 圖；自己不算）。"""
    if graph_units is None:
        graph_units = _load_dep_scan().build()["units"]
    count = {}
    for name, u in graph_units.items():
        for d in set(u.get("imports", [])) - {name}:
            count[d] = count.get(d, 0) + 1
    return count


def _cell(s: str) -> str:
    return (s or "").replace("|", "\\|").strip()


def render(snapshot: dict | None = None, users: dict | None = None, backend: Path = BACKEND) -> str:
    snapshot = load_snapshot() if snapshot is None else snapshot
    users = direct_users() if users is None else users
    info = cards(snapshot, backend)
    order = sorted(snapshot, key=lambda u: (layer_of(u), u))
    with_card = sum(1 for u in order if info[u]["card"])
    out = [
        "# UNIT-INDEX：L0／L1 單位總索引",
        "",
        "由 `python tools/platform/unit_index.py` 產生，**勿手改**；`--check` 驗證（守門 `tests/platform/test_unit_cards.py`）。"
        "格式與規則見 PLAYBOOK §G2。",
        "新的 session 先讀這份，再決定要開哪個檔；要看不變式與注意事項，只讀該檔開頭的單位卡。",
        "",
        "- 介面＝G1 快照中的頂層公開名稱數；使用者＝dep_scan import 圖中直接 import 它的單位數（不含測試）。",
        "- 用途標「（無單位卡）」＝取自 docstring 第一行，尚未補卡；改到該檔時守門會要求補上。",
        "",
        "單位 %d 個；有單位卡 %d 個。" % (len(order), with_card),
        "",
        "| 單位 | 層 | 用途 | 介面 | 使用者 | 契約題 |",
        "|---|---|---|---:|---:|---|",
    ]
    for u in order:
        c = info[u]["card"]
        if c:
            purpose = c["用途"]
            tests = "、".join("`%s`" % t for t in split_list(c.get("契約題", ""))) or "—"
        else:
            purpose = (info[u]["doc_first"] or "（無 docstring）") + "（無單位卡）"
            tests = "—"
        out.append("| `%s` | %s | %s | %d | %d | %s |"
                   % (u, layer_of(u), _cell(purpose), len(snapshot[u]), users.get(u, 0), tests))
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="與重產結果不同 ⇒ exit 1，不寫檔")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    text = render()
    out = Path(a.out)
    if a.check:
        cur = out.read_text(encoding="utf-8") if out.is_file() else None
        if cur != text:
            print("UNIT-INDEX 過期（或不存在）：%s\n⇒ 跑 python tools/platform/unit_index.py 重產後一起 commit"
                  % out)
            return 1
        print("UNIT-INDEX 與重產結果相同")
        return 0
    out.write_text(text, encoding="utf-8", newline="\n")
    print("已寫出 %s" % out)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
