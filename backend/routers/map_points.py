"""地圖：把有地址的東西畫在同一張圖上。**共用能力，不是標案雷達的一部分。**

2026-09-21 使用者裁示：「**我即便沒有在雷達內，也要能用地圖**」。

## 🔴 這不是改個名字

搬家之前：`/api/tender-radar/map`、`_require_radar()`、跟著 `radar_on()`。
⇒ **沒有雷達模組權限的人叫不到地圖；雷達一關，地圖跟著死。**
而那牴觸模組化原則：**共用能力要下沉，L2 功能模組之間不可相依。**
**地圖是共用能力，標案只是它的其中一個資料來源。**

## ⚠️ 權限：端點對「已登入」開放，**資料來源各自過濾**

`require_any_module` 只有 superadmin 直通（`helpers/auth.py:148`），
所以把整個端點綁在 `map` 這個 key 上，會讓「沒有雷達也能用地圖」變成
「**沒有地圖 key 也不能用地圖**」——換了一個名字的同一個問題。

⇒ 端點只要求登入，**而每一個資料來源自己檢查自己的權限**：
沒有雷達模組的人看得到地圖，**只是上面沒有標案點**。
🔑 而那個「沒有」**必須說出來**（`sources` 欄位），不可以只是少一層點——
☠️ 「你沒有權限看標案」與「今天沒有標案」在畫面上都是一張沒有點的地圖，
而那是今天第五個長成那個樣子的成因。
"""
import copy
import datetime
import hashlib
import json
import logging
import threading
import time

from fastapi import APIRouter, Header, HTTPException, Response

from db import db_conn
from helpers import _require_user, user_has_module
from helpers import geo
from helpers import row_access

logger = logging.getLogger(__name__)

router = APIRouter()

#: 地圖自己的模組 key。**刻意不沿用 `tender_radar`** ——
#: 沿用的話「不在雷達內也能用地圖」這件事就沒有地方成立。
#: 📌 它管的是**側邊欄入口**，不是這個端點的守衛（見檔頭〈權限〉）。
MAP_MODULE_KEY = "map"


#: 每一個資料集：它的表、地址欄、顯示名、以及**它自己的權限**。
#:
#: 🔴 權限一律**沿用那份資料原本的入口**，不是另外發明一套：
#: `contractors` 是**外包名冊（自然人）**——那張表有 `id_number`（身分證號）與
#: `bank_account_number`，所以那個 `address` 是**住家地址**。
#: ☠️ 把它畫在一張「已登入就看得到」的地圖上，**等於從一扇新的門把保護降級**，
#: 而地圖會**正常運作**，只是保護變低了。
#: 🔑〈降級之後它還是會動〉：**壞掉會被報修，降級不會。**
#:
#: 📌 `completion_notes` **刻意不在這裡**：實測 0 筆。
#: 不為一張空表寫實作——那份程式碼沒有任何東西會驗它，
#: 而它會一直看起來像「已經支援了」。
_DATASETS = {
    "contractors": {
        "table": "contractors", "address": "address", "label": "外包名冊",
        # ⚠️ `routers/contractors.py` 是 superadmin ＋ `contractor_list` 兩者都要，
        # 而這裡只要求模組。**那是一個放寬**，由 C 的 P12d 釘死。
        # 📌 理由（我的理解）：名冊端點會回身分證號與銀行帳號，
        # 而地圖只回**名稱與地址** ⇒ 暴露面不同。
        # 🔴 但那個地址仍然是**住家地址**，所以模組這一道不可以再拿掉。
        "modules": ("contractor_list",),
    },
    "vendor_contractors": {
        "table": "vendor_contractors", "address": "address", "label": "協力廠商",
        "modules": ("procurement", "case_manage", "contractor_list"),
    },
    "shipping_notes": {
        "table": "shipping_notes", "address": "delivery_address", "label": "出貨單",
        "modules": ("case_manage", "quotation"),
    },
    # ── 地址在 `data_json` 裡的兩個來源 ────────────────────────────────
    # ⚠️ 這兩張表**沒有 address 欄位**（實測：`customers` 與 `suppliers` 的
    # 欄位只有 id／name／tax_id／phone／data_json／…）⇒ 地址是 JSON 裡的鍵。
    "customers": {
        "table": "customers", "label": "客戶",
        # 從 `routers/customers.py` 讀的，不是從規格抄的。
        "modules": ("customer", "case_manage", "dev_crm", "procurement"),
        # 🔴 **一個來源可以產出多個 dataset。**
        # 發票地址與送貨地址是**兩件事**，不是同一個點的兩個屬性：
        # 🔑 送貨地址才是業務上**會跑的地方**，發票地址通常是登記地
        # ⇒ 合併的話「我要去哪裡」這個問題就答不出來。
        #
        # 📌 **送貨排在前面**：兩個地址相同時去重留下先出現的那一個，
        # 而留下「送貨」比留下「發票」更接近使用者想問的事。
        "json": (("customers_delivery", "deliveryAddress", "客戶（送貨地址）"),
                 ("customers_invoice", "invoiceAddress", "客戶（發票地址）")),
    },
    "suppliers": {
        "table": "suppliers", "label": "供應商",
        # 從 `routers/suppliers.py` 讀的。
        "modules": ("customer", "procurement", "inventory"),
        "json": (("suppliers", "address", "供應商"),),
    },
}


#: 🔴 **背景暖快取刻意不碰的來源。**
#:
#: `contractors` 是**外包名冊（自然人）**，那個 `address` 是**住家地址**。
#: ☠️ 地圖在有權限的人打開時查它，是**有人要求**；
#: 背景迴圈查它，是**沒有人要求而我們把它送出去**。
#: 🔑 兩者在技術上一樣、在性質上不一樣，而**只有後者是我們自己決定的**。
#: 📌 代價很小：實測只有 5 個相異地址，需要時走前景那條路照樣查得到。
#: ⚠️ 這是我（B）做的決定，不是規格裡的 —— 已回報 A。
_WARM_EXCLUDED = ("contractors",)


