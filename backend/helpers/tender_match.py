"""標案比對（2026-09-21，細線 6 第 3 步）。**全部是純函式，不碰 DB、不碰 request。**

抽出來的理由跟 `helpers/procurement.py` 一樣：比對規則是這條線唯一「會被人改」的地方
（關鍵字、排除詞、金額區間都是使用者設的），而**會被改的東西必須驗得動**。

## 這一支在防的那個錯

**「沒填」不是「填了 0」，也不是「篩出 0 筆」。**

- `org=None` ＝ 不篩機關；寫成 `tender["org"] == watch["org"]` 的話，沒填就等於
  「只收機關名是空字串的標案」—— **一筆都不會中，而且安靜**。
- `budget_max=None` ＝ 不篩上限；`None` 被當成 `0` 的話，「沒填上限」變成「上限 0 元」，
  同樣是一筆都不會中、同樣安靜。

⚠️ 所以這裡**任何一個篩選條件都先問 `is None`**，不用真假值——
`0` 是合法的金額下限，`""` 是合法（雖然無用）的機關名。
（同 `helpers/procurement.py` 的前置時間，是同一家族的錯。）
"""


def _as_list(value):
    """關鍵字／排除詞：允許 list、單一字串、或 None。"""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    return [str(v).strip() for v in value if str(v).strip()]


def matches(tender, watch):
    """這一筆標案有沒有命中這一個搜尋條件。

    順序是刻意的：**排除詞排在關鍵字後面但優先於命中**——
    「即使關鍵字也命中，排除詞一中就整筆排除」（§3 條件 2）。
    """
    if not watch.get("enabled", 1):
        return False

    name = str(tender.get("name") or "")

    keywords = _as_list(watch.get("keywords"))
    if keywords and not any(k in name for k in keywords):
        return False

    # 排除詞一中就整筆排除，不管關鍵字中了幾個。
    if any(x in name for x in _as_list(watch.get("excludes"))):
        return False

    # ⚠️ 用 `is not None`：沒填 = 不篩。寫成 `if watch.get("org"):` 的話，
    # 空字串與 None 會被合併成同一件事——雖然這裡結果剛好一樣，但下一個欄位
    # （budget_min=0）就不一樣了，規則不一致比規則錯更難查。
    org = watch.get("org")
    if org is not None and str(org).strip():
        if str(tender.get("org") or "") != str(org):
            return False

    budget = tender.get("budget")
    bmin = watch.get("budget_min")
    bmax = watch.get("budget_max")
    if bmin is not None or bmax is not None:
        # 標案沒寫預算（None）時，任何一邊有設限就無從判斷。
        # 這裡選擇**不命中**：命中的話使用者會收到一筆他明確說過不要的東西，
        # 而且不會知道那是因為對方沒公告金額。
        if budget is None:
            return False
        if bmin is not None and budget < bmin:
            return False
        if bmax is not None and budget > bmax:
            return False

    return True


def match_watches(tender, watches):
    """回傳這一筆標案命中的 watch 清單（可能多個）。

    一筆標案命中多個 watch 是正常的——去重是 `tender_hits` 的
    `UNIQUE(watch_id, tender_id)` 在管，不是這裡。
    """
    return [w for w in (watches or []) if matches(tender, w)]
