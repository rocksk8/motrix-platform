# -*- coding: utf-8 -*-
"""LG-O1：正式公鑰一填入，出貨包就不可以再帶開發公鑰（`_PUBKEY_DEV`）。

## 為什麼
`backend/helpers/licensing.py` 同時內嵌 `_PUBKEY_DEV`、`_PUBKEY_PROD`，`_open_blob()` 兩把都信；而這支檔會進**每一個**出貨包。
開發私鑰沒有像正式私鑰那樣進密碼管理器保管 ⇒ 握有它的人可以對任何一台機器（含正式機）簽出 `env=dev` 的授權金鑰，
`license_gate_middleware` 不會擋它（只有橫幅＋每日稽核）。⇒ 授權閘門的強度 ＝ 兩把私鑰中保管最差的那一把。
修法不靠「這台是不是正式機」的猜測（沒有可靠訊號），而是**包裡根本沒有那把公鑰**：
`_PUBKEY_PROD` 非空 ⇒ 建包時把包內 `licensing.py` 的 `_PUBKEY_DEV` 賦值改寫成 `b""`（只改包，不改 git）；
`_open_blob()` 對空的公鑰「略過、不丟例外」，所以開發私鑰簽的金鑰在包內一律 `bad_signature`。

## 兩層（fail-closed；漏掉任何一層都會擋下，不是靜默放過）
1. 建包：`strip`（改寫）＋`check`（再驗一次；`build_deploy_package.ps1` 兩個都叫，任何一個非 0 ⇒ 中止）。
2. 驗包：`verify_package.py` 的 `check_dev_pubkey`（同一支 `policy_problems`，另帶正對照）。
   ⚠️ 正式機上跑的是**已安裝版本**的 `verify_package.py`（`delivery.py` 刻意用正式機上受信任的程式，不是包裡的）——
   所以這一層要等本班裝上去之後才在正式機生效；本班的把關靠第 1 層與步驟檔的 `Select-String` 檢查。

## 判定規則（全部 fail-closed：看不懂 ⇒ 有問題）
- 必須恰好各有 **一個** 模組層級的 `Name = <bytes 字面值>` 賦值給 `_PUBKEY_DEV`、`_PUBKEY_PROD`；
  任何其他寫法（缺少、非字面值、型別註記、增量賦值、海象、函式內重新賦值、`global` 後改它、重複賦值、語法錯誤）⇒ 問題。
- `_PUBKEY_PROD` 去空白後非空 ＋ `_PUBKEY_DEV` 去空白後非空 ⇒ 問題（LG-O1）。
- `_PUBKEY_PROD` 為空（開發階段）⇒ 不處理、不改寫（開發金鑰在那時是唯一的受信公鑰，拿掉會讓所有金鑰失效）。

用法：
    python pubkey_policy.py strip --pkg <包目錄>      # 就地改寫包內 backend/helpers/licensing.py（必要時）
    python pubkey_policy.py check --pkg <包目錄>      # exit 0＝乾淨；1＝有問題（逐行印出）
    python pubkey_policy.py check --file <licensing.py>
"""
import argparse
import ast
import io
import os
import sys

LICENSING_REL = os.path.join("backend", "helpers", "licensing.py")
DEV = "_PUBKEY_DEV"
PROD = "_PUBKEY_PROD"
_NAMES = (DEV, PROD)
STRIPPED_LINE = '%s = b""  # LG-O1: 正式公鑰已填入，出貨包不帶開發公鑰（tools/platform/pubkey_policy.py 建包時改寫）' % DEV


def _target_names(node):
    """一個賦值節點會碰到哪些我們在意的名字（只看 Name 目標；解構賦值也算）。"""
    out = []
    targets = []
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        targets = [node.target]
    elif isinstance(node, ast.NamedExpr):
        targets = [node.target]
    elif isinstance(node, (ast.For, ast.AsyncFor)):
        targets = [node.target]
    elif isinstance(node, (ast.With, ast.AsyncWith)):
        targets = [i.optional_vars for i in node.items if i.optional_vars is not None]
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        return [(a.asname or a.name.split(".")[0]) for a in node.names if (a.asname or a.name.split(".")[0]) in _NAMES]
    for t in targets:
        for n in ast.walk(t):
            if isinstance(n, ast.Name) and n.id in _NAMES:
                out.append(n.id)
    return out