@geo.register_warm_source
def _map_geocode_backlog():
    """地圖會用到的所有地址。**給背景暖快取當待辦。**

    📌 `geo` 不認識任何一張業務表（〈模組化〉：共用能力不可以綁死 ERP 的
    schema），所以待辦是由**這一層**註冊進去的。
    ⚠️ 這裡**不檢查權限**：它不回給任何人，只決定「先去查哪些地址」。
    而查到的座標進 `geocode_cache`，讀出來時仍然要過 `_may_see_dataset`。
    """
    out = []
    # 🔴 **據點的地址也要進佇列**（BR13）。
    # ⚠️ 不納入的話，新增一個分公司之後**要等到有人打開地圖才會被定位** ——
    # 🔑 而那正是 §3v 整節要解決的事（使用者不必按任何按鈕）。
    # 📌 而它與 `_WARM_EXCLUDED` 不衝突：**據點是公司的營業地址，
    # 不是自然人的住家** —— 那個排除只針對 `contractors`。
    for loc in _profile_locations(_company_profile()):
        address = str(loc.get("address") or "").strip()
        if address:
            out.append(address)
    with db_conn() as conn:
        for r in conn.execute("SELECT org, location FROM tenders").fetchall():
            org = (r["org"] or "").strip()
            # ⚠️ 被截斷的名稱不查 —— 與前景那條路同一個判準
            # （`_locate_tender`）。兩邊不一致的話，背景會把一個
            # **錯的**座標寫進快取，而前景永遠讀得到它。
            if org and not geo.looks_truncated(org):
                out.append(org)
            place = (r["location"] or "").strip()
            if place:
                out.append(place)

        for name, spec in _DATASETS.items():
            if name in _WARM_EXCLUDED:
                continue
            if spec.get("json"):
                rows = conn.execute(
                    f"SELECT data_json FROM {spec['table']}").fetchall()
                for row in rows:
                    try:
                        data = json.loads(row["data_json"] or "{}")
                    except (TypeError, ValueError):
                        continue          # 壞掉的那一筆跳過，不拖垮其他筆
                    if not isinstance(data, dict):
                        continue
                    for _dataset, key, _label in spec["json"]:
                        value = str(data.get(key) or "").strip()
                        if value:
                            out.append(value)
            else:
                col = spec["address"]
                rows = conn.execute(
                    f"SELECT {col} AS addr FROM {spec['table']} "
                    f"WHERE {col} IS NOT NULL AND TRIM({col}) <> ''").fetchall()
                out += [str(r["addr"] or "").strip() for r in rows]

        # `MP6`：案件交貨地點也進背景預熱（規格：走既有地址定位階梯與背景預熱）。
        #   📌 這裡不看權限——它只決定「先查哪些地址」，讀出來時照樣過 `_case_points` 的篩選。
        for r in conn.execute("SELECT data_json FROM quotations").fetchall():
            addr = _case_address(r["data_json"])
            if addr:
                out.append(addr)
    return out


#: 有地址欄位、但**刻意不查**的資料集。回報它們、但不碰那些表。
_NOT_QUERIED = {
    "completion_notes": "完工單目前沒有可用的地址資料（實測 0 筆），這個來源尚未支援",
}


def _may_see_dataset(user, name) -> bool:
    """這個使用者看不看得到這一份資料。**判準與那份資料原本的入口相同。**"""
    spec = _DATASETS[name]
    if (user or {}).get("role") == "superadmin":
        return True
    mods = (user or {}).get("modules") or []
    if isinstance(mods, str):
        import json
        try:
            mods = json.loads(mods)
        except (TypeError, ValueError):
            mods = []
    return any(m in mods for m in spec["modules"])


def _own_points(name, located, user_coord=None, budget=None):
    """把一份自有資料的地址畫成點。回 `(points, 沒有地址或定位不到的筆數)`。"""
    spec = _DATASETS[name]
    if spec.get("json"):
        return _json_points(name, located, user_coord, budget)
    col = spec["address"]
    # ⚠️ **`with get_db()` 是錯的**：sqlite 連線的 `with` 管的是**交易**，
    # 不是關閉 ⇒ 那個連線永遠不會關。要走 `db_conn()`。
    # 📌 而它同時解掉另一件：`db_conn()` 在呼叫當下才從 `db` 取 `get_db`，
    # 所以測試把間諜裝在 `db.get_db` 上看得到；
    # `from db import get_db` 拿的是副本，**間諜裝了也打不到**。
    name_col = "customer_name" if spec["table"] == "shipping_notes" else "name"
    # `MP1`：出貨單沒有自己的頁，連結要落在它所屬的案件上 ⇒ 一併取 quote_no。
    is_ship = spec["table"] == "shipping_notes"
    with db_conn() as conn:
        rows = conn.execute(
            f"SELECT id, {name_col} AS name, {col} AS addr"
            f"{', quote_no' if is_ship else ''} FROM {spec['table']} "
            f"WHERE {col} IS NOT NULL AND TRIM({col}) <> ''"
        ).fetchall()

    budget = budget or _GeocodeBudget()
    points, missing = [], 0
    for r in rows:
        found = budget.locate(r["addr"])
        if found is None:
            # ⚠️ **不算進 `missing`**：「這次來不及查」與「查不到」是兩件事，
            # 而它們的處置相反（前者再按一次就好，後者要去改地址）。
            continue
        if not found.coord:
            missing += 1
            continue
        points.append({
            "dataset": name,
            # 🔴 `MP1`：點位要連得回它的單據 ⇒ 帶記錄 id（前端據此組連結與 `?focus=`）。
            "recordId": r["id"],
            **({"quoteNo": r["quote_no"]} if is_ship else {}),
            "name": r["name"], "address": r["addr"],
            "lat": found.coord[0], "lon": found.coord[1],
            "precision": found.precision, "source": found.source,
            **_distances(found.coord, located, user_coord),
        })
    return points, missing


