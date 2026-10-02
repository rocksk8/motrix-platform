# -*- coding: utf-8 -*-
"""出貨請款類型（`helpers/expense_type_defs/*.json`，版本 0＝程式預設）的「申請人」欄位說明改成白話（使用者裁示，第 32 班）：
「這一欄會自動帶入申請人；管理者可在設計器解除鎖定」。

這次**只准動 `applicant.help` 一個字串**：
① 四個預設類型除 `applicant.help` 以外的內容（排序後的 JSON）雜湊＝改動前的雜湊——欄位、明細、版面、輸出版型、編號一個字都沒變
② 新說明文字照裁示、不含工程用語（locked／定義／key）
③ 四個預設仍通過 `validate_expense_type`；`help` 不參與驗證與輸出（驗證長度上限內），所以釘在版本 0 的舊單據驗證結果不變
④ 公司已發布的版本（版本 ≥1）是發布當時的內容副本，不會被這次改動牽動（`get_type(version=N)` 讀庫、不讀檔）
反向控制：把任一預設的其他欄位改一個字 ⇒ ① 紅。"""
import copy
import hashlib
import json

import pytest

from helpers import expense_types as ET

NEW_HELP = "這一欄會自動帶入申請人；管理者可在設計器解除鎖定"
#: 改動前（help 欄除外）的 canonical JSON sha256（第 31 班出貨狀態，origin/platform 09d13fdf 實算）
FROZEN = {
    "petty_cash": "e730414edeffcd8422e631479204138c769c6bbf7e46bb4b917fef9d2cd0d8b2",
    "purchase_order": "9aa1f66a6fb20124c949649bb14afb6c5237cd3142aa7e342e150bf2739fa46d",
    "purchase_req": "38c30b7a0c02f89453cbf73ff3264413a91ce28240fcd6375b4202c68e8a5073",
    "travel": "1e774ca4074634e1c5c6d3c8a63982580eafa2f5b945135b3b970a9b48ce5202",
}


def _without_applicant_help(d):
    d = copy.deepcopy(d)
    for f in d["fields"]:
        if f["key"] == "applicant":
            f.pop("help", None)
    return d


def _digest(d):
    return hashlib.sha256(json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


@pytest.mark.parametrize("code", sorted(FROZEN))
def test_only_the_applicant_help_text_changed(code):
    d = ET._default_for(code)
    assert _digest(_without_applicant_help(d)) == FROZEN[code], "預設定義除了 applicant.help 之外被改動了"
    app = next(f for f in d["fields"] if f["key"] == "applicant")
    assert app["help"] == NEW_HELP
    assert app["locked"] is True and app["default"] == {"$": "requester"} and app["type"] == "ref" and app["target"] == "users"   # 鎖定與預填語意不變


@pytest.mark.parametrize("code", sorted(FROZEN))
def test_new_help_has_no_engineering_words_and_defaults_still_validate(code):
    d = ET._default_for(code)
    help_ = next(f for f in d["fields"] if f["key"] == "applicant")["help"]
    for w in ("locked", "定義", "key", "false", "true"):
        assert w not in help_, w
    assert ET.validate_expense_type(d, code) == []


def test_reverse_control_changing_any_other_field_turns_the_digest_red():
    d = ET._default_for("travel")
    d["fields"][1]["label"] = d["fields"][1]["label"] + "！"
    assert _digest(_without_applicant_help(d)) != FROZEN["travel"]


def test_published_versions_are_copies_in_the_database_not_the_shipped_file(client):
    """版本 ≥1 讀 ui_definitions（發布當時的副本）；只有版本 0（程式預設）讀檔 ⇒ 這次只影響仍釘在版本 0 的顯示文字。"""
    import db
    from core import definitions as D
    old = ET._default_for("travel")
    for f in old["fields"]:
        if f["key"] == "applicant":
            f["help"] = "舊說明（公司發布當時）"
    conn = db.get_db()
    try:
        D.save_draft(conn, ET.KIND, "travel", "company", old, "t")
        D.publish(conn, ET.KIND, "travel", "company", "舊版", "t")
        conn.commit()
        v1 = ET.get_type(conn, "travel", 1)["body"]
        v0 = ET.get_type(conn, "travel", 0)["body"]
        assert next(f for f in v1["fields"] if f["key"] == "applicant")["help"] == "舊說明（公司發布當時）"
        assert next(f for f in v0["fields"] if f["key"] == "applicant")["help"] == NEW_HELP
    finally:
        conn.close()
