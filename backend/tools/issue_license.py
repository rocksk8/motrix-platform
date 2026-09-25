"""離線授權簽發 CLI（2026-09-21，細線 1 第 1 步）。

**這支不連任何東西**——沒有伺服器、不碰資料庫。簽發是一個離線動作：拿私鑰、
簽一個 JSON、把 blob 交給客戶放進 `backend/license.key`。

用法
----

    # 這台機器的指紋（要裝授權的那台自己跑，把結果回報給簽發的人）
    python tools/issue_license.py fingerprint

    # 產一把新的開發金鑰對（已存在就拒絕覆蓋）
    python tools/issue_license.py genkey

    # 簽一把授權
    python tools/issue_license.py issue \
        --customer "第二家公司股份有限公司" --tax-id 87654321 \
        --machine 0123456789abcdef --modules tender_radar,case \
        --days 365 --out license.key

⚠️ 私鑰
-------
預設讀 `backend/tools/_license_private_key_dev.pem`，那是**開發用**的。
它簽出來的授權 `env == "dev"`，跟正式授權長得一模一樣但查得出來（見
`helpers/licensing.py` 開頭）。正式私鑰的保管方式是 `docs/windows/STATE.md`
§4 第 1 項的未決事項，**在它定案之前不要用這支簽真的要出貨的授權**。

私鑰檔已被 `.gitignore` 涵蓋（`**/*_private_key*.pem`）。私鑰一旦進了 git 歷史
就拔不乾淨，而離線驗證**沒有撤銷清單**——已發出的授權撤不回來。
"""
import argparse
import os
import sys
from datetime import date, timedelta

_TOOLS_DIR   = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_TOOLS_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from helpers.licensing import (  # noqa: E402 — sys.path 要先補好才 import 得到
    LICENSE_KIND_PERPETUAL,
    LICENSE_KIND_SUBSCRIPTION,
    machine_fingerprint,
    sign_license,
    verify_license,
)

DEFAULT_KEY = os.path.join(_TOOLS_DIR, "_license_private_key_dev.pem")