def _json_points(name, located, user_coord=None, budget=None):
    """地址在 `data_json` 裡的來源（客戶／供應商）。

    ## 🔴 一筆壞資料只能拖垮**它自己**
    ☠️ `data_json` 壞掉或缺鍵的那一筆要落進 `withoutLocation`，
    **不可以讓整個來源回空或回 500** —— 那會讓其餘十幾筆一起消失，
    而畫面上那是「**沒有客戶**」。
    🔑〈讀不到的欄位要拒絕那一筆，不要送空值〉的鄰居：
    **拒絕那一筆，不是拒絕整批。**
    ⚠️ 所以這裡**不可以**寫成 `try: … except: return []`。

    ## 📌 `missing` 是**以「筆」為單位**，不是以「地址欄位」為單位
    一個客戶只填了發票地址、沒填送貨地址，那是**正常的**，不該被算成
    「定位不到」。⇒ 一整筆**一個點都產不出來**時才 +1。
    （實測：13 筆客戶裡 9 筆有發票地址、7 筆有送貨地址。）
    """
    spec = _DATASETS[name]
    with db_conn() as conn:
        rows = conn.execute(
            f"SELECT id, name, data_json FROM {spec['table']}").fetchall()

    budget = budget or _GeocodeBudget()
    points, missing = [], 0
    for r in rows:
        try:
            data = json.loads(r["data_json"] or "{}")
        except (TypeError, ValueError):
            # ⚠️ 只吞**這一筆**的解析錯誤，而且**不靜靜跳過**：
            # 下面 `made == 0` 會把它算進 `withoutLocation`。
            data = None
        if not isinstance(data, dict):
            data = {}

        seen, made, deferred = set(), 0, False
        for dataset, key, label in spec["json"]:
            addr = str(data.get(key) or "").strip()
            if not addr:
                continue
            if addr in seen:
                # 🔴 兩種地址**相同**時只畫一個點。
                # ☠️ 不去重的話地圖上會有**完全重疊**的兩個標記，
                # 而重疊的標記在畫面上**看不出來是兩個**
                # ⇒ 這個缺陷不會被報修，它只會讓「我有幾個據點」長期答錯。
                continue
            seen.add(addr)
            found = budget.locate(addr)
            if found is None:
                # 這一筆這次來不及查 ⇒ **不可以算成「定位不到」**。
                deferred = True
                continue
            if not found.coord:
                continue
            made += 1
            points.append({
                "dataset": dataset, "datasetLabel": label,
                # `MP1`：同一筆客戶的送貨／發票兩個點帶**同一個** id（連到同一張客戶卡）。
                "recordId": r["id"],
                "name": r["name"], "address": addr,
                "lat": found.coord[0], "lon": found.coord[1],
                "precision": found.precision, "source": found.source,
                **_distances(found.coord, located, user_coord),
            })
        if not made and not deferred:
            missing += 1
    return points, missing


# ══════════════════════════════════════════════════════════════════════
# `MP6`：案件地點（報價／案件的交貨地點）
# ══════════════════════════════════════════════════════════════════════

#: 資料集模組門檻：比照出貨單（規格：「權限比照 shipping（case_manage 或 quotation）」）。
CASE_MODULES = ("case_manage", "quotation")
CASE_LABEL = "案件地點"


def _case_address(data_json):
    """一個案件的交貨地點：案件合約的交貨地址優先，其次報價單的交貨地點。**一案一點。**

    📌 合約的交貨地址是成案後填的、比較準；報價時的「交貨地點」可能只是說明文字。
    ⚠️ 讀不到／壞掉的 JSON ⇒ 回空字串（那一筆算「沒有地點」，不拖垮其他筆）。
    """
    try:
        data = json.loads(data_json or "{}")
    except (TypeError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    contract = ((data.get("caseRecord") or {}).get("contract") or {})         if isinstance(data.get("caseRecord"), dict) else {}
    addr = str((contract.get("deliveryAddress") if isinstance(contract, dict) else "") or "").strip()
    return addr or str(data.get("deliveryLocation") or "").strip()


def _may_see_cases(user) -> bool:
    if (user or {}).get("role") == "superadmin":
        return True
    mods = (user or {}).get("modules") or []
    if isinstance(mods, str):
        try:
            mods = json.loads(mods)
        except (TypeError, ValueError):
            mods = []
    return any(m in mods for m in CASE_MODULES)


def _case_rows_visible_to(user, rows):
    """🔴 **逐筆**套用案件可見性：非 admin／superadmin 只看得到自己名下或被分配的案件。

    ☠️ 只擋模組的話，有 `case_manage` 的業務會在地圖上看到**別的業務的客戶與工地地址**——
       而案件管理頁刻意不給他看（`list_quotations` 的過濾）。
    🔑 判準與列表是同一份：L1 `row_access` 的 `case`，scope="read"（admin+／擁有者／
       被分配／cashier，CM14b）。以前這裡自己再寫一次 admin 與 cashier 例外——兩套規則會
       漂移，而漂移的那一天沒有任何題會紅（search 與動態牆就是這樣漂掉的）。
    """
    return [r for r in rows if row_access.visible("case", user or {}, r, scope="read")]


def _case_points(user, located, budget=None):
    """案件地點。回 `(points, 沒有地點或定位不到的筆數)`——兩者都只算**這個人看得到的**案件。"""
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT id, quote_no, customer_name, project_name, deal_tag, data_json, "
            "sales_person_id, sales_person, assigned_user_ids FROM quotations ORDER BY id DESC").fetchall()
    rows = _case_rows_visible_to(user, rows)
    budget = budget or _GeocodeBudget()
    points, missing = [], 0
    for r in rows:
        addr = _case_address(r["data_json"])
        if not addr:
            continue          # 沒填交貨地點的案件很多（報價階段）——不算「定位不到」
        found = budget.locate(addr)
        if found is None:
            continue          # 這次來不及查 ≠ 查不到
        if not found.coord:
            missing += 1
            continue
        points.append({
            "dataset": "cases",
            # `MP1`：連回案件頁（case-management.html?q=<quote_no>）；焦點鍵 `cases:<quote_no>`。
            "recordId": r["quote_no"], "quoteNo": r["quote_no"],
            "name": r["project_name"] or r["quote_no"], "org": r["customer_name"],
            "dealTag": r["deal_tag"] or "",
            "address": addr,
            "lat": found.coord[0], "lon": found.coord[1],
            "precision": found.precision, "source": found.source,
            **_distances(found.coord, located, None),
        })
    return points, missing


def _may_see_tenders(user) -> bool:
    if (user or {}).get("role") == "superadmin":
        return True
    mods = (user or {}).get("modules") or []
    if isinstance(mods, str):
        import json
        try:
            mods = json.loads(mods)
        except (TypeError, ValueError):
            mods = []
    return "tender_radar" in mods


def _position_from_header(raw):
    """`X-Map-Position: <lat>,<lon>,<accuracy>` 拆成三個。沒給回三個 `None`。

    ## 🔴 為什麼要有這條路：**query string 會被寫到磁碟上**
    ⚠️ 這不是推論，是實測（2026-09-22，uvicorn 0.41.0，`--log-level info`）：

    ```
    INFO:  127.0.0.1:34378 - "GET /api/map/points?sources=tenders
           &lat=24.1657&lon=120.6402&accuracy=35 HTTP/1.1" 200 OK
    ```

    正式機的 `autostart.bat` 是 `uvicorn … --log-level info >> logs/server.log 2>&1`
    ⇒ **每按一次「使用我的位置」，那個人當下的座標就被追加到一個永久檔案裡。**

    ☠️ 而我們原本檢查過的三個地方**全都是乾淨的**：
    `system_settings` 沒寫、`audit_log` 沒寫、`user_request_log` 存的是
    `request.url.path`（Starlette 的 `path` **不含** query string）。
    🔑 〈防護的副作用落在盲側〉：我們把三個想得到的出口都堵了，
    而漏的是**沒有人列進清單的那一個**——它不在我們的程式碼裡，在 web server 裡。

    📌 header 不會進 access log，也不在 `user_request_log` 的欄位裡
    （那張表存的是 method／path／page／status）。
    """
    if not raw:
        return None, None, None
    parts = [p.strip() for p in str(raw).split(",")]
    if len(parts) != 3:
        raise HTTPException(422, "X-Map-Position 的格式是 <lat>,<lon>,<accuracy>")
    return parts[0], parts[1], parts[2]


