"""案件角色（caseRecord.roles 的 filler／sales／executor）的兩種形狀（CM3，2026-09-24）。

新格式：{"username": "...", "display": "..."}——display 是指定當下的名稱，只給人看；判斷一律用 username。
舊格式：顯示名稱字串——升級轉換時查不到或同名的「不猜、保留原值」（db.py::_m116_case_roles_username），
所以讀取端永遠要吃兩種形狀。未對應的清單見 GET /api/system/case-roles-unmapped。
"""

ROLE_KEYS = ("filler", "sales", "executor")
ROLE_LABELS = {"filler": "填表人", "sales": "業務負責", "executor": "執行負責"}


def role_username(v):
    """物件形狀的帳號；舊字串或空值回 None。"""
    if isinstance(v, dict):
        return (v.get("username") or "").strip() or None
    return None


def role_display(v) -> str:
    """給人看的名稱：物件取 display（沒有就退回 username）；舊字串原樣；其他回空字串。"""
    if isinstance(v, dict):
        return (v.get("display") or v.get("username") or "").strip()
    if isinstance(v, str):
        return v.strip()
    return ""


def is_role_object(v) -> bool:
    return isinstance(v, dict) and bool(role_username(v))
