# -*- coding: utf-8 -*-
"""設定中心跨群組批次儲存端點的金標案例（S2／S1c）。記錄『錯誤形狀』（4xx，鍵集＝detail）：不存在的群組在寫入前就被拒（一組都不寫）。
成功形狀（groups／classification／recipients 預覽、409 衝突 body、單一通知）由 tests/platform/test_settings_batch_*.py 與
tests/test_e2e_settings_center_shell_2026_11_14.py 以真實使用者逐項斷言；成功回應的 groups 鍵隨群組資料長出來，不適合進金標。"""
_E = (4,)
CASES = [
    {"key": "POST /api/settings-center/batch", "url": "/api/settings-center/batch",
     "body": {"groups": {"no_such_group": {"values": {"x": 1}}}, "reason": "金標：不存在的群組"}, "expect": _E},
]
WAIVE = {}