def _user_position(lat, lon, accuracy):
    """把三個參數變成 `((lat, lon), accuracy_m)`，或 `(None, None)`。

    ## 🔴 沒給誤差就 422，**不可以預設一個**
    一個編出來的誤差值會被畫成一個圈，而那個圈**看起來跟真的一樣**。
    🔑 「我不知道有多準」與「誤差是 50 公尺」是兩件事，
    而後者是一個**宣稱**——我們沒有資格替瀏覽器做那個宣稱。

    ## 🔴 `accuracy=0` 也是 422（A 2026-09-22 裁定，**改掉我原本的決定**）
    我原本寫的是「刻意不特判，因為語意沒有人裁過」。⚠️ **那個理由是錯的層級**：
    ☠️ 真正的問題不是「0 不合理」，是**收下 0 之後畫面會說「誤差約 0 公尺」**，
    而瀏覽器定位沒有任何情境能宣稱誤差為零（GPS 最佳也是數公尺）。
    🔑 **一個具體而錯誤的保證，比不顯示誤差更糟。**
    📌 而它直接繞過 §3n 的核心設計（距離與誤差綁在一起）——
    綁上去的誤差如果可以是 0，**那個設計就白做了**。
    """
    given = [v for v in (lat, lon, accuracy) if v is not None and v != ""]
    if not given:
        return None, None
    if lat is None or lon is None:
        raise HTTPException(422, "lat 與 lon 要一起給")
    if accuracy is None or accuracy == "":
        raise HTTPException(
            422, "給了座標就要給 accuracy（公尺）——我們不替瀏覽器猜一個誤差值")
    try:
        lat_f, lon_f, acc_f = float(lat), float(lon), float(accuracy)
    except (TypeError, ValueError):
        raise HTTPException(422, "lat／lon／accuracy 必須是數字")
    if not -90.0 <= lat_f <= 90.0 or not -180.0 <= lon_f <= 180.0:
        raise HTTPException(422, f"座標超出範圍：({lat_f}, {lon_f})")
    if acc_f <= 0:
        # ⚠️ `<= 0` 不是 `< 0`：0 與負數走同一條路（見上面的說明）。
        raise HTTPException(
            422, f"accuracy 必須大於 0：{acc_f}"
                 "（瀏覽器定位不可能沒有誤差，0 是一個我們不能替它做的保證）")
    return (lat_f, lon_f), acc_f


@router.get("/api/map/points")
def map_points(response: Response, sources: str = "tenders",
               lat: str = None, lon: str = None, accuracy: str = None,
               x_map_position: str = Header(None),
               authorization: str = Header(None)):
    """地圖上的點，以及**所有「為什麼這裡是空的」的理由**。

    ## ☠️ 這個畫面有五個成因會長成同一個樣子（一張乾淨、沒有點的地圖）
    | 成因 | 訊號 |
    |---|---|
    | 標案沒有地點資訊 | `withoutLocation` |
    | 辦公室地址沒填 | `officeMissing` |
    | 沒有 Google 金鑰（附近廠商） | `googleMapsConfigured` |
    | 地理查詢沒開 / 被對方封鎖 | `geoEnabled` |
    | **沒有那個來源的權限** | `sources[].skipped` |
    🔑 **每一個都必須有自己的訊號**，不能靠使用者看圖分辨——
    處置完全不同，而少幾個點跟「那些東西不存在」長得一模一樣，
    **而且沒有人會報修。**

    📌 `sources` 支援 `tenders`／`contractors`／`vendor_contractors`／`shipping_notes`。
    ⚠️ **`completion_notes` 刻意不支援**：實測 0 筆。
    不為一張空表寫實作——那份程式碼沒有任何東西會驗它，
    **而它會一直看起來像「已經支援了」**。
    """
    user = _require_user(authorization)
    wanted = [s.strip() for s in (sources or "").split(",") if s.strip()]
    # 🔴 **並列，不是二選一**：辦公室是穩定的錨點，瀏覽器定位是會變的。
    # 兩者**互相獨立**——公司地址沒填時，定位距離照樣要算得出來
    # （那是新使用者第一天就會遇到的狀態）。
    #
    # 🔴 **這三個參數不可以被寫下來**（隱私）：
    # 不進 `system_settings`、不進 `audit_log`、不進 `user_request_log`。
    # ⚠️ 後者存的是 `path`，而 **query string 就在 path 裡**
    # ⇒ 「順手記下完整網址」就足以把一個人的位置留在磁碟上，
    # 而那張表**會進每日備份**。
    # 🔴 **位置優先從 header 讀**，query string 只是相容路徑（見
    # `_position_from_header` 的說明：query string 會被 uvicorn 寫進
    # `logs/server.log`，而 header 不會）。前端只走 header。
    h_lat, h_lon, h_acc = _position_from_header(x_map_position)
    if h_lat is not None:
        lat, lon, accuracy = h_lat, h_lon, h_acc
    elif any(v is not None and v != "" for v in (lat, lon, accuracy)):
        # 🔴 **直接拒絕，不是警告**（A 2026-09-22 裁定）。
        # 我原本留著這條路，理由是「C 的 13 題都是那個形狀」。
        # ⚠️ A 指出那等於**讓測試決定產品的安全形狀**，而
        # **那 13 題紅是正確的訊號——它們在測一條不該存在的路**。
        # 🔑 而我自己那句話就是判準：「留著就還是一條可以被下一個人寫進去的路。」
        #
        # 📌 訊息要說**改用什麼**，不可以只說「參數不合法」——
        # 只說不合法的話，下一個人會去查參數格式，而格式是對的。
        logger.warning(
            "/api/map/points 收到 query string 形式的座標並已拒絕。"
            "（那串網址已經被 uvicorn 的 access log 寫進 logs/server.log）"
        )   # ⚠️ 這行**不印座標**——印出來就等於自己做了同一件事。
        # 🔑 為什麼座標不可以放在網址上（`EM1 §3⑤`：這段理由原本寫在給使用者看的訊息裡，
        #    搬到這裡——它是這個決定唯一的記錄，不可以刪）：
        #    uvicorn 的 access log 會把整串 query string 寫進 logs/server.log
        #    （一個永久追加的檔案）⇒ 使用者的位置會被永久記在伺服器日誌裡。
        raise HTTPException(
            422,
            "請改用 X-Map-Position 標頭傳送座標（格式：緯度,經度,誤差公尺），不要放在網址上。"
        )
    user_coord, user_accuracy = _user_position(lat, lon, accuracy)

    # 🔴 `MP8`：回應快取。鍵＝「要了哪些來源 × **這個人看得到哪些**」——權限算進鍵裡，
    #    A 看得到的點不會回給 B（A 裁示）。與使用者位置有關的欄位不進快取，每次另算。
    visible = tuple(sorted(
        n for n in set(wanted)
        if (n == "tenders" and _may_see_tenders(user))
        or (n == "cases" and _may_see_cases(user))
        or (n in _DATASETS and _may_see_dataset(user, n))))
    # 🔴 `MP6`：案件是**逐筆**可見（自己名下／被分配）——同樣模組的兩個業務看到的點不同
    #    ⇒ 非管理員要到案件時，把「是誰」算進鍵；否則 A 的案件會從快取回給 B。
    who = (user.get("id") if ("cases" in visible
                             and user.get("role") not in ("superadmin", "admin")) else None)
    # ⚠️ 地理查詢開關也算進鍵：關著時算出來的「沒有點」不可以在打開之後繼續被回
    #    （G7 抓到的——第一版的鍵沒有它，開關切換後 60 秒內回的都是舊結果）。
    key = (tuple(sorted(set(wanted))), visible, bool(geo.geo_on()), who)
    fp = _data_fingerprint()
    now = time.monotonic()
    with _RESP_LOCK:
        hit = _RESP_CACHE.get(key)
        base = hit["body"] if (hit and hit["fp"] == fp
                               and now - hit["at"] < MAP_RESPONSE_TTL_SECONDS) else None
    response.headers["X-Map-Cache"] = "hit" if base is not None else "miss"
    if base is None:
        base = _build_points(user, wanted)
        with _RESP_LOCK:
            _RESP_CACHE[key] = {"at": now, "fp": fp, "body": base}
    out = copy.deepcopy(base)
    for pt in out["points"]:
        pt["distanceFromUserKm"] = (
            round(geo.haversine_km(user_coord, (pt["lat"], pt["lon"])), 1)
            if user_coord else None)
    out.update({
        "geoEnabled": geo.geo_on(),
        "quota": geo.quota_status(),
        "userAccuracyM": user_accuracy,
        "tilesBlocked": geo.tiles_blocked(),
        "geocodeWarm": geo.warm_status(),
    })
    return out


