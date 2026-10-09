"""git 合併驅動：CHANGELOG 與 version_manifest.json 兩邊都在最上面插入 ⇒ 兩邊都留，不出衝突（PLAYBOOK §G6）。

用法（git 呼叫；由 tools/platform/setup_merge_drivers.py 登記到 repo 的 git config，複本放在 git 共用目錄）：
  merge_drivers.py changelog %O %A %B [%P]
  merge_drivers.py manifest  %O %A %B [%P]
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


# ── CLI ──────────────────────────────────────────────────────────────────

MERGERS = {"changelog": merge_changelog, "manifest": merge_manifest}


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
        print("用法：merge_drivers.py changelog|manifest %O %A %B [%P]", file=sys.stderr)
        return 2
    kind, o, a, b = argv[:4]
    path = argv[4] if len(argv) > 4 else a
    texts = [_read(p) for p in (o, a, b)]
    merged = None
    if all(t is not None for t in texts):
        try:
            merged = MERGERS[kind](*texts)
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
