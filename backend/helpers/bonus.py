# -*- coding: utf-8 -*-
"""獎金分潤的**純邏輯**（`FN2`）：基數、拆分、人員、可見性。

施工圖：`docs/windows/SPEC-BONUS.md`。
第一行逐字：``# 獎金分潤 `FN2` —— **施工圖**``

使用者原話：「獎金分潤子模組是依據案件的**實際獲利**去拆比例給參與者」。

# 🔴 這一支**不重算任何係數**

淨利的算式只寫在一個地方（`frontend/pages/settlement.html`，儲存時算），
後端兩個讀它的地方（`pdf_gen.py`／`routers/reports.py`）都是**讀已存值**。
```
獎金若自己再乘一次 => **第三份實作，而三份一定會分岔**
=> 分岔之後「獎金算出來跟精算頁對不上」會被當成**精算頁的錯**
```
⇒ 這裡一律取 `settlement.summary.netProfit` 的**已存值**。

# 🔴 而更危險的是**退回用毛利**

`routers/reports.py` 有一段 fallback，註解逐字寫著
「Fallback to gross fields for legacy settlements saved before netProfit was
recorded.」——**對報表是合理的折衷**（寧可有個數字）。
```
☠️ 而獎金照抄它：毛利 > 淨利 => **獎金發多**
   而它**不報錯，畫面上每一個數字都正常**
```
⇒ 沒有淨利 ⇒ **拒絕**，而拒絕訊息要講得出**出路**。

📌 〈模組化：L2 功能模組彼此不可依賴〉：本支不碰資料庫、不 import 任何 router。
"""

#: 比例的單位：**基點**（1/10000）。
#:
#: ⚙️ 用整數基點而不是浮點百分比 —— 浮點相加不等於 1 是一個
#:    **沒有錯誤訊息**的缺陷：三個 0.3333 加起來不是 1，而沒有人會看到。
BASIS_POINTS = 10000

#: 基數的唯一來源。寫成常數是為了讓「它從哪來」可以被查，
#: 而 `bonus_awards.base_source` 會把它一起凍進每一筆。
BASE_FIELD = "netProfit"

#: 舊精算的拒絕訊息。**必須講出路** ——
#:
#: ☠️ 只說「沒有淨利」的副作用是**舊案永遠發不了獎金**，而使用者看不出路在哪。
#: 🔑 出路存在：淨利是**儲存精算時**算出來寫進去的
#:    ⇒ 重新儲存一次就會補上。
#: 📌 與 `RAISE(ABORT)` 那一條同源：**那句話是使用者唯一看得到的東西。**
LEGACY_SETTLEMENT_MESSAGE = (
    "這個案件的精算是舊格式（沒有淨利欄位），無法產生獎金單。\n"
    "請重新開啟並儲存一次該案的精算，系統會自動補算淨利後即可發放。")


def base_amount_for(settlement):
    """回 `(ok, base, err)` —— 獎金基數。

    ```
    沒有 netProfit 這個欄位  => (False, 0, 舊格式訊息)   **不可退回用毛利**
    netProfit <= 0           => (False, 0, 說明)          使用者裁：負數當 0 不發
    netProfit > 0            => (True, 值, None)
    ```

    ## ⚠️ 「沒有這個欄位」與「值是 0」是兩件事

    ☠️ 寫成 `summary.get("netProfit") or ...` 的話，**淨利剛好是 0 的案子**
       會被當成舊格式 ⇒ 使用者收到「請重新儲存精算」，而他照做之後
       **還是 0，訊息還是一樣** ⇒ 他會以為系統壞了。
    ⇒ 用 `is None` 分辨（〈null 不等於 0〉）。
    """
    summary = (settlement or {}).get("summary") or {}
    raw = summary.get(BASE_FIELD)
    if raw is None:
        # 🔴 這裡**不看 grossProfit** —— 見模組 docstring。
        return False, 0, LEGACY_SETTLEMENT_MESSAGE

    value = int(raw)
    if value <= 0:
        # 使用者裁：負數當 0 不發。
        # ☠️ 硬發的話，負的獎金在傳票上是一筆反向分錄，**帳是平的**，
        #    沒有人會報修 —— 而某個人的獎金單上是一個負數。
        return False, 0, (
            "這個案件的淨利是 %s，沒有可分配的獎金基數。" % f"{value:,}")
    return True, value, None


