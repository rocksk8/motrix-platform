# -*- coding: utf-8 -*-
"""去識別化 S6：建包的 audience 邏輯（`build_deploy_package.ps1 -Audience own|sale` 呼叫；獨立成 Python 才測得動）。

  python tools/platform/deid_build.py apply --pkg <包目錄> --audience own|sale --commit <sha> --product <名稱> --out <deid.json>
        [--own-payload <檔>] [--key <金鑰檔> --hashlist <清單.json>] [--repo <repo>]

## own 包（自用）
- **一律要有本公司資料檔**（own_payload.json；`--own-payload` 或環境變數 MOTRIX_OWN_PAYLOAD）：缺／驗不過 ⇒ 建包中止。
  凍結 migration（`_m008`／`_m106`）與弱密碼清單在正式機都要它；沒有它的 own 包在正式機會 migration 失敗或少判兩個舊密碼。
  通過 ⇒ 複製成包內 `backend/migrations_frozen/own_payload.json`。
- 不剪、不擋。有給金鑰＋清單就掃描並記命中數（只記錄，方便追蹤）；沒給就記 `hits: null`。

## sale 包（客戶）
1. 包內**不得**有本公司資料檔；剪裁＋剪段＋客戶版文件＋manifest 投影（`deid_project.prune_tree`）；
2. `deid_project.verify_tree` 要過；
3. **投影要能從 git 重算**：由 `--commit`＋設定＋overlay 重建一份，與包逐檔比對（除建包才產生的檔外逐位元組相同，version_manifest 比解析後內容）；
4. 掃描**必過**：金鑰＋清單必給；清單新鮮（30 天）、金絲雀掃得到、誤判登記檔本身合規；虛構登記檔（deid_fiction.json）合規；
   scan 有任何命中 ⇒ 建包中止（只印 路徑:行號:類別:值代碼，不印明文）。
輸出 JSON（`deploy_manifest.json` 的 `deid`）：audience、hits、key_id、list_created、canary、prune 報告、投影輸入（設定／overlay 的 blob 雜湊、基準版號）、不含任何開發機路徑。
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import deid_fiction as F  # noqa: E402
import deid_project as P  # noqa: E402
import deid_scan as S  # noqa: E402
import own_payload as OP  # noqa: E402

PAYLOAD_REL = "backend/migrations_frozen/own_payload.json"
#: 建包才會產生、不在 git 裡的檔（重算比對時略過）
GENERATED = ("deploy_manifest.json", "backend/.build_commit", "backend/export_ignore.json")
FICTION = HERE / "deid_fiction.json"
ALLOW = HERE / "deid_allow.json"


class BuildError(Exception):
    pass


def _blob(repo, commit, rel):
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "%s:%s" % (commit, rel)], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def payload_problems(path):
    """⇒ [問題]（不含值）。"""
    if not path or not Path(path).is_file():
        return ["找不到本公司資料檔（--own-payload 或環境變數 MOTRIX_OWN_PAYLOAD）"]
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        return ["本公司資料檔讀不懂：%s" % type(e).__name__]
    return OP.verify_payload(d)


def _scan(pkg, key_path, hashlist_path, required):
    """⇒ (hits, key_id, created)。required（sale）：缺金鑰／清單、清單過期、金絲雀掃不到、誤判登記不合規 ⇒ BuildError。"""
    if not (key_path and hashlist_path):
        if required:
            raise BuildError("sale 包必須做雜湊層掃描：缺 --key／--hashlist")
        return None, None, None
    try:
        key = S.load_key(key_path)
        hl = S.load_hashlist(hashlist_path, key)
    except (ValueError, OSError) as e:
        raise BuildError("清單／金鑰不能用：%s" % e)
    prob, _note = S.check_freshness(hl)
    if prob:
        raise BuildError(prob)
    c = S.canary_check(hl)
    if c:
        raise BuildError(c)
    allow = S.load_json_list(str(ALLOW)) if ALLOW.is_file() else []
    fiction = S.load_json_list(str(FICTION)) if FICTION.is_file() else []
    probs = S.allow_problems(allow) + F.problems(fiction)
    if probs:
        raise BuildError("登記檔不合規：" + "；".join(probs))
    hits = S.scan(pkg, hl, fiction, allow)
    return hits, S.key_id(key), str(hl.created)


def verify_rebuild(pkg, repo, commit, product, cfg=None):
    """由 commit 重算出 sale 包的內容樹，與包逐檔比對（建包才產生的檔略過；version_manifest 比解析後內容，PowerShell 那段會重排格式）。⇒ [問題]。"""
    ignore = GENERATED + (P.MANIFEST_REL,)
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "r"
        P.rebuild(commit, out, product, repo, cfg)
        a, b = P.tree_digest(pkg, ignore), P.tree_digest(out, ignore)
        probs = []
        for rel in sorted(set(a) | set(b)):
            if a.get(rel) != b.get(rel):
                probs.append("%s：%s" % (rel, "包裡多出來（git 重算沒有）" if rel not in b else ("包裡缺（git 重算有）" if rel not in a else "內容與 git 重算不同")))
        try:
            same = json.loads((Path(pkg) / P.MANIFEST_REL).read_text(encoding="utf-8-sig")) == json.loads((out / P.MANIFEST_REL).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            same = False
        if not same:
            probs.append("%s：投影結果與 git 重算不同" % P.MANIFEST_REL)
    return probs


def apply(pkg, audience, commit, product="full", repo=REPO, own_payload=None, key=None, hashlist=None):
    pkg = Path(pkg)
    if audience not in ("own", "sale"):
        raise BuildError("audience 只能是 own 或 sale：%r" % audience)
    payload = own_payload or os.environ.get("MOTRIX_OWN_PAYLOAD")
    if audience == "own":
        probs = payload_problems(payload)
        if probs:
            raise BuildError("own 包一律要有本公司資料檔：" + "；".join(probs))
        dst = pkg / PAYLOAD_REL
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(payload, dst)
        hits, kid, created = _scan(pkg, key, hashlist, required=False)
        return {"audience": "own", "hits": None if hits is None else len(hits), "list_created": created, "key_id": kid,
                "own_payload": True, "canary": hits is not None}
    # ── sale ──
    if (pkg / PAYLOAD_REL).exists():
        raise BuildError("sale 包內有本公司資料檔（%s）——建包來源被污染" % PAYLOAD_REL)
    cfg = P.load_config(REPO / "product" / "sale_prune.json" if repo == REPO else Path(repo) / "product" / "sale_prune.json")
    rep = P.prune_tree(pkg, cfg)
    probs = P.verify_tree(pkg, cfg)
    if probs:
        raise BuildError("剪裁後驗證不過：" + "；".join(probs))
    rb = verify_rebuild(pkg, repo, commit, product, cfg)
    if rb:
        raise BuildError("包與 git 重算不一致：" + "；".join(rb[:10]))
    hits, kid, created = _scan(pkg, key, hashlist, required=True)
    if hits:
        raise BuildError("掃描有 %d 筆命中（路徑:行號:類別:值代碼）：%s" % (len(hits), "；".join("%s:%d:%s:%s" % (h.path, h.line, h.kind, h.value_id) for h in hits[:20])))
    return {"audience": "sale", "hits": 0, "list_created": created, "key_id": kid, "canary": True, "own_payload": False,
            "prune": rep, "projection_inputs": {"manifest_baseline": cfg["manifest_baseline"],
                                                "sale_prune_blob": _blob(repo, commit, "product/sale_prune.json"),
                                                "overlay_blob": _blob(repo, commit, "backend/version_manifest_sale_overlay.json"),
                                                "fiction_blob": _blob(repo, commit, "tools/platform/deid_fiction.json"),
                                                "allow_blob": _blob(repo, commit, "tools/platform/deid_allow.json")}}


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("apply")
    a.add_argument("--pkg", required=True)
    a.add_argument("--audience", required=True)
    a.add_argument("--commit", required=True)
    a.add_argument("--product", default="full")
    a.add_argument("--out", required=True)
    a.add_argument("--own-payload")
    a.add_argument("--key")
    a.add_argument("--hashlist")
    a.add_argument("--repo", default=str(REPO))
    args = ap.parse_args(argv)
    try:
        block = apply(args.pkg, args.audience, args.commit, args.product, args.repo, args.own_payload, args.key, args.hashlist)
    except (BuildError, P.ProjectError) as e:
        print("DEID_BUILD_FAIL %s" % e)
        return 1
    Path(args.out).write_text(json.dumps(block, ensure_ascii=False, indent=1), encoding="utf-8")
    print("DEID_BUILD_OK audience=%s hits=%s" % (block["audience"], block["hits"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