#: `MP8`：回應快取的有效秒數（資料一變就失效，這是保底）。
MAP_RESPONSE_TTL_SECONDS = 60
_RESP_CACHE = {}
_RESP_LOCK = threading.Lock()


def _data_fingerprint():
    """`MP8`：地圖資料的指紋——任何一個來源表、定位快取或公司據點變了，指紋就變 ⇒ 快取失效。

    📌 讀整張來源表算雜湊（每表一條 SQL）：比「每個地址查一次快取」便宜得多，
       而不必在每一個寫入點掛失效掛鉤（會漏）。
    """
    h = hashlib.sha256()
    with db_conn() as conn:
        tables = ["tenders"] + sorted({spec["table"] for spec in _DATASETS.values()})
        for t in tables:
            try:
                for row in conn.execute("SELECT * FROM %s ORDER BY rowid" % t):
                    h.update(repr(tuple(row)).encode("utf-8", "replace"))
            except Exception:                                   # noqa: BLE001
                h.update(("missing:" + t).encode())
        # `MP6`：案件只取會影響地圖的欄位（整張 data_json 太大）；可見性欄位也在內（分配變了要失效）。
        #   ⚠️ 只改 data_json 而沒動 updated_at 的寫入點，最多晚 60 秒（TTL）反映。
        for row in conn.execute("SELECT quote_no, updated_at, deal_tag, customer_name, project_name, "
                                "sales_person_id, sales_person, assigned_user_ids "
                                "FROM quotations ORDER BY id"):
            h.update(repr(tuple(row)).encode("utf-8", "replace"))
        row = conn.execute("SELECT COUNT(*), MAX(id), MAX(created_at) FROM geocode_cache").fetchone()
        h.update(repr(tuple(row)).encode())
    h.update(json.dumps(_company_profile(), sort_keys=True, ensure_ascii=False,
                        default=str).encode("utf-8"))
    return h.hexdigest()


