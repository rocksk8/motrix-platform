"""git 合併驅動：CHANGELOG 與 version_manifest.json 兩邊都在最上面插入 ⇒ 兩邊都留，不出衝突（PLAYBOOK §G6）。

用法（git 呼叫；由 tools/platform/setup_merge_drivers.py 登記到 repo 的 git config，複本放在 git 共用目錄）：
  merge_drivers.py changelog %O %A %B [%P]
  merge_drivers.py manifest  %O %A %B [%P]
  merge_drivers.py json      %O %A %B [%P]
  merge_drivers.py maxentries %O %A %B [%P]
結果寫回 %A；exit 0＝合好、非 0＝衝突（%A 裡是一般的衝突標記）。

規則（只處理「看得懂而且安全」的形狀，其餘一律退回 `git merge-file`＝跟沒有驅動時一樣的衝突，**不猜**）：
  changelog：以「## 」標題切段。兩邊各自＝〔自己新增的段落〕＋〔基底的段落（可被其中一邊改過）〕。
             結果＝前言＋我方新增＋對方新增（完全相同的段落只留一份）＋基底段落。
             基底段落兩邊都改、且改得不一樣 ⇒ 衝突；找不到基底第一段 ⇒ 衝突；前言兩邊改得不一樣 ⇒ 衝突。
             🔸 第 51 班：兩邊各新增一塊 `## (next)` ⇒ **併成一塊**（A 的整塊照舊；B 的標題變成
             「- **（併入）(next) — …**」一行、內文接後面）——一班一個模組只該有一塊（test_version_slots）；
             版號段落（`## X.Y.Z`）不併，仍然兩個都留。
  manifest ：逐筆（JSON 物件）比對。結果＝我方的順序＋對方新增的條目（插在對方檔裡它後面那一筆之前）；
             兩邊加了同一筆（內容完全相同）只留一份；只有一邊刪／改基底條目 ⇒ 照那一邊；
             兩邊都刪／改了基底條目 ⇒ 衝突；檔案格式不是「每筆以 `,\\n  ` 相隔」⇒ 衝突。
  json     ：基準檔（l1_interface_snapshot／route_inventory／response_keys_baseline／unscoped_reads_baseline／modules.json）。
             **結構合併**（不是逐行）：物件逐鍵三方、字串／數字清單依序聯集（基底刪的不復活）、整份排好序的清單結果仍排序；
             兩邊對同一個值改成不一樣 ⇒ 衝突（不猜）。route_inventory 的 summary／select_star 是計數：兩邊都改 ⇒ 基底＋兩邊增量。
             輸出排版＝與基底檔逐位元組相同的 json.dumps 排版；基底排版認不出來（modules.json 是手排的）⇒ 用逐行聯集的文字，
             且必須解析後與結構合併的結果完全相同才採用，否則一般衝突。
  maxentries：test_unscoped_reads_ratchet.py 的 `MAX_ENTRIES = N  # …` 那一塊（上限數字＋往下疊的說明註解）：數字＝基底＋兩邊增量，
             說明註解兩邊的都留；檔案其餘部分兩邊不能都改（否則一般衝突）。注意：上限最後仍要等於聯集後的基準筆數
             （resolve_baselines.py 會重算）。
⚠ 本檔被複製到 git 共用目錄執行（不隨 checkout 變動）；改了這支要重跑 setup_merge_drivers.py（`--check` 會報過期）。
"""
import json
import re
import subprocess
import sys

_SECTION = re.compile(r"^## ", re.M)


# ── CHANGELOG ────────────────────────────────────────────────────────────

def split_sections(text):
    """⇒ (前言, [段落全文（含標題行與其後到下一個「## 」之前）])。"""
    ms = [m.start() for m in _SECTION.finditer(text)]
    if not ms:
        return text, []
    return text[:ms[0]], [text[s:e] for s, e in zip(ms, ms[1:] + [len(text)])]


def _head(section):
    return section.split("\n", 1)[0]


