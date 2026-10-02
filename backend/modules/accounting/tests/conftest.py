# -*- coding: utf-8 -*-
"""會計模組測試共用：功能旗標的有效值＝紀錄開著 且 在 READY 裡（features.flags）。
其他題目（401、扣繳、補登、分錄引擎…）要驗的是功能本身，所以預設把 READY 視為全部功能；
驗 READY 本身的題（檔名含 `c5_ready`、題名含 `unbuilt_features`）不套用，直接看真實的 READY。"""
import pytest


@pytest.fixture(autouse=True)
def _all_features_ready_unless_testing_ready(request, monkeypatch):
    if "c5_ready" in request.node.nodeid or "unbuilt_features" in request.node.nodeid:        # 驗『開發中』本身的題：看真實的 READY
        return
    from modules.accounting.ledger import features
    monkeypatch.setattr(features, "READY", frozenset(features.FEATURES))