def _utf8_stdout():
    """Windows 主控台預設 CP950，印中文會炸。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


# ── 子指令 ───────────────────────────────────────────────────────────────────

def cmd_fingerprint(args):
    print(machine_fingerprint())
    return 0


def cmd_genkey(args):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    dst = args.out or DEFAULT_KEY
    if os.path.exists(dst) and not args.force:
        print(f"[拒絕] 已存在，不覆蓋：{dst}", file=sys.stderr)
        print("       蓋掉舊私鑰＝所有用它簽出去的授權全部失效，而且救不回來。",
              file=sys.stderr)
        print("       真的要換，先把舊的搬走，再加 --force。", file=sys.stderr)
        return 2

    priv = ed25519.Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    with open(dst, "wb") as fh:
        fh.write(priv_pem)
    try:
        os.chmod(dst, 0o600)
    except OSError:
        pass

    print(f"私鑰已寫入：{dst}")
    print("")
    print("把下面這段公鑰貼進 backend/helpers/licensing.py 的 _PUBKEY_DEV：")
    print("")
    for line in pub_pem.decode("ascii").splitlines():
        print(f'    b"{line}\\n"')
    print("")
    print("⚠️ 貼完立刻確認 `git status` 看不到那個 .pem 檔。")
    return 0


def cmd_issue(args):
    if not os.path.isfile(args.key):
        print(f"[錯誤] 找不到私鑰：{args.key}", file=sys.stderr)
        print("       先跑 `python tools/issue_license.py genkey` 產一把。",
              file=sys.stderr)
        return 2

    if args.expires:
        try:
            expires = date.fromisoformat(args.expires)
        except ValueError:
            print(f"[錯誤] --expires 不是 YYYY-MM-DD：{args.expires!r}",
                  file=sys.stderr)
            return 2
    else:
        expires = date.today() + timedelta(days=args.days)

    issued = args.issued or date.today().isoformat()
    machine = (args.machine or machine_fingerprint()).strip().lower()

    modules = [m.strip() for m in args.modules.split(",") if m.strip()]
    if not modules:
        print("[錯誤] --modules 不可為空（全開請寫 '*'）", file=sys.stderr)
        return 2

    with open(args.key, "rb") as fh:
        priv_pem = fh.read()

    payload = {
        "customer": args.customer,
        "tax_id":   args.tax_id,
        "machine":  machine,
        "modules":  modules,
        "issued":   issued,
        "expires":  expires.isoformat(),
        # kind 會自動落在簽章範圍內（sign_license 簽的是除 sig 外的全部欄位），
        # 所以客戶把 subscription 改成 perpetual 會被 bad_signature 擋下來。
        "kind":     args.kind,
    }
    blob = sign_license(payload, priv_pem)

    # 簽完當場驗一次。簽發是離線動作，產出一把驗不過的金鑰交給客戶，
    # 要等到對方裝上去才會發現。
    status = verify_license(blob)
    if status["reason"] == "bad_signature":
        print("[錯誤] 自我複驗失敗：剛簽出來的金鑰用內嵌公鑰驗不過。",
              file=sys.stderr)
        print("       表示 helpers/licensing.py 裡的公鑰跟這把私鑰不是一對。",
              file=sys.stderr)
        return 3

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(blob + "\n")
        print(f"金鑰已寫入：{args.out}")
    else:
        print(blob)

    print("", file=sys.stderr)
    print(f"  客戶     {payload['customer']}（統編 {payload['tax_id']}）", file=sys.stderr)
    print(f"  機器     {machine}", file=sys.stderr)
    print(f"  模組     {', '.join(modules)}", file=sys.stderr)
    print(f"  有效期   {issued} ~ {payload['expires']}", file=sys.stderr)
    if args.kind == LICENSE_KIND_PERPETUAL:
        print("  種類     永久授權（到期後仍可使用，只是不再提供更新）", file=sys.stderr)
    else:
        print("  種類     年費授權（到期後會擋住業務 API）", file=sys.stderr)
    print(f"  簽發環境 {status['env']}", file=sys.stderr)
    if status["env"] != "prod":
        print("  ⚠️ 這是**開發用**金鑰（env=dev），不要交給真的客戶。", file=sys.stderr)
    if status["reason"] == "machine_mismatch":
        print("  （在這台機器上驗是 machine_mismatch —— 正常，這把是簽給別台的）",
              file=sys.stderr)
    return 0


# ── 進入點 ───────────────────────────────────────────────────────────────────

def main(argv=None):
    _utf8_stdout()
    parser = argparse.ArgumentParser(
        description="MOTRIX-ERP 離線授權簽發工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("fingerprint", help="印出這台機器的指紋").set_defaults(
        func=cmd_fingerprint)

    p_gen = sub.add_parser("genkey", help="產一把新的 Ed25519 金鑰對")
    p_gen.add_argument("--out", default=None, help=f"私鑰輸出路徑（預設 {DEFAULT_KEY}）")
    p_gen.add_argument("--force", action="store_true",
                       help="覆蓋已存在的私鑰（會讓舊授權全部失效）")
    p_gen.set_defaults(func=cmd_genkey)

    p_iss = sub.add_parser("issue", help="簽一把授權金鑰")
    p_iss.add_argument("--customer", required=True, help="客戶名稱")
    p_iss.add_argument("--tax-id", required=True, dest="tax_id", help="統一編號")
    p_iss.add_argument("--machine", default=None,
                       help="目標機器指紋（預設：本機）")
    p_iss.add_argument("--modules", default="*",
                       help="模組清單（各模組 module.json 的 license_key，預設＝modules/ 資料夾名），逗號分隔；'*' 代表全開（預設 '*'）")
    p_iss.add_argument("--days", type=int, default=365,
                       help="有效天數（預設 365；--expires 優先）")
    p_iss.add_argument("--expires", default=None, help="到期日 YYYY-MM-DD")
    p_iss.add_argument("--issued", default=None, help="簽發日 YYYY-MM-DD（預設今天）")
    p_iss.add_argument("--kind", default=LICENSE_KIND_SUBSCRIPTION,
                       choices=[LICENSE_KIND_SUBSCRIPTION, LICENSE_KIND_PERPETUAL],
                       help="授權種類：subscription＝年費（到期擋住）、"
                            "perpetual＝永久（到期只提示）。預設 subscription —— "
                            "預設值要往「會擋住」那一邊倒，簽錯成永久是救不回來的")
    p_iss.add_argument("--key", default=DEFAULT_KEY, help="私鑰路徑")
    p_iss.add_argument("--out", default=None,
                       help="金鑰輸出檔（預設印到 stdout）")
    p_iss.set_defaults(func=cmd_issue)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