#: `SPEC-BN6-BN7.md §1`：逐字抄 `settlement.html` 的十二格鍵名與順序。
#: 🔴 `BN6` 一個數字都不重算——10%／1% 只寫在 `settlement.html`，
#: 這裡只把 `summary` 已存的值原樣帶出來。改動任何一個字要回那份規格。
#: 📌 `SPEC-BN11-BN12.md §2`：原本定義在 `routers/bonus.py`，`BN11` 搬到
#: 這裡——`bonus_pdf.py`（helper）不可以 import router，搬過來才有單一
#: 來源可以共用，不是為了搬而搬。
SETTLEMENT_FIELDS = (
    "quotedPretax", "quotedTotal",
    "itemActualTotal", "extraTotal", "dispatchTotal", "totalActualCost",
    "grossProfit", "grossMarginPct", "adminCost", "charityDonation",
    "netProfit", "netMarginPct",
)


def settlement_fields(settle):
    """把 `settlement.summary` 的十二格原樣帶出，**缺的回 `None`，不是 `0`**
    （〈null 不等於 0〉）——`summary` 本身是空的（`MQ-EXPFILE-001` 那種）與
    `summary` 缺某一欄，兩種情況這裡自然地都回 `None`，不必分兩支寫。
    """
    summary = (settle or {}).get("summary") or {}
    return {k: summary.get(k) for k in SETTLEMENT_FIELDS}


#: `SPEC-BN11-BN12.md §2`：精算明細表的**列定義**（鍵、標籤、格式），
#: 順序即顯示順序。**這是唯一一份**——`bonus_pdf.py` 的 PDF 與
#: `bonus.html` 的 `bn-settle`（現有 HTML，文字逐字抄自這裡）都以它為準，
#: `settlement.html` 那份**本輪不動**（前端寫死的表格，改寫不在 BN11
#: 範圍內），靠守門釘兩邊文字一致，不是靠兩邊都讀同一份程式碼。
#:
#: 🔴 第 10 列（`netProfit`）的 `note` 是使用者 2026-09-23 裁示要印的
#: 「（＝獎金分潤基數）」——**不是與 `settlement.html` 的漂移**，那句話
#: 正是使用者這次強調的因果（「必須有詳細金額最後算出真實淨利，才能用
#: 真實淨利去算獎金」）。
#: ⚠️ `quotedTotal`（含稅總額）不在列定義裡——它是 `quotedPretax` 那一列
#: 的**註記**，不是獨立的一列（`bonus.html` 的 `bn-settle__note` 已經是
#: 這樣做的）。
SETTLEMENT_ROWS = (
    ("quotedPretax",    "報價稅前收入",     "money", ""),
    ("itemActualTotal", "品項實際成本",     "money", ""),
    ("extraTotal",      "額外支出",         "money", ""),
    ("dispatchTotal",   "承攬商派發成本",   "money", ""),
    ("totalActualCost", "實際總成本",       "money", ""),
    ("grossProfit",     "真實毛利",         "money", ""),
    ("grossMarginPct",  "真實毛利率",       "pct1",  ""),
    ("adminCost",       "管銷分攤（10%）",  "money", ""),
    ("charityDonation", "公益捐款（1%）",   "money", ""),
    ("netProfit",       "真實淨利",         "money", "（＝獎金分潤基數）"),
    ("netMarginPct",    "真實淨利率",       "pct1",  ""),
)


def pool_for(base, total_pct):
    """總獎金池 ＝ `base × total_pct / 10000`（整數，無條件捨去）。"""
    return int(base) * int(total_pct) // BASIS_POINTS


def split_award(base, total_pct, people):
    """把獎金池拆給每個人。回 `[{username, person_pct, amount}, …]`。

    ```
    pool   = base × total_pct / 10000
    amount = pool × person_pct / 10000
    尾差   = pool - Σamount  =>  **歸公司**（A 裁），不落在任何一個人身上
    ```

    ## ⚙️ 為什麼尾差不補給最後一個人

    補給誰都是一個**沒有依據的決定**，而它每次都落在同一個人身上
    （清單順序通常是穩定的）⇒ 那個人會固定多拿幾塊錢。
    🔑 歸公司是唯一不需要理由的選擇。

    ⚠️ 不變量：`Σamount <= pool`，且 `pool - Σamount < 人數`。
       **大於人數表示那不是捨入誤差，是算式錯了。**
    """
    pool = pool_for(base, total_pct)
    out = []
    for entry in people or ():
        username, person_pct = entry[0], entry[1]
        out.append({
            "username": username,
            "person_pct": int(person_pct),
            "total_pct": int(total_pct),
            # 🔑 先乘後除：`pool * pct // BP`。
            #    反過來（先除後乘）會讓每一項先各自損失一次精度。
            "amount": pool * int(person_pct) // BASIS_POINTS,
        })
    return out


def remainder_of(base, total_pct, lines):
    """尾差（歸公司的那一塊）。呼叫端要把它記下來，不要讓它消失。"""
    return pool_for(base, total_pct) - sum(l["amount"] for l in lines or ())


