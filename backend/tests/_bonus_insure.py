"""U4（2026-09-25）：獎金分潤標記已發放前，名單上每個人都必須有投保金額（否則 409，不以 0 計算）。

既有題目驗的是別的事（簽核、傳票、頁面），在撥付前呼叫 `insure_all()` 給名單上的人一個投保金額。
投保金額存在 `system_settings["payroll_insurance_profiles"]`（modules.payroll.bonus_deductions.PROFILE_KEY）。
"""
import json

DEFAULT_INSURED = 45800


def insure_all(amount=DEFAULT_INSURED):
    """所有帳號都設投保金額（題目裡的名單都是測試帳號）。"""
    import db
    from modules.payroll.bonus_deductions import PROFILE_KEY
    conn = db.get_db()
    try:
        prof = {r["username"]: {"insuredAmount": amount} for r in conn.execute("SELECT username FROM users")}
        conn.execute(
            "INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (PROFILE_KEY, json.dumps(prof), "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()