def _pick3(o, a, b):
    """三方：一樣 ⇒ 那個；只有一邊改 ⇒ 改的那邊；兩邊改得不一樣 ⇒ None。"""
    if a == b:
        return a
    if a == o:
        return b
    if b == o:
        return a
    return None


def coalesce_next(sections):
    """第 51 班（SPEEDUP-PREPUSH-T50 類 1）：一班一個模組只該有**一塊** `## (next)`——兩邊各新增一塊時併成一塊
    （第一塊的標題與內文照舊；其餘各塊的標題變成「- **（併入）(next) — …**」一行，內文接在後面）。
    少於兩塊 ⇒ 原樣回傳。完全相同的塊已在上游去重。"""
    idx = [i for i, s in enumerate(sections) if _head(s).startswith("## (next)")]
    if len(idx) < 2:
        return sections
    nl = chr(10)
    out_sec = sections[idx[0]].rstrip(nl)
    for i in idx[1:]:
        s = sections[i]
        head, _, body = s.partition(nl)
        title = head[len("## (next)"):].lstrip(" —-").strip()
        out_sec += nl + "- **（併入）(next) — " + title + "**"
        if body.strip():
            out_sec += nl + body.rstrip(nl)
    out_sec += nl + nl
    drop = set(idx[1:])
    res = []
    for i, s in enumerate(sections):
        if i == idx[0]:
            res.append(out_sec)
        elif i not in drop:
            res.append(s)
    return res


def merge_changelog(o, a, b):
    """⇒ 合併結果，或 None（不是看得懂的形狀 ⇒ 交給一般合併）。"""
    po, so = split_sections(o)
    pa, sa = split_sections(a)
    pb, sb = split_sections(b)
    pre = _pick3(po, pa, pb)
    if pre is None or not so:
        return None
    first = _head(so[0])
    ia = next((i for i, s in enumerate(sa) if _head(s) == first), None)
    ib = next((i for i, s in enumerate(sb) if _head(s) == first), None)
    if ia is None or ib is None:
        return None
    rest = _pick3(so, sa[ia:], sb[ib:])
    if rest is None:
        return None
    new_a = list(sa[:ia])
    new_b = [s for s in sb[:ib] if s not in new_a]
    if new_a and new_b and not new_a[-1].endswith("\n\n"):
        new_a[-1] += "\n" if new_a[-1].endswith("\n") else "\n\n"
    return pre + "".join(coalesce_next(new_a + new_b) + rest)


# ── version_manifest.json ────────────────────────────────────────────────

_SEP = ",\n  "


def parse_manifest(text):
    """⇒ [每筆的原文] 或 None（不是本 repo 的排版：`[` 換行 兩格縮排、筆與筆以 `,\\n  ` 相隔、`\\n]\\n` 結尾）。"""
    if not text.startswith("[\n  ") or not text.endswith("\n]\n"):
        return None
    dec = json.JSONDecoder()
    spans, i, end = [], 4, len(text) - 3
    while True:
        try:
            obj, j = dec.raw_decode(text, i)
        except ValueError:
            return None
        if not isinstance(obj, dict):
            return None
        spans.append(text[i:j])
        if j == end:
            break
        if not text.startswith(_SEP, j):
            return None
        i = j + len(_SEP)
    return spans if render_manifest(spans) == text else None


def render_manifest(spans):
    return "[\n  " + _SEP.join(spans) + "\n]\n"


def _key(span):
    return json.dumps(json.loads(span), sort_keys=True, ensure_ascii=False)


def merge_manifest(o, a, b):
    """⇒ 合併結果，或 None（交給一般合併）。"""
    so, sa, sb = parse_manifest(o), parse_manifest(a), parse_manifest(b)
    if so is None or sa is None or sb is None:
        return None
    ko = {_key(s) for s in so}
    ka = [_key(s) for s in sa]
    kb = [_key(s) for s in sb]
    removed_a, removed_b = ko - set(ka), ko - set(kb)
    if removed_a and removed_b:
        return None
    out = [(k, s) for k, s in zip(ka, sa) if k not in removed_b]
    present = {k for k, _ in out}
    for i, (k, s) in enumerate(zip(kb, sb)):
        if k in ko or k in present:
            continue
        succ = next((kk for kk in kb[i + 1:] if kk in present), None)
        pos = next(n for n, (kk, _) in enumerate(out) if kk == succ) if succ is not None else len(out)
        out.insert(pos, (k, s))
        present.add(k)
    text = render_manifest([s for _, s in out])
    json.loads(text)
    return text