#: 每個獎金項目各自綁一個人員來源。
#:
#: 🔴 **只有兩個**，而那是使用者原話逐字定的：
#:    「業務獎金→`sales_person`／專案執行獎金→`case_stages.assigned_to`」。
#:
#: ## ☠️ 這裡原本有 `owner` 與 `engineer`，已拿掉（A 裁，2026-09-23）
#:
#: 那兩個是**規格自己加的**，而 `quotations` 上**沒有那兩個欄位**
#: （實查 `PRAGMA table_info`）⇒ 用它們建的獎金項目**永遠發不出去**。
#: ⚠️ 留著並標「尚未支援」也被否決：那會讓畫面上永遠有兩個點不下去的選項，
#:    而**沒有人答得出它們什麼時候會支援**。
#:
#: ## 📌 已知的未來來源：`quotations.assigned_user_ids`
#:
#: 那個欄位**真的存在**（A 實查；我原本與 A-2 都沒列到它）。
#: ⚠️ 而它**這一輪刻意不接** —— 沒有紅燈、沒有裁示。
#:    寫在這裡是為了讓下一個人**不必重新去找**，不是為了暗示它該被加進來。
PERSON_SOURCES = (
    "sales_person",             # 業務
    "case_stages.assigned_to",  # 各執行階段負責人（JSON 陣列）
)

#: 來源解析不出任何人時的標記。**不可以靜默算成 0 筆。**
NO_ELIGIBLE_PEOPLE = "無可發放對象"


def people_for_item(item, case):
    """這個獎金項目在這個案件上該發給誰。回 `(ok, people, note)`。

    ## 🔴 解析出 0 人 ⇒ **拒絕該項目**，不是靜默算 0

    `case_stages.assigned_to` 的預設值是 `'[]'`（空陣列）
    ⇒ **空是常態不是例外**。
    ☠️ 靜默算 0 的兩個後果，第二個更糟：
    ```
    ① 那個項目從來沒出現在任何一張獎金單上 —— 而**沒有人會發現一個
       從來不出現的東西**
    ② **把金額併給別的項目** => 別人領多了，**而總額對得起來**
    ```

    ## ⚠️ 階段負責人要**逐筆解析 JSON**，不能用一句 SQL 彙整

    `db.py` 對 `case_stages.assigned_to` 的註解逐字寫著「刻意維持 JSON text
    欄位，不再往下正規化成 join table」⇒ 這一層只能在應用層做。
    """
    import json

    source = ((item or {}).get("person_source") or "").strip()
    if not source:
        # 🔑 資料層的 NOT NULL 擋不住空字串 ⇒ 這裡是另一半。
        return False, [], "這個獎金項目沒有設定人員來源，無法決定發給誰。"

    case = case or {}
    people = []

    if source == "case_stages.assigned_to":
        for stage in case.get("stages") or ():
            raw = stage.get("assigned_to")
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw or "[]")
                except ValueError:
                    # ⚠️ 壞掉的 JSON **不要吞** —— 吞掉就變成「這一階段沒有人」，
                    #    而那與「真的沒有人」在結果上一模一樣。
                    return False, [], (
                        "案件階段的負責人資料格式不正確，無法解析發放對象。")
            for name in raw or ():
                if name and name not in people:
                    people.append(name)
    else:
        name = case.get(source)
        if name and name not in people:
            people.append(name)

    if not people:
        return False, [], NO_ELIGIBLE_PEOPLE
    return True, people, None


def visible_lines(lines, username, is_admin=False):
    """這個人看得到哪幾列。

    ```
    管理者  全部
    本人    **只看得到自己那一列**
    其他人  看不到
    ```
    🔴 施工圖 `§七` 逐字：**現行營運報表的可見範圍不可沿用** ——
       沿用＝**全公司看得到每個人領多少**。
    📌 「本人」是一條**規則**不是一個角色 ⇒ 明著比對 `username`，
       不從角色推論。
    """
    if is_admin:
        return list(lines or ())
    return [l for l in (lines or ()) if l.get("username") == username]


#: 「應付獎金」要記在哪個科目 —— **設定值的鍵**，不是代號本身。
#:
#: 🔴 那個科目**未決**（會計師三題之一）⇒ 代號不可以寫死進 DDL 或程式碼。
#: 🔑 而預設值的判準不是「哪個比較好」，是「**猜錯時哪個比較好收拾**」：
#: ```
#: 用法定科目  => 日後要拆出來 ＝ 新增一個科目 ＋ 改設定
#: 用自訂科目而會計師說不行 => **已開出的傳票都指向一個不該存在的科目**
#: ```
#: ⇒ 預設用法定的「應付薪資」（代號見 `DEFAULT_PAYABLE_ACCOUNT`）。
PAYABLE_ACCOUNT_SETTING_KEY = "bonus_payable_account_code"