def _build_points(user, wanted):
    """`MP8`：不含使用者位置的那一部分（進快取的就是這一份）。"""
    profile = _company_profile()
    office_address = (profile.get("address") or "").strip()
    api_key = (profile.get("google_maps_api_key") or "").strip()

    # 🔴 走 `locate_cached()` 不是舊的 `geocode_cached()`。
    # 舊的只有 Nominatim 一階，查不到就整個回報定位不到——
    # ☠️ **§3o 的 25 題全綠而這裡沒換的話，使用者看到的仍然是舊行為**，
    # 而每一題都是對的。斷點在兩個後端函式之間，**沒有人會去點那裡。**
    located, unlocated = _locate_locations(profile)
    # `office` 保留給既有的讀取者（前端的辦公室標記與 `officeMissing`）——
    # **它是「主要據點」（`locations[0]`）**，不是「最近的那一個」。
    # 🔑 兩者是不同的問題：主要據點決定舊欄位與抬頭，最近據點決定距離。
    office = dict(located[0]) if located else None

    points, without_location, source_info = [], 0, []
    # 🔴 **整個請求共用一份預算**，不是每個來源各給一份。
    # 每個來源各給的話，六個來源 × 6 秒 = 36 秒，而使用者等的是**一次請求**。
    budget = _GeocodeBudget()
    # ⚠️ **只回報「被要求的」來源**：使用者沒問的東西出現在回報裡，
    # 會讓他以為那個來源是開著的。
    if "tenders" in wanted:
        if not _may_see_tenders(user):
            # 🔴 **說出來，不要只是少一層點。**
            source_info.append({"source": "tenders", "skipped": "no_permission",
                                "count": 0,
                                "note": "沒有標案雷達模組權限，地圖上不會顯示標案"})
        else:
            pts, missing = _tender_points(located, None, budget)
            for pt in pts:
                pt["sourceKey"] = "tenders"
            points += pts
            without_location += missing
            source_info.append({
                "source": "tenders", "skipped": None,
                "count": len(pts), "withoutLocation": missing,
                "note": (f"{len(pts)} 筆標案畫在地圖上"
                         + (f"，另有 {missing} 筆沒有地點資訊" if missing else "")),
            })

    # 🔴 **被要求了就要回報，即使我們刻意不支援它。**
    # 沉默的話畫面上就是一張沒有點的地圖，而「沒有權限」「沒有資料」
    # 「我們沒做」三件事長得一模一樣。
    # ⚠️ 而它**連查都不查**：實測 0 筆，不為一張空表寫實作——
    # 那份程式碼沒有任何東西會驗它，**而它會一直看起來像「已經支援了」**。
    for name in _NOT_QUERIED:
        if name in wanted:
            source_info.append({
                "source": name, "skipped": "not_supported", "count": 0,
                "note": _NOT_QUERIED[name],
            })

    if "cases" in wanted:
        if not _may_see_cases(user):
            source_info.append({"source": "cases", "skipped": "no_permission", "count": 0,
                                "note": f"沒有「{CASE_LABEL}」的權限，地圖上不會顯示這一類"})
        else:
            pts, missing = _case_points(user, located, budget)
            for pt in pts:
                pt["sourceKey"] = "cases"
            points += pts
            without_location += missing
            source_info.append({
                "source": "cases", "skipped": None,
                "count": len(pts), "withoutLocation": missing,
                "note": (f"{CASE_LABEL} {len(pts)} 筆畫在地圖上"
                         + (f"，另有 {missing} 筆定位不到" if missing else "")),
            })

    for name in _DATASETS:
        if name not in wanted:
            continue
        spec = _DATASETS[name]
        if not _may_see_dataset(user, name):
            source_info.append({
                "source": name, "skipped": "no_permission", "count": 0,
                "note": f"沒有「{spec['label']}」的權限，地圖上不會顯示這一類",
            })
            continue
        pts, missing = _own_points(name, located, None, budget)
        for pt in pts:
            pt["sourceKey"] = name
        points += pts
        without_location += missing
        source_info.append({
            "source": name, "skipped": None,
            "count": len(pts), "withoutLocation": missing,
            "note": (f"{spec['label']} {len(pts)} 筆畫在地圖上"
                     + (f"，另有 {missing} 筆定位不到" if missing else "")),
        })

    return {
        "office": office,
        "officeMissing": not office_address,
        # 🔴 每個據點都要畫得出來（BR10），而**定位不到的要被看見**（BR7）。
        "locations": located,
        # ⚠️ 不是只給數量 —— **要指得出是哪幾筆**：
        # 一個「2 個據點定位不到」的數字，使用者無從知道該去修哪一個地址。
        "locationsUnlocated": unlocated,
        "points": points,
        "withoutLocation": without_location,
        "googleMapsConfigured": bool(api_key),
        # ⚠️ 地理查詢關著時，**已填的地址也定位不到** ⇒ 距離全是 null。
        # 不講的話使用者會以為地址填錯了。
        "geoEnabled": geo.geo_on(),
        # 🔴 GB9：**降級必須看得見。**
        # 📌 〈降級之後它還是會動〉：壞掉會被報修，降級不會。
        # ☠️ 少了這一個欄位，使用者會把「地圖變不準了」當成 bug 報上來，
        #    **而沒有人查得出來** —— 金鑰正常、設定正常、程式沒有例外。
        # 🔑 這裡回的是**狀態**不是文案：畫面決定怎麼說，後端只負責說得出來。
        "quota": geo.quota_status(),
        # `MP8`：userAccuracyM／geoEnabled／quota／tilesBlocked／geocodeWarm 與位置、時間有關，
        # 由 `map_points()` 每次另算（見那裡的 `out.update`），不進快取。
        # 🔴 第七個訊號，而它跟前六個不同級：前六個是「沒有東西」，
        # 這個是「**有東西而且是錯的**」——OSM 封鎖的回應是 HTTP 200 ＋
        # 一張寫著 Access blocked 的圖 ⇒ 瀏覽器不觸發 error、JS 讀不到標頭
        # ⇒ **前端沒有任何辦法自己發現。** 只有後端讀得到那個標頭。
        # ⚠️ 三態：True 被擋／False 探過可以用／**None 不知道**。
        "tilesBlocked": geo.tiles_blocked(),
        # 🔴 第八個訊號：**「這次來不及查」的筆數。**
        # ⚠️ 它與 `withoutLocation` 是兩件事，而處置相反：
        #   `withoutLocation` ＝ 查過了、查不到 ⇒ **去改地址**
        #   `pendingGeocode`  ＝ 還沒查 ⇒ **再按一次就好**
        # ☠️ 合併的話，使用者會去翻資料找一個不存在的錯。
        # 📌 快取是永久的 ⇒ 這個數字**只會往下掉**，按幾次就歸零。
        "pendingGeocode": budget.pending,
        # 🔴 GC8：**查過查不到**的筆數，與「這次來不及」分開回。
        # ☠️ 合在一起的話，畫面會永遠說「這次來不及」，而那句話會變成
        #    一個**永久的謊** —— 再按幾次都不會變少。
        "unresolvableGeocode": budget.unresolvable,
        # 🔴 背景暖快取的狀態。**「沒有在跑」與「跑了什麼都沒做」
        # 在畫面上一模一樣**，所以它要跟著這個回應出來。
        # 📌 `stoppedBecause` 的三種停法處置完全不同：
        #   `geo_off`（去打開）／`daily_limit`（明天會繼續）／
        #   `failures`（**對方可能拒絕我們了，要看 log**）
        "geocodeWarm": geo.warm_status(),
        "sources": source_info,
    }


def _profile_locations(profile):
    """據點清單。**讀取時做與設定頁同一套遷移**（既有安裝只有 `address`）。

    ⚠️ 兩邊各寫一份遷移邏輯的話，設定頁看得到一筆據點而地圖看不到 ——
    🔑 而那種不一致**沒有任何錯誤訊息**。
    📌 所以這裡直接呼叫 `routers.system` 那一支。
    """
    from routers.system import _migrated_locations
    return _migrated_locations(profile) or []