# ── JSON 基準檔（結構合併）──────────────────────────────────────────────

_MISSING = object()
_CONFLICT = object()
#: 兩邊都改的『計數』：這些路徑底下的數字取 基底＋兩邊增量（route_inventory 的 select_star＝各區域 SELECT * 出現次數；
#: summary 不在這裡——它是 endpoints 的合計，合併後直接重算，見 summarize_inventory）
ADDITIVE_PREFIXES = {"route_inventory.json": (("summary",), ("select_star",))}      # summary 先加總只為了不衝突，之後會被重算覆蓋


def summarize_inventory(inv):
    """與 tests/platform/_route_inventory.summarize 同一份算法（本檔要能單獨跑，不能 import 專案）。"""
    api = {k: v for k, v in inv.items() if k.split(" ", 1)[1].startswith("/api/")}
    return {
        "endpoints_total": len(inv), "endpoints_api": len(api),
        "write_total": sum(1 for v in inv.values() if v["w"]),
        "write_api": sum(1 for v in api.values() if v["w"]),
        "get_api": sum(1 for k in api if k.startswith("GET ")),
        "distinct_paths_api": len({k.split(" ", 1)[1] for k in api}),
        "write_with_body_api": sum(1 for v in api.values() if v["w"] and v["body"]),
        "write_with_path_param_api": sum(1 for v in api.values() if v["w"] and v["pp"]),
    }


def _is_scalar(x):
    return x is None or isinstance(x, (str, int, float, bool))


def _sorted_list(xs):
    try:
        return list(xs) == sorted(xs)
    except TypeError:
        return False


def merge_scalar_list(o, a, b):
    """字串／數字清單的三方合併：a 的順序為主，b 新增的插在它後面那一筆之前；基底有、任一邊刪掉的不復活；
    三份都已排序 ⇒ 結果也排序（response_keys 的鍵集是排好序的）。"""
    removed = (set(o) - set(a)) | (set(o) - set(b))
    out = [x for x in a if x not in removed]
    present = set(out)
    for i, x in enumerate(b):
        if x in present or x in o:
            continue
        succ = next((y for y in b[i + 1:] if y in present), None)
        pos = out.index(succ) if succ is not None else len(out)
        out.insert(pos, x)
        present.add(x)
    if _sorted_list(o) and _sorted_list(a) and _sorted_list(b):
        out = sorted(set(out))
    return out


def _core_version(o, a, b):
    """L1 快照的 core_version：一邊是版號佔位 "next"、另一邊是列車取的數字 ⇒ "next"（合併後 CORE CHANGELOG 最上面就是 (next) 段落，
    號碼由列車 train_number.py 重新定）；兩邊是不同的數字 ⇒ 衝突（兩邊各自取了號，要人／列車決定）。"""
    if "next" in (a, b):
        return "next"
    return _CONFLICT


#: 特定檔案、特定路徑的葉子合併規則（只在兩邊都改成不一樣時才會被問到）
SPECIAL_LEAVES = {"l1_interface_snapshot.json": {("core_version",): _core_version}}


def merge_value(o, a, b, path=(), additive=(), special=None):
    """三方結構合併 ⇒ 合併後的值，或 _CONFLICT。_MISSING＝這個鍵在那一邊不存在。"""
    if a == b:
        return a
    if a == o:
        return b
    if b == o:
        return a
    if isinstance(a, dict) and isinstance(b, dict) and (isinstance(o, dict) or o is _MISSING):
        od = o if isinstance(o, dict) else {}
        out = {}
        for k in list(a) + [k for k in b if k not in a]:
            r = merge_value(od.get(k, _MISSING), a.get(k, _MISSING), b.get(k, _MISSING), path + (k,), additive, special)
            if r is _CONFLICT:
                return _CONFLICT
            if r is not _MISSING:
                out[k] = r
        return out
    if isinstance(a, list) and isinstance(b, list) and isinstance(o, list):
        if all(_is_scalar(x) for x in o + a + b):
            return merge_scalar_list(o, a, b)
        return _CONFLICT
    if (all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (o, a, b)) and path
            and any(path[:len(p)] == p for p in additive)):
        return o + (a - o) + (b - o)
    if special and path in special:
        return special[path](o, a, b)
    return _CONFLICT