#: 預設代號。**放在設定的預設值裡，不是散在程式邏輯裡** ——
#: 改它只要改設定，不必改碼，而已開出的傳票凍的是當時的值。
DEFAULT_PAYABLE_ACCOUNT = "2191"


#: `BN8`：前兩層沿用傳票的既有慣例（覆核／主管），第三層起才用「第 N 層」——
#: 沒有設定過簽核流程時（見 bonus_signatures_of() 的呼叫端）鏈是空的，
#: 這裡不會被用到；一旦設定了，版面文字與傳票一致，使用者不必學兩套說法。
_TIER_LABELS = ("覆核", "主管")

#: `SPEC-BN8.md §1`：「製表」是建立者，不是簽核，與傳票「製票」同一個做法
#: ——刻意用不同的字（A-2 複核）：傳票的製單人在會計上就叫「製票」，
#: 獎金分潤單不是傳票，叫「製表」。若有人想統一成同一個字，答案是刻意
#: 不同，統一之後其中一邊會紅在正確實作上。
MAKER_SLOT = "製表"


class BonusChainUnreadable(Exception):
    """簽核鏈存在而讀不出來。與「沒有簽核鏈」是兩件事，不可以折疊在一起
    （道理與 `helpers/voucher.py::VoucherChainUnreadable` 相同）。"""


def _bonus_chain_tiers(award):
    """`award["approval_json"]` 裡的 `tiers`。

    ```
    沒有 approval_json（或 '{}'）  => 回 []（明確的「沒有鏈」）
    有而解析失敗                  => raise BonusChainUnreadable
    ```
    """
    raw = award.get("approval_json")
    if not raw:
        return []
    import json
    try:
        return (json.loads(raw) or {}).get("tiers") or []
    except (TypeError, ValueError) as exc:
        raise BonusChainUnreadable(
            "這張獎金分潤單的簽核資料讀不出來，無法判斷是否已完成簽核。"
        ) from exc


def bonus_signatures_of(award):
    """獎金分潤單的簽核格：`{格名: {by, at}}`，格名是「製表／覆核／主管／
    第 N 層」。

    ## 🔴 `SPEC-BN8.md §1`：**只讀 `approval_json`，沒有投影欄位可以退回**

    ```
    傳票    v99 已有 submitted_by/at、checked_by/at、manager_by/at
            => signatures_of() 有鏈時照鏈畫，沒鏈時退回那六欄
    獎金單  bonus_awards **一格都沒有**（只有 created_by／created_at）
            => 這裡只讀鏈，沒有 fallback 分支
    ```
    ⚠️ 沒有設定過簽核流程時鏈是空的 ⇒ 這裡只回「製表」一格——是不是要再
    退回一個內建的預設層，是送審端點（`routers/bonus.py`）的決定，不是
    這支版面函式的事。
    """
    out = {MAKER_SLOT: {"by": award.get("created_by") or "",
                        "at": award.get("created_at") or ""}}
    try:
        tiers = _bonus_chain_tiers(award)
    except BonusChainUnreadable:
        out["簽核資料無法讀取"] = {"by": "", "at": ""}
        return out
    for i, tier in enumerate(tiers):
        label = _TIER_LABELS[i] if i < len(_TIER_LABELS) else "第 %d 層" % (i + 1)
        out[label] = {"by": (tier or {}).get("approvedBy") or "",
                      "at": (tier or {}).get("approvedAt") or ""}
    return out


def is_paid(award) -> bool:
    """這張獎金分潤單的錢出去了沒有。**兩條路都走這一支**
    （`SPEC-BN8.md §5c` 界線③）。

    ```
    主路  出納開發放傳票 -> 回填 voucher_no_payment
    退路  最高管理者手動標記 -> 寫 paid_manually_at（不可偽造 voucher_no_payment）
    ```
    ☠️ 查詢「已發放的單」時只認其中一條路，另一條會**消失**——這支是唯一
    的判準來源，查詢端與端點都要用它，不要在別處各寫一次條件。
    """
    return bool((award.get("voucher_no_payment") or "").strip()
                or (award.get("paid_manually_at") or "").strip())


def payable_account_code(get_setting):
    """讀「應付獎金」的科目代號。`get_setting` 是取設定的那支函式。

    ⚠️ 傳進來而不是直接 import `helpers.settings`：這一支要能在**沒有資料庫**
       的情況下被測到，而相依注入比 monkeypatch 誠實。
    ⚙️ 而設定值指向一個**不存在或已停用**的科目時，擋它的是設定頁不是這裡 ——
       這一支只負責回報「設定說是哪一個」。
    """
    value = (get_setting(PAYABLE_ACCOUNT_SETTING_KEY) or "").strip()
    return value or DEFAULT_PAYABLE_ACCOUNT