def _locate_locations(profile):
    """把每個據點定位。回 `(定位得到的, 定位不到的)`。

    ## 🔴🔴 定位不到的**要被看見**，不可以安靜地排除（BR7）
    ☠️ 台北分公司定位失敗 ⇒ 台北的案子**全部算成「離梧棲 150 km」**
    ⇒ 🔑 **每個數字都是對的，而整張表在回答一個沒有人問的問題。**
    📌〈答案沒錯，是題目問錯了〉。

    ⚠️ 而「數量」不夠，**要指得出是哪幾筆** ——
    一個「2 個據點定位不到」的數字，使用者無從知道該去修哪一個地址。
    """
    located, unlocated = [], []
    # 🔴 GC7：預算保護在 `geo._locate_locations()` 裡 ——
    # 🔑 **判準只有一份**：這裡再寫一次「算不算已知」的話，兩份會分岔，
    #    而分岔之後「畫面說的」與「實際查的」就不是同一件事。
    # `MP8`：開地圖不對外查——據點沒查過的交給背景（預算 0 ＝ 只讀快取）。
    resolved = geo._locate_locations(_profile_locations(profile), budget=0)
    for loc in _profile_locations(profile):
        address = str(loc.get("address") or "").strip()
        found = resolved.get(loc.get("id"))
        if found and found.coord:
            located.append({
                "id": loc.get("id"), "name": loc.get("name") or "",
                "address": address,
                "lat": found.coord[0], "lon": found.coord[1],
                "precision": found.precision, "source": found.source,
            })
        else:
            unlocated.append({"id": loc.get("id"),
                              "name": loc.get("name") or "",
                              "address": address})
    return located, unlocated


def _nearest_location(coord, located):
    """離 `coord` 最近的據點。回 `(公里數, 名稱)`，沒有可用據點就 `(None, None)`。

    ## 🔴 只從「定位得到的」裡挑，而挑不到時是 `None` 不是 `0`
    ☠️ 回 `0` 的話畫面顯示「離公司 0 km」，**看起來像「就在公司」** ——
    而使用者會照著那個數字排行程。📌〈null 不等於 0〉。

    ## ⚠️ 是「最近」不是「第一個」
    ☠️ 回 `locations[0]` 的實作在**只有一個據點**時看不出差別 ——
    🔑 而那正是既有使用者的狀態，所以它會一路綠到有人開了分公司。
    """
    best = None
    for loc in located or []:
        km = round(geo.haversine_km((loc["lat"], loc["lon"]), coord), 1)
        if best is None or km < best[0]:
            best = (km, loc.get("name") or "")
    return best if best else (None, None)


#: 一次 `/api/map/points` 最多花多少**秒**在「還沒查過的地址」上。
#:
#: ## 🔴 為什麼需要預算
#: ⚠️ 實測（正式機 `motrix_erp.db`，2026-09-22）：
#:
#: ```
#: 相異查詢字串 199（tenders.org 158 ＋ suppliers 23 ＋ customers 10 ＋ 其餘 10）
#: geocode_cache 現有 5 筆、google_maps_api_key 空 ⇒ 全部走 Nominatim
#: 而 `_throttle()` 是每秒最多一次 ⇒ 冷快取要 199 秒 = 3.3 分鐘
#: ```
#:
#: ☠️ 而那是**一個同步的 HTTP 請求** ⇒ 瀏覽器先逾時，
#: 使用者看到的不是「慢」，是「**地圖資料載入失敗：連線不到伺服器**」。
#: 🔑 這是 R1 改出來的：改之前 `location` 全 NULL ⇒ 標案那一段
#: **一次查詢都不發**。我把「0 個點」修好了，同時把 0 次查詢變成 158 次，
#: **而那一面我原本沒有量。**
#:
#: ## 📌 用時間不是用次數
#: 測試把 `geo.locate_cached` 換成查表（瞬間回）⇒ **時間預算在測試裡
#: 永遠不會觸發**，不會改到任何一題的行為。
#: 次數預算會，而那會讓一堆題目在「剛好超過 N 筆」時開始紅。
GEOCODE_TIME_BUDGET_SECONDS = 6.0


class _GeocodeBudget:
    """這次請求還能花多少時間去查沒查過的地址。

    ⚠️ **超過預算不是「安靜地少幾個點」** —— 那又是一個「空地圖」的成因，
    而今天已經有五個成因長成同一個樣子了。
    ⇒ 查不完的筆數回到 `pendingGeocode`，畫面上要說出來。

    📌 快取是**永久的**（`geocode_cache` 表，migration v89）
    ⇒ 每一次請求都讓進度往前，按幾次「繼續定位」之後就不用再按了。
    """

    def __init__(self, seconds=None):
        self.deadline = time.monotonic() + (
            GEOCODE_TIME_BUDGET_SECONDS if seconds is None else seconds)
        self.pending = 0
        # 🔴 GC8 的那一半：**查過、查不到**的筆數。
        # ☠️ 它先前被算進 `pending`，於是畫面說「這次來不及」——
        #    而使用者再按幾次也不會變少（實測：60 → 103，方向是反的）。
        # 🔑 兩者的處置相反：一個是**等**，一個是**要去改地址**。
        self.unresolvable = 0

    def locate(self, address):
        """回 `GeoResult` 或 `None`。

        🔴 **`None` 只有一個意思：這次來不及查（時間預算用完）。**
        查過而查不到 ⇒ 回一個**沒有座標的 `GeoResult`**，不是 `None`。

        ☠️ 我第一版讓兩種都回 `None`，而 `_locate_tender()` 把 `None`
        一律當成「來不及」⇒ **`withoutLocation` 變成 0**
        ⇒ **定位不到的標案從計數裡消失，而畫面說一切正常**
        （`test_m6`／`test_r2` 當場紅，它們守的正是這件事）。
        🔑 兩個計數器答得了「這一輪各有幾筆」，**答不了「這一筆是哪一種」**——
        而呼叫端要的是後者。
        📌 〈缺欄位≠缺訊號〉的反面：訊號在計數器裡，**而消費端拿不到**。
        """
        hit = geo.cached_only(address)
        if hit is not None:
            return hit          # 已經知道的一律免費
        if geo.geocode_missed_recently(address):
            # 📌 不佔時間預算：它根本不會發出請求。
            self.unresolvable += 1
            return geo.GeoResult(error="查無此地址", address=address)
        # 🔴 `MP8`（使用者：「地圖模組每次使用者都要載入一次，讓流量很快卡死」）：
        #    **開地圖的請求路徑不對外查定位**——沒查過的一律交給背景預熱，這一輪算「待定位」。
        #    ☠️ 原本這裡在時間預算內同步呼叫 `geo.locate_cached()`：每個人每次開圖
        #       都可能對外連線，而且把請求拖到 6 秒。
        self.pending += 1
        return None