def _unscoped_dump(obj):
    """unscoped_reads_baseline.json 的排版（tests/platform/_unscoped_reads.dump：一筆一行、依 id 排序）。"""
    es = obj.get("entries") if isinstance(obj, dict) and list(obj) == ["entries"] else None
    if not isinstance(es, dict):
        return None
    lines = ['  %s: %s' % (json.dumps(k, ensure_ascii=False), json.dumps(v)) for k, v in sorted(es.items())]
    return '{\n "entries": {\n%s\n }\n}\n' % ",\n".join(lines)


def _renderers():
    yield lambda o: json.dumps(o, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    yield lambda o: json.dumps(o, ensure_ascii=False, indent=1, sort_keys=False) + "\n"
    yield lambda o: json.dumps(o, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    yield lambda o: json.dumps(o, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    yield _unscoped_dump


def detect_renderer(base_text):
    """⇒ 與基底檔逐位元組相同的排版函式，或 None（手排的檔）。"""
    try:
        obj = json.loads(base_text)
    except ValueError:
        return None
    for r in _renderers():
        try:
            if r(obj) == base_text:
                return r
        except Exception:                                                # noqa: BLE001
            continue
    return None


def _union_text(o, a, b):
    """逐行聯集（git merge-file --union）⇒ 文字或 None；呼叫端要再驗證解析結果。"""
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for name, txt in (("a", a), ("o", o), ("b", b)):
            p = os.path.join(d, name)
            with open(p, "wb") as f:
                f.write(txt.encode("utf-8"))
            paths.append(p)
        r = subprocess.run(["git", "merge-file", "--union", "-p", *paths], capture_output=True)
        if r.returncode < 0 or r.returncode > 127:
            return None
        try:
            return r.stdout.decode("utf-8")
        except UnicodeDecodeError:
            return None


def merge_json(o, a, b, path=""):
    """⇒ 合併後的檔案文字，或 None（衝突／看不懂 ⇒ 交給一般合併）。path 只用來決定哪些路徑是計數。"""
    try:
        jo, ja, jb = json.loads(o), json.loads(a), json.loads(b)
    except ValueError:
        return None
    name = str(path).replace("\\", "/").rsplit("/", 1)[-1]
    res = merge_value(jo, ja, jb, (), ADDITIVE_PREFIXES.get(name, ()), SPECIAL_LEAVES.get(name))
    if res is _CONFLICT:
        return None
    if name == "route_inventory.json" and isinstance(res, dict) and isinstance(res.get("endpoints"), dict) and "summary" in res:
        try:
            res["summary"] = summarize_inventory(res["endpoints"])
        except Exception:                                                # noqa: BLE001 — 形狀不對 ⇒ 不改，讓 resolve_baselines 的驗證去報
            pass
    render = detect_renderer(o)
    if render is not None:
        out = render(res)
        return out if out is not None and json.loads(out) == res else None
    out = _union_text(o, a, b)                                           # 手排的檔：逐行聯集，但結果必須等於結構合併
    if out is None:
        return None
    try:
        return out if json.loads(out) == res else None
    except ValueError:
        return None


# ── test_unscoped_reads_ratchet.py 的 MAX_ENTRIES 區塊 ───────────────────

_CAP = re.compile(r"^MAX_ENTRIES\s*=\s*(\d+)(.*)$")


def split_cap(text):
    """⇒ (前, [區塊行…], 後) 或 None。區塊＝`MAX_ENTRIES = N …` 那一行＋其後以空白開頭的 `#` 續行。"""
    lines = text.split("\n")
    i = next((n for n, l in enumerate(lines) if _CAP.match(l)), None)
    if i is None:
        return None
    j = i + 1
    while j < len(lines) and lines[j].lstrip().startswith("#") and lines[j][:1] in (" ", "\t"):
        j += 1
    return lines[:i], lines[i:j], lines[j:]


def _cap_n(block):
    return int(_CAP.match(block[0]).group(1))


def merge_maxentries(o, a, b):
    so, sa, sb = split_cap(o), split_cap(a), split_cap(b)
    if so is None or sa is None or sb is None:
        return None
    pre = _pick3(so[0], sa[0], sb[0])
    post = _pick3(so[2], sa[2], sb[2])
    if pre is None or post is None:
        return None
    cap = _cap_n(so[1]) + (_cap_n(sa[1]) - _cap_n(so[1])) + (_cap_n(sb[1]) - _cap_n(so[1]))
    first_a = _CAP.match(sa[1][0]).group(2)
    first_b = _CAP.match(sb[1][0]).group(2)
    first_o = _CAP.match(so[1][0]).group(2)
    block = ["MAX_ENTRIES = %d%s" % (cap, first_a)] + sa[1][1:]
    seen = {x.strip() for x in block}
    if first_b != first_o and first_b != first_a and first_b.strip().startswith("#"):
        extra = " " * 24 + "# （併入）" + first_b.strip().lstrip("#").strip()
        if extra.strip() not in seen:
            block.append(extra)
            seen.add(extra.strip())
    for l in sb[1][1:]:
        if l.strip() not in seen and l not in so[1]:
            block.append(l)
            seen.add(l.strip())
    return "\n".join(pre + block + post)


# ── CLI ──────────────────────────────────────────────────────────────────

MERGERS = {"changelog": merge_changelog, "manifest": merge_manifest, "json": merge_json, "maxentries": merge_maxentries}


def _read(path):
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r\n" in raw:
        return None                      # BOM／CRLF：不是本 repo 的排版 ⇒ 不碰
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _fallback(o, a, b, path):
    """跟沒有驅動時一樣：三方文字合併，衝突標記寫進 %A。"""
    r = subprocess.run(["git", "merge-file", "-L", "ours", "-L", "base", "-L", "theirs", a, o, b])
    rc = r.returncode
    print("motrix-merge：%s 不是可自動合併的形狀 ⇒ 一般合併（%s）" % (path, "衝突" if rc else "無衝突"), file=sys.stderr)
    return 1 if rc != 0 else 0


def main(argv):
    if len(argv) < 4 or argv[0] not in MERGERS:
        print("用法：merge_drivers.py changelog|manifest|json|maxentries %O %A %B [%P]", file=sys.stderr)
        return 2
    kind, o, a, b = argv[:4]
    path = argv[4] if len(argv) > 4 else a
    texts = [_read(p) for p in (o, a, b)]
    merged = None
    if all(t is not None for t in texts):
        try:
            merged = merge_json(*texts, path=path) if kind == "json" else MERGERS[kind](*texts)
        except Exception as exc:          # noqa: BLE001 — 驅動自己壞掉也不可以吃掉對方的改動
            print("motrix-merge：%s 驅動例外 %r ⇒ 一般合併" % (path, exc), file=sys.stderr)
            merged = None
    if merged is None:
        return _fallback(o, a, b, path)
    with open(a, "wb") as f:
        f.write(merged.encode("utf-8"))
    return 0


if __name__ == "__main__":
    try:                                                              # 背景執行不彈視窗（tools/platform/nowindow.py；MOTRIX_SHOW_WINDOWS=1 可關）
        import sys as _s, pathlib as _p
        _s.path.insert(0, str(_p.Path(__file__).resolve().parents[0]))
        import nowindow as _nw
        _nw.install()
    except ImportError:
        pass
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")   # 否則 Windows 主控台編碼（cp950）的中文訊息經 git 轉出會亂碼
        except (AttributeError, ValueError):
            pass
    sys.exit(main(sys.argv[1:]))
