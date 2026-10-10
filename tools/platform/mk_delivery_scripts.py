# -*- coding: utf-8 -*-
"""交付腳本範本化：由參數產生「發布腳本」與「基準推送腳本」（取代每班複製上一班腳本再手改數個常數）。

[單位] tools:mk_delivery_scripts    [層] 工具    [穩定度] 內部
[公開介面] render_publish, render_push, cn_number, letters_seq, main
[不變式] 範本（`delivery_templates/*.tpl`）是 T53 實際使用過的腳本改成 `@@KEY@@` 佔位；本工具只做**逐字代換**，不改任何檢查邏輯：
    發布腳本仍是「--check 不寫任何東西、PENDING 稽核文字不得發布、金鑰只傳路徑不讀、不 force」；基準腳本仍是「只 fast-forward、
    origin/platform 必須還是班前那個 commit、閘門 commit 到 tip 之間只能有 docs／基準常數」。任一佔位沒被代換 ⇒ 直接報錯不輸出。

用法（每班）：
  python tools/platform/mk_delivery_scripts.py --train 54 --gated <40位SHA> --pkgname <建包目錄名> --old-platform <班前 origin/platform SHA> \\
      --branch train/t54-int --wt b7-t54 --pkgroot b7-t54-pkg --draft 20261011-train54-apply-DRAFT.md \\
      --letters-from bc --letters-to bt --letter-count 10 --audit-text '...' --drill-text '...' [--patches patches.json] [--out-dir ~]
  --prev 預設 train-1；--letters-from 是草稿裡驗收項的起始字母（兩字母），--letters-to 是這一班要接在上一班之後的起始字母
  （「字母位移」）；--patches 是 [[舊字串, 新字串], …] 的 JSON，只放這一班特有的文字修補（找不到就中止）。
"""
import argparse
import io
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TPL = HERE / "delivery_templates"
_DIGITS = "零一二三四五六七八九"


def cn_number(n: int) -> str:
    """1～99 ⇒ 中文數字（47→四十七、53→五十三、10→十、20→二十）。步驟檔檔名用。"""
    if not 1 <= n <= 99:
        raise ValueError("只支援 1～99：%r" % n)
    if n < 10:
        return _DIGITS[n]
    t, o = divmod(n, 10)
    return ("" if t == 1 else _DIGITS[t]) + "十" + (_DIGITS[o] if o else "")


def letters_seq(start: str, count: int) -> list:
    """兩字母起點遞增：('bc', 3) ⇒ ['bc','bd','be']；超過 z 進位（bz→ca）。"""
    if not re.fullmatch(r"[a-z]{2}", start):
        raise ValueError("字母起點要是兩個小寫字母：%r" % start)
    a, b = ord(start[0]) - 97, ord(start[1]) - 97
    out = []
    for _ in range(count):
        out.append(chr(97 + a) + chr(97 + b))
        b += 1
        if b == 26:
            a, b = a + 1, 0
        if a == 26:
            raise ValueError("字母用完")
    return out


def sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def _fill(tpl: str, values: dict) -> str:
    for k, v in values.items():
        tpl = tpl.replace("@@%s@@" % k, v)
    left = sorted(set(re.findall(r"@@[A-Z0-9_]+@@", tpl)))
    if left:
        raise ValueError("範本佔位沒被代換：%s" % left)
    return tpl


def _sha(x: str, name: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", x):
        raise ValueError("%s 要是 40 位小寫 SHA：%r" % (name, x))
    return x


def render_publish(train, gated, pkgname, branch, wt, pkgroot, draft, audit_text, drill_text, letters_from, letters_to, letter_count,
                   prev=None, patches=(), verify_anchor=None):
    prev = train - 1 if prev is None else prev
    anchor = verify_anchor or (TPL / "verify_anchor.txt").read_text(encoding="utf-8").rstrip("\n")
    lf, lt = letters_seq(letters_from, letter_count), letters_seq(letters_to, letter_count)
    return _fill((TPL / "publish.sh.tpl").read_text(encoding="utf-8"), {
        "TRAIN": str(train), "PREV": str(prev), "THIS_CN": cn_number(train), "PREV_CN": cn_number(prev),
        "GATED": _sha(gated, "gated"), "PKGNAME": pkgname, "BRANCH": branch, "WT": wt, "PKGROOT": pkgroot, "DRAFT": draft,
        "AUDIT_TEXT_SH": sh_quote(audit_text), "DRILL_TEXT_SH": sh_quote(drill_text),
        "VERIFY_ANCHOR_PY": repr(anchor), "LETTERS_FROM_PY": repr(lf), "LETTERS_TO_PY": repr(lt),
        "PATCHES_PY": repr([list(p) for p in patches]),
    })


def render_push(train, gated, old_platform, branch):
    return _fill((TPL / "push_baseline.sh.tpl").read_text(encoding="utf-8"), {
        "TRAIN": str(train), "GATED": _sha(gated, "gated"), "GATED8": gated[:8], "OLD_PLATFORM": _sha(old_platform, "old-platform"), "BRANCH": branch,
    })


def main(argv=None):
    ap = argparse.ArgumentParser(description="產生發布腳本與基準推送腳本")
    ap.add_argument("--train", type=int, required=True)
    ap.add_argument("--prev", type=int, default=None)
    ap.add_argument("--gated", required=True)
    ap.add_argument("--old-platform", required=True)
    ap.add_argument("--pkgname", required=True)
    ap.add_argument("--branch", required=True)
    ap.add_argument("--wt", required=True)
    ap.add_argument("--pkgroot", required=True)
    ap.add_argument("--draft", required=True)
    ap.add_argument("--audit-text", default="PENDING")
    ap.add_argument("--drill-text", required=True)
    ap.add_argument("--letters-from", required=True)
    ap.add_argument("--letters-to", required=True)
    ap.add_argument("--letter-count", type=int, required=True)
    ap.add_argument("--patches", default=None, help="JSON：[[舊字串, 新字串], …]")
    ap.add_argument("--out-dir", default=str(Path.home()))
    a = ap.parse_args(argv)
    patches = json.loads(Path(a.patches).read_text(encoding="utf-8")) if a.patches else []
    out = Path(a.out_dir)
    pub = render_publish(a.train, a.gated, a.pkgname, a.branch, a.wt, a.pkgroot, a.draft, a.audit_text, a.drill_text,
                         a.letters_from, a.letters_to, a.letter_count, a.prev, patches)
    push = render_push(a.train, a.gated, a.old_platform, a.branch)
    for name, text in (("publish_t%d.sh" % a.train, pub), ("push_t%d_baseline.sh" % a.train, push)):
        p = out / name
        if p.exists():
            print("已存在、不覆蓋：%s" % p, file=sys.stderr)
            return 2
        io.open(p, "w", encoding="utf-8", newline="\n").write(text)
        print("寫出 %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