def _distances(coord, located, user_coord):
    """一個點到「**最近據點**」與到「使用者」的距離。**兩個各自獨立。**

    ## 🔑 A 的裁決：「離公司多遠」背後真正要回答的是
    **「這個案子該由哪個據點去」** ⇒ 所以要多回一欄說是**哪一個**據點。
    📌 只有一個據點時**行為與改版前完全相同**（最近的就是它）⇒ 向下相容。

    ⚠️ 算不出來時是 `None` **不是 `0`**：
    0 公里的意思是「就在這裡」，那跟「不知道」是兩件事，
    **而它們在畫面上都是一個數字。**
    """
    km, name = _nearest_location(coord, located)
    return {
        "distanceFromOfficeKm": km,
        # ⚠️ 沒有可用據點時**名稱也要是 `None`** ——
        # 一個「離 12 km」而說不出離什麼的數字，比沒有數字更糟。
        "nearestLocationName": name,
        "distanceFromUserKm": (
            round(geo.haversine_km(user_coord, coord), 1)
            if user_coord else None),
    }


def _company_profile():
    from helpers.settings import _get_setting
    return {**(_get_setting("company_profile", {}) or {})}


def _locate_tender(org, place, budget):
    """一筆標案的定位：**機關名稱 → `location` → 失敗**。回 `(GeoResult, 查的字串)`。

    ## 🔴 為什麼順序是這樣
    ⚠️ 實測（正式機 `motrix_erp.db`）：

    ```
    tenders.location   200 筆   filled = 0     相異值只有 [None]
    tenders.org        200 筆   filled = 200
    ```

    ☠️ 只讀 `location` 的話**地圖上一個標案點都沒有**，
    而畫面不會說原因——使用者看到的是一張只有自己廠商的地圖。
    📌 `withoutLocation` 那個數字**是對的，只是沒有人會去看它**。

    而即使兩個都有值，機關名稱也該排前面：它命中的是**建物級**座標，
    `location` 只有縣市級。

    ## ⚠️ 被截斷的名稱不查
    🔑 **查不到會退階（安全），查到錯的不會。**
    「交通部民用航空局飛航」如果剛好命中某個不相關的地點，
    我們會得到一個看起來合理而完全錯誤的座標，
    而地圖上那個圖釘**看起來跟正確的一模一樣**。
    """
    org = (org or "").strip()
    place = (place or "").strip()
    deferred = False
    if org and not geo.looks_truncated(org):
        found = budget.locate(org)
        if found is None:
            deferred = True
        elif found.coord:
            return found, org, False
    if place:
        found = budget.locate(place)
        if found is None:
            deferred = True
        elif found.coord:
            return found, place, False
    # 🔴 第三個回傳值分辨「**查不到**」與「**這次來不及查**」。
    # ⚠️ 合併的話，「還沒查」會被算進 `withoutLocation`，
    # 而那個數字的意思是「這筆標案沒有地點資訊」——**使用者會去找資料的錯**。
    return None, None, deferred


#: `MP3`：「即將截止」的天數（含當天）。
CLOSING_SOON_DAYS = 7


def _today():
    """獨立成函式：測試可以換掉「今天」，不必跟著真實日期改資料。"""
    return datetime.date.today()


def _deadline_status(deadline, today):
    """`MP3`：標案截止狀態。

    | 值 | 意思 |
    |---|---|
    | `closed`  | 截止日 < 今天（截止日當天仍可投標） |
    | `closing` | 今天 ≤ 截止日 ≤ 今天＋7 |
    | `open`    | 截止日 > 今天＋7 |
    | `unknown` | 沒有截止日或讀不懂 |

    ⚠️ `unknown` 不可以併進 `closed`：前端預設只看「未截止」，併進去的話
    讀不懂日期的那幾筆會**靜靜從地圖上消失**，而它們可能正是還能投的。
    """
    try:
        d = datetime.date.fromisoformat(str(deadline or "").strip()[:10])
    except ValueError:
        return "unknown"
    if d < today:
        return "closed"
    if (d - today).days <= CLOSING_SOON_DAYS:
        return "closing"
    return "open"


def _tender_points(located, user_coord=None, budget=None):
    """標案來源。回 `(points, 沒有地點的筆數)`。

    ⚠️ **雷達關著時這裡照常跑**：它讀的是資料庫裡已經抓回來的標案，
    **不對外連線**。開關管的是「要不要去抓」，不是「能不能看已經抓到的」。
    """
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT case_no, name, org, location, budget, deadline, url "
            "FROM tenders ORDER BY id DESC").fetchall()

    budget = budget or _GeocodeBudget()
    points, missing = [], 0
    today = _today()
    for r in rows:
        place = (r["location"] or "").strip()
        found, used, deferred = _locate_tender(r["org"], place, budget)
        if found is None and deferred:
            continue
        if found is None:
            # ⚠️ 一筆定位失敗不可以拖垮其他筆，而它要歸到「沒有地點」那一欄
            # ——使用者至少看得到它存在，而不是它不存在。
            missing += 1
            continue
        coord = found.coord
        points.append({
            # 🔴 `dataset`（這個點屬於哪一份資料）與 `source`（誰把地址變成座標）
            # 是**兩件事**，而它們一度搶同一個鍵名：
            #   {"source": "tenders", ..., "source": found.source}
            # Python 的字典字面值**後面的鍵覆蓋前面的** ⇒ 每個點都說自己是
            # `nominatim`，而**那時看不出來**，因為地圖上只有一種資料集。
            # ☠️ 一加上廠商就會爆：前端沒有任何辦法把兩者分開上色。
            # 🔑 兩個不同的意思搶同一個名字，而**兩個值都合法** ⇒ 不會有人報錯。
            "dataset": "tenders",
            "caseNo": r["case_no"], "name": r["name"], "org": r["org"],
            "location": place, "lat": coord[0], "lon": coord[1],
            # 📌 `address` ＝ **實際被拿去查的那個字串**，
            # 所以退階走到哪一階從回傳上讀得出來，不必去猜內部呼叫了什麼。
            "address": used,
            "precision": found.precision, "source": found.source,
            "budget": r["budget"], "deadline": r["deadline"],
            "deadlineStatus": _deadline_status(r["deadline"], today),
            # 空網址回 `None` **不是 `""`**——理由與 `tender_radar._clean_url`
            # 相同（`href=""` 是一個看起來可以點、點了沒反應的東西）。
            # 📌 刻意**不跨 router 匯入**那個函式：L2 功能模組彼此不可依賴。
            "url": (str(r["url"] or "").strip() or None),
            **_distances(coord, located, user_coord),
        })
    return points, missing


__all__ = ["router", "MAP_MODULE_KEY"]
