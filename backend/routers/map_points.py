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
import json
import logging

from fastapi import APIRouter, Header, HTTPException

from db import db_conn
from helpers import _require_user
from helpers import geo
from helpers import tender_source

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


def _own_points(name, office, user_coord=None):
    """把一份自有資料的地址畫成點。回 `(points, 沒有地址或定位不到的筆數)`。"""
    spec = _DATASETS[name]
    if spec.get("json"):
        return _json_points(name, office, user_coord)
    col = spec["address"]
    # ⚠️ **`with get_db()` 是錯的**：sqlite 連線的 `with` 管的是**交易**，
    # 不是關閉 ⇒ 那個連線永遠不會關。要走 `db_conn()`。
    # 📌 而它同時解掉另一件：`db_conn()` 在呼叫當下才從 `db` 取 `get_db`，
    # 所以測試把間諜裝在 `db.get_db` 上看得到；
    # `from db import get_db` 拿的是副本，**間諜裝了也打不到**。
    name_col = "customer_name" if spec["table"] == "shipping_notes" else "name"
    with db_conn() as conn:
        rows = conn.execute(
            f"SELECT id, {name_col} AS name, {col} AS addr FROM {spec['table']} "
            f"WHERE {col} IS NOT NULL AND TRIM({col}) <> ''"
        ).fetchall()

    points, missing = [], 0
    for r in rows:
        found = geo.locate_cached(r["addr"])
        if not found.coord:
            missing += 1
            continue
        points.append({
            "dataset": name,
            "name": r["name"], "address": r["addr"],
            "lat": found.coord[0], "lon": found.coord[1],
            "precision": found.precision, "source": found.source,
            **_distances(found.coord, office, user_coord),
        })
    return points, missing


def _json_points(name, office, user_coord=None):
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

        seen, made = set(), 0
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
            found = geo.locate_cached(addr)
            if not found.coord:
                continue
            made += 1
            points.append({
                "dataset": dataset, "datasetLabel": label,
                "name": r["name"], "address": addr,
                "lat": found.coord[0], "lon": found.coord[1],
                "precision": found.precision, "source": found.source,
                **_distances(found.coord, office, user_coord),
            })
        if not made:
            missing += 1
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
def map_points(sources: str = "tenders",
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
        raise HTTPException(
            422,
            "座標不可以放在網址上：uvicorn 的 access log 會把整串 query string "
            "寫進 logs/server.log（一個永久追加的檔案）。"
            "請改用 `X-Map-Position: <lat>,<lon>,<accuracy>` header。"
        )
    user_coord, user_accuracy = _user_position(lat, lon, accuracy)

    profile = _company_profile()
    office_address = (profile.get("address") or "").strip()
    api_key = (profile.get("google_maps_api_key") or "").strip()

    # 🔴 走 `locate_cached()` 不是舊的 `geocode_cached()`。
    # 舊的只有 Nominatim 一階，查不到就整個回報定位不到——
    # ☠️ **§3o 的 25 題全綠而這裡沒換的話，使用者看到的仍然是舊行為**，
    # 而每一題都是對的。斷點在兩個後端函式之間，**沒有人會去點那裡。**
    office = None
    manual = _manual_coord(profile)
    if office_address or manual:
        found = geo.locate_cached(office_address, manual_coord=manual)
        if found.coord:
            office = {"address": office_address,
                      "lat": found.coord[0], "lon": found.coord[1],
                      # 精度要帶到畫面上：門牌與行政區在地圖上都是一個圖釘，
                      # 而距離可能差好幾公里。
                      "precision": found.precision, "source": found.source}

    points, without_location, source_info = [], 0, []
    # ⚠️ **只回報「被要求的」來源**：使用者沒問的東西出現在回報裡，
    # 會讓他以為那個來源是開著的。
    if "tenders" in wanted:
        if not _may_see_tenders(user):
            # 🔴 **說出來，不要只是少一層點。**
            source_info.append({"source": "tenders", "skipped": "no_permission",
                                "count": 0,
                                "note": "沒有標案雷達模組權限，地圖上不會顯示標案"})
        else:
            pts, missing = _tender_points(office, user_coord)
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
        pts, missing = _own_points(name, office, user_coord)
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
        "points": points,
        "withoutLocation": without_location,
        "googleMapsConfigured": bool(api_key),
        # ⚠️ 地理查詢關著時，**已填的地址也定位不到** ⇒ 距離全是 null。
        # 不講的話使用者會以為地址填錯了。
        "geoEnabled": geo.geo_on(),
        # ⚠️ 沒有定位時是 `None` 不是 `0`——0 公尺是「完美精準」。
        "userAccuracyM": user_accuracy,
        # 🔴 第七個訊號，而它跟前六個不同級：前六個是「沒有東西」，
        # 這個是「**有東西而且是錯的**」——OSM 封鎖的回應是 HTTP 200 ＋
        # 一張寫著 Access blocked 的圖 ⇒ 瀏覽器不觸發 error、JS 讀不到標頭
        # ⇒ **前端沒有任何辦法自己發現。** 只有後端讀得到那個標頭。
        # ⚠️ 三態：True 被擋／False 探過可以用／**None 不知道**。
        "tilesBlocked": geo.tiles_blocked(),
        "sources": source_info,
    }


def _manual_coord(profile):
    """人工填的辦公室座標。兩個都要有才算數。

    ⚠️ **只填一個 ⇒ 當成沒填。** 一個只有緯度的座標不是「一半的位置」，
    它是一個在赤道或本初子午線上的錯誤位置——而那會畫在地圖上，看起來很正常。
    """
    lat, lon = profile.get("office_lat"), profile.get("office_lon")
    if lat is None or lon is None:
        return None
    try:
        return (float(lat), float(lon))
    except (TypeError, ValueError):
        return None


def _distances(coord, office, user_coord):
    """一個點到「辦公室」與到「使用者」的距離。**兩個各自獨立。**

    ⚠️ 算不出來時是 `None` **不是 `0`**：
    0 公里的意思是「就在這裡」，那跟「不知道」是兩件事，
    **而它們在畫面上都是一個數字。**
    """
    return {
        "distanceFromOfficeKm": (
            round(geo.haversine_km((office["lat"], office["lon"]), coord), 1)
            if office else None),
        "distanceFromUserKm": (
            round(geo.haversine_km(user_coord, coord), 1)
            if user_coord else None),
    }


def _company_profile():
    from helpers.settings import _get_setting
    return {**(_get_setting("company_profile", {}) or {})}


def _locate_tender(org, place):
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
    if org and not geo.looks_truncated(org):
        found = geo.locate_cached(org)
        if found.coord:
            return found, org
    if place:
        found = geo.locate_cached(place)
        if found.coord:
            return found, place
    return None, None


def _tender_points(office, user_coord=None):
    """標案來源。回 `(points, 沒有地點的筆數)`。

    ⚠️ **雷達關著時這裡照常跑**：它讀的是資料庫裡已經抓回來的標案，
    **不對外連線**。開關管的是「要不要去抓」，不是「能不能看已經抓到的」。
    """
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT case_no, name, org, location, budget, deadline, url "
            "FROM tenders ORDER BY id DESC").fetchall()

    points, missing = [], 0
    for r in rows:
        place = (r["location"] or "").strip()
        found, used = _locate_tender(r["org"], place)
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
            "budget": r["budget"], "deadline": r["deadline"], "url": r["url"],
            **_distances(coord, office, user_coord),
        })
    return points, missing


__all__ = ["router", "MAP_MODULE_KEY"]
