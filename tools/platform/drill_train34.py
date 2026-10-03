# -*- coding: utf-8 -*-
"""第 34 班套用演練（骨架；基線＝prod/8ae8b8cc＝第 33 班A 已套用的正式機現況）。由 drill_train33 複製：通用零件（交付／套用／回滾／A→C→E→B）沿用 drill_train_apply／30／31，
本班判準寫在 `CHECKS`（目前全是 **未實作的紅燈樁**——整合分支（wip/train-34-int1）出來、種子資料與預期值確定後逐題換成真判準；樁會讓演練明確失敗，不會誤報綠）。

用法（同 drill_train33）：
  python tools/platform/drill_train34.py --delivery-root <交付資料夾> --name <包名> --new-commit <SHA>       [--base-commit 8ae8b8cc] [--expect-schema k=N ...] [--expect-db-version N] [--runs A,C,E,B] [--keep]

本班要涵蓋（主持 2026-10-03 指派；細節待整合分支）：
  34a M2 變更申請 migration 0006 對**正式機資料形狀**的升級（種子＝正式機現況：材料申請筆數／狀態分布，合成資料；升級後逐欄不變、新表／新欄預設、回滾回舊形狀）
  34b 出貨單連動（出貨單 ↔ 材料申請／採購單連結：舊出貨單不連結仍可用；有已到料且有剩餘量卻沒連 ⇒ 送審前警示）
  34c D7 鎖定（全額付款的舊材料申請不能改金額、新額不低於已付）
  34d D12 設計器預設開的切換（預設開、?designer=0／localStorage 可切回；舊的「預設關」判準 15_designer_default_off 要換成「預設開」）
  34e 沿用 33 班判準：19a–19h 在 33A 已上線，34 班只需確認 voucher 表與分期流程不退化（用 19d 的精簡版）
紅線同 TRAIN29-DRILL：不碰正式機／金鑰；全合成資料；埠 6760 只綁 127.0.0.1（由 da 獨占）；跑完清。
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import drill_train30 as T30  # noqa: E402
import drill_train31 as T31  # noqa: E402

T = T30.T

#: 班別參數：schema／db_version 待整合分支確定（None＝不判定、只記錄「沒有 schema 版本變小」）
TRAIN = {"number": 34, "base": "8ae8b8cc", "schema": {}, "db_version": None}
_FAILED = []


def seed34(root, port):
    """基線（第 33 班A 程式）種子——待補：M2 前的材料申請形狀、舊出貨單、已全額付款的材料申請、設計器設定。"""
    return {"todo": "seed34 尚未實作"}


def record34(rec, root):
    return rec


def _todo(key, what):
    return (False, {"status": "未實作的紅燈樁", "todo": what})


def checks34(root, port, base_rec, new_rec, t0, package_modules):
    res = T31.checks31(root, port, base_rec, new_rec, t0, package_modules)
    for k in ("15_designer_default_off", "16_subcontract_schema_stays_3", "9c_legacy_dispatch_untouched", "16_material_tables_exist_and_empty"):
        res.pop(k, None)                          # 15：D12 預設改開（見 34d）；其餘是舊班的專屬題
    res["34a_m2_migration_0006_on_prod_shaped_data"] = _todo("34a", "種子＝正式機形狀的材料申請；升級後逐欄不變、新表／新欄預設；C 回滾後舊形狀")
    res["34b_shipping_link"] = _todo("34b", "舊出貨單不連結仍可用；有已到料且有剩餘量卻沒連 ⇒ 送審前警示")
    res["34c_d7_lock_full_paid_material_request"] = _todo("34c", "全額付款的舊材料申請改金額 ⇒ 拒絕；新額不低於已付")
    res["34d_designer_default_on_and_switch_back"] = _todo("34d", "設計器預設開；可切回舊畫面")
    res["34e_installment_flow_not_regressed"] = _todo("34e", "沿用 drill_train33 的 19d（分期→最後一期→作廢 LIFO）")
    return res


CHECKS = checks34


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--expect-db-version", type=int)
    ap.add_argument("--expect-schema", action="append", default=[])
    known, rest = ap.parse_known_args(argv)
    T31._EXPECT["db_version"] = known.expect_db_version if known.expect_db_version is not None else TRAIN.get("db_version")
    schema = dict(TRAIN["schema"])
    for kv in known.expect_schema:
        k, v = kv.split("=")
        schema[k] = int(v)
    T31._EXPECT["schema"].update(schema)
    T.deliver = T31.deliver31
    orig_main = T.main

    def main_with_hooks(a):
        T.checks_after_apply = CHECKS
        prev_rec, prev_mb = T.record, T.make_baseline

        def rec(root):
            return record34(prev_rec(root), root)

        def mb(base, port, commit):
            root, info = prev_mb(base, port, commit)
            info["train34_seed"] = seed34(root, port)
            return root, info
        T.record, T.make_baseline = rec, mb
        return orig_main(a)
    T.main = main_with_hooks
    if "--base-commit" not in rest:
        rest += ["--base-commit", TRAIN["base"]]
    rc = T30.main(rest)
    for why, info in _FAILED:
        print("FAIL:", why, json.dumps(info, ensure_ascii=False))
    return 1 if _FAILED else rc


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