def inspect_source(source):
    """⇒ (dev_bytes|None, prod_bytes|None, dev_node|None, problems)。看不懂的一律進 problems（fail-closed）。"""
    problems = []
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return None, None, None, ["licensing.py 解析失敗：%s" % e]
    # 全檔找所有碰到這兩個名字的賦值；只有『模組層級、單一目標、純 Assign』那一筆算數
    top_plain = {n: [] for n in _NAMES}
    for node in ast.walk(tree):
        names = _target_names(node)
        if not names:
            continue
        is_top = node in tree.body
        plain = isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
        for name in names:
            if is_top and plain:
                top_plain[name].append(node)
            else:
                problems.append("%s 有不認得的寫法（第 %d 行，%s）：不是模組層級單一賦值" % (name, getattr(node, "lineno", 0), type(node).__name__))
    for stmt in ast.walk(tree):                       # `global _PUBKEY_DEV` ＝ 函式裡打算改它
        if isinstance(stmt, ast.Global):
            for name in stmt.names:
                if name in _NAMES:
                    problems.append("%s 在函式裡被宣告 global（第 %d 行）：執行期可能被改寫" % (name, stmt.lineno))
    vals, nodes = {}, {}
    for name in _NAMES:
        found = top_plain[name]
        if len(found) != 1:
            problems.append("%s 的模組層級賦值有 %d 筆（必須恰好 1 筆）" % (name, len(found)))
            continue
        node = found[0]
        nodes[name] = node
        try:
            val = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            problems.append("%s 不是 bytes 字面值（第 %d 行）" % (name, node.lineno))
            continue
        if not isinstance(val, bytes):
            problems.append("%s 的值不是 bytes（第 %d 行，%s）" % (name, node.lineno, type(val).__name__))
            continue
        vals[name] = val
    return vals.get(DEV), vals.get(PROD), nodes.get(DEV), problems


def _nonempty(b):
    return bool(b is not None and b.strip())


def policy_problems(source):
    """⇒ 問題清單（空＝乾淨）。"""
    dev, prod, _node, problems = inspect_source(source)
    out = list(problems)
    if not problems and _nonempty(prod) and _nonempty(dev):
        out.append("LG-O1：%s 已填入正式公鑰，但包內仍帶著開發公鑰 %s（開發私鑰簽的授權會被當成有效授權）" % (PROD, DEV))
    return out


def strip_source(source):
    """⇒ (新原始碼, 是否改寫)。正式公鑰為空或開發公鑰已空 ⇒ 原樣；看不懂 ⇒ ValueError（fail-closed）。"""
    dev, prod, node, problems = inspect_source(source)
    if problems:
        raise ValueError("；".join(problems))
    if not _nonempty(prod) or not _nonempty(dev):
        return source, False
    lines = source.splitlines(keepends=True)
    first, last = node.lineno - 1, node.end_lineno          # end_lineno 為 1-based 且含
    tail = lines[last - 1]
    nl = "\r\n" if tail.endswith("\r\n") else ("\n" if tail.endswith("\n") else "")
    new = "".join(lines[:first]) + STRIPPED_LINE + (nl or "\n") + "".join(lines[last:])
    after = policy_problems(new)
    if after:
        raise ValueError("改寫後仍有問題：%s" % "；".join(after))
    return new, True


def _licensing_path(pkg):
    return os.path.join(pkg, LICENSING_REL)


def _read(path):
    with io.open(path, encoding="utf-8", newline="") as f:
        return f.read()


def main(argv=None):
    # 訊息含中文：不論主控台碼頁是什麼（cp932／cp950）都不可以因為印不出來而崩潰成「沒擋住」或「看不到原因」
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="LG-O1：正式公鑰就位後，包內不帶開發公鑰")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("strip")
    s.add_argument("--pkg", required=True)
    c = sub.add_parser("check")
    g = c.add_mutually_exclusive_group(required=True)
    g.add_argument("--pkg")
    g.add_argument("--file")
    a = ap.parse_args(argv)

    if a.cmd == "strip":
        path = _licensing_path(a.pkg)
        if not os.path.isfile(path):
            print("[pubkey_policy] 找不到 %s ⇒ 無法處理（不是 PASS）" % path)
            return 2
        try:
            new, changed = strip_source(_read(path))
        except ValueError as e:
            print("[pubkey_policy] FAIL: %s" % e)
            return 1
        if changed:
            with io.open(path, "w", encoding="utf-8", newline="") as f:
                f.write(new)
            print("[pubkey_policy] 已把包內 %s 改寫成 b\"\"（正式公鑰已填入）：%s" % (DEV, path))
        else:
            print("[pubkey_policy] 不需改寫（%s 為空，或 %s 已為空）：%s" % (PROD, DEV, path))
        return 0

    path = a.file or _licensing_path(a.pkg)
    if not os.path.isfile(path):
        print("[pubkey_policy] 找不到 %s ⇒ 無法檢驗（不是 PASS）" % path)
        return 2
    probs = policy_problems(_read(path))
    for p in probs:
        print("[pubkey_policy] FAIL: %s" % p)
    if not probs:
        print("[pubkey_policy] OK：%s" % path)
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
