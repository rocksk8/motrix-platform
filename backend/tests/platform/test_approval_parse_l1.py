"""簽核鏈 approval_json 的解析在 L1（主持裁示 M06-c，2026-09-26）。

- 契約：`helpers/tiered_approval.py` 不 import 任何 L2（routers／modules／歸在 L2 組的 helper）。
- M06 `helpers.voucher` 的同名別名（淘汰中）指向 L1 的**同一個**物件：`except VoucherChainUnreadable` 一定接得到 L1 丟的例外。
- M01 的簽核佇列不再 import M06（`helpers.voucher`）。
正對照／反向控制用合成原始碼，不綁任何 L2 模組。
"""
import ast
import json
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
MODULES_JSON = BACKEND.parent / "docs" / "platform" / "modules.json"


def _l1_helpers():
    d = json.loads(MODULES_JSON.read_text(encoding="utf-8"))
    return {u.split(":", 1)[1] for u in d["L1"]["units"] if u.startswith("helper:")}


def l2_imports(src, l1_helpers):
    """原始碼裡指向 L2 的 import：routers.*、modules.*、不在 L1 清單上的 helpers.*（含相對 import）。"""
    bad = []
    for n in ast.walk(ast.parse(src)):
        names = []
        if isinstance(n, ast.Import):
            names = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            mod = n.module or ""
            if n.level:                                   # from .x import y ⇒ helpers.x
                names = ["helpers." + mod] if mod else ["helpers." + a.name for a in n.names]
            else:
                names = [mod]
        for name in names:
            head = name.split(".")
            if head[0] in ("routers", "modules"):
                bad.append(name)
            elif head[0] == "helpers" and len(head) > 1 and head[1] not in l1_helpers:
                bad.append(name)
    return bad


def test_positive_and_reverse_control_of_the_scanner():
    l1 = {"settings", "tiered_approval"}
    ok = "import json\nfrom .settings import _get_setting\nfrom helpers.settings import x\n"
    assert l2_imports(ok, l1) == []
    for src, want in (("from routers.vouchers import a\n", "routers.vouchers"),
                      ("import modules.accounting.voucher\n", "modules.accounting.voucher"),
                      ("from .voucher import parse_approval_json\n", "helpers.voucher"),
                      ("from helpers.quotations import guard\n", "helpers.quotations")):
        assert l2_imports(src, l1) == [want], src


def test_tiered_approval_imports_no_l2():
    l1 = _l1_helpers()
    assert "tiered_approval" in l1 and "settings" in l1, "modules.json 的 L1 清單讀不到 ⇒ 這一題會假綠"
    src = (BACKEND / "helpers" / "tiered_approval.py").read_text(encoding="utf-8")
    assert l2_imports(src, l1) == []


def test_voucher_aliases_are_the_l1_objects():
    from helpers import tiered_approval as ta
    from helpers import voucher
    assert voucher.VoucherChainUnreadable is ta.ApprovalChainUnreadable      # 同一個類別，不是另一個同名類別
    assert voucher.parse_approval_json({"id": 1}) == {} == ta.parse_approval_json({"id": 1})
    assert voucher.parse_approval_json({"approval_json": '{"tiers": []}'}) == {"tiers": []}
    with pytest.raises(voucher.VoucherChainUnreadable) as ei:                # 舊呼叫端的 except 接得到 L1 丟的
        ta.parse_approval_json({"id": 7, "approval_json": "{壞掉"})
    assert "單據" in str(ei.value)
    with pytest.raises(ta.ApprovalChainUnreadable) as ei:
        voucher.parse_approval_json({"id": 8, "approval_json": "{壞掉"})
    assert "傳票" in str(ei.value)


def test_m01_approval_queue_no_longer_imports_m06():
    src = (BACKEND / "routers" / "quotations.py").read_text(encoding="utf-8")
    assert "from helpers.voucher import parse_approval_json" not in src
    # 〔更正（C，M01-PLAN §3-7 c-approval）：~~M01 改自 L1 tiered_approval 解析~~ 轉簽的傳票簽核鏈改由 M06 的
    #  `approval.reassign` 提供者讀寫，M01 不再解析傳票；該提供者用的是 L1 的解析〕
    assert "parse_approval_json" not in src
    vsrc = (BACKEND / "routers" / "vouchers.py").read_text(encoding="utf-8")
    assert "from helpers.tiered_approval import parse_approval_json, ApprovalChainUnreadable" in vsrc
