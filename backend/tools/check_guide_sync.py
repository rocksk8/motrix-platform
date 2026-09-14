"""雙機（開發機／正式機）選型資料庫內容核對工具。

用途：撰寫新的內容同步腳本（sync_YYYY-MM-DD_xxx.py）之前，先用這支工具直接打兩台機器的
選型資料庫 CRUD API（唯讀 GET），依自然鍵比對哪些資料只有一邊有——取代目前「翻 docstring
回憶／人工核對」的做法，比對結果可以直接告訴你這次該補哪些資料，不用再靠記憶。

前置需求：兩台機器都要先跑過 create_claude_account.py（建立帳號）與同目錄上一層的
issue_claude_session.py（核發 session token）。

netarch_products 用 generation_id（機器本地自增數字，兩機不保證相同）當外鍵，比對前會
先用 (family_code, gen_name) 把 generation_id 換成穩定的自然鍵再比對；其餘類別的外鍵都
已經是 code 字串，不需要轉換。

用法：
    1. 設定 backend/tools/.guide_sync_config.json（不進 git，範例見 _CONFIG_EXAMPLE）
       或改用環境變數 GUIDE_SYNC_DEV_TOKEN / GUIDE_SYNC_PROD_TOKEN（URL 用預設值時足夠）
    2. python check_guide_sync.py                            # 核對全部類別
    3. python check_guide_sync.py --category switch access   # 只核對指定類別
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

_HERE = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_HERE, ".guide_sync_config.json")
_TIMEOUT = 10

_CONFIG_EXAMPLE = {
    "dev":  {"base_url": "http://localhost:666",     "token": "<claude 帳號在開發機的 session token>"},
    "prod": {"base_url": "http://172.16.10.177:666",  "token": "<claude 帳號在正式機的 session token>"},
}

# 類別 → [(端點簡稱, path, 自然鍵欄位 tuple；None 代表用下方特例函式比對), ...]
CATEGORIES = {
    "switch": [
        ("scenarios",  "/api/switch-guide/scenarios",  ("code",)),
        ("categories", "/api/switch-guide/categories", ("code",)),
        ("fit",        "/api/switch-guide/fit",        ("scenario_code", "category_code")),
        ("products",   "/api/switch-guide/products",   ("category_code", "brand", "model")),
    ],
    "monitor": [
        ("scenarios",  "/api/monitor-guide/scenarios",  ("code",)),
        ("categories", "/api/monitor-guide/categories", ("code",)),
        ("fit",        "/api/monitor-guide/fit",        ("scenario_code", "category_code")),
        ("products",   "/api/monitor-guide/products",   ("category_code", "brand", "model")),
    ],
    "access": [
        ("scenarios",  "/api/access-guide/scenarios",  ("code",)),
        ("categories", "/api/access-guide/categories", ("code",)),
        ("fit",        "/api/access-guide/fit",        ("scenario_code", "category_code")),
        ("products",   "/api/access-guide/products",   ("category_code", "brand", "model")),
    ],
    "gateway": [
        ("scenarios",  "/api/gateway-guide/scenarios",  ("code",)),
        ("categories", "/api/gateway-guide/categories", ("code",)),
        ("fit",        "/api/gateway-guide/fit",        ("scenario_code", "category_code")),
        ("products",   "/api/gateway-guide/products",   ("category_code", "brand", "model")),
    ],
    "netarch": [
        ("families",    "/api/netarch-guide/families",    ("code",)),
        ("generations", "/api/netarch-guide/generations", ("family_code", "gen_name")),
        ("products",    "/api/netarch-guide/products",    None),
    ],
    "env": [
        ("environments",    "/api/env-guide/environments",    ("code",)),
        ("recommendations", "/api/env-guide/recommendations", ("env_code", "layer", "position")),
        ("links",            "/api/env-guide/links",           ("keyword", "url")),
    ],
}


def _load_config():
    if os.path.exists(_CONFIG_PATH):
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        cfg = {
            "dev":  {"base_url": "http://localhost:666", "token": ""},
            "prod": {"base_url": "http://172.16.10.177:666", "token": ""},
        }
    if os.environ.get("GUIDE_SYNC_DEV_TOKEN"):
        cfg["dev"]["token"] = os.environ["GUIDE_SYNC_DEV_TOKEN"]
    if os.environ.get("GUIDE_SYNC_PROD_TOKEN"):
        cfg["prod"]["token"] = os.environ["GUIDE_SYNC_PROD_TOKEN"]
    missing = [side for side in ("dev", "prod") if not cfg.get(side, {}).get("token")]
    if missing:
        print(f"缺少 token：{missing}")
        print(f"請建立 {_CONFIG_PATH}，格式範例：")
        print(json.dumps(_CONFIG_EXAMPLE, ensure_ascii=False, indent=2))
        print("或改用環境變數 GUIDE_SYNC_DEV_TOKEN / GUIDE_SYNC_PROD_TOKEN")
        sys.exit(1)
    return cfg


def _fetch(base_url, token, path):
    req = urllib.request.Request(base_url.rstrip("/") + path, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  [錯誤] GET {path} -> HTTP {e.code}（{e.reason}）")
        return None
    except urllib.error.URLError as e:
        print(f"  [錯誤] GET {path} -> 連線失敗（{e.reason}），機器是否開機/可達？")
        return None


def _key_of(row, key_fields):
    return tuple(row.get(f) for f in key_fields)


def _diff_rows(dev_rows, prod_rows, key_fields, label):
    dev_map = {_key_of(r, key_fields): r for r in dev_rows}
    prod_map = {_key_of(r, key_fields): r for r in prod_rows}
    dev_only = [k for k in dev_map if k not in prod_map]
    prod_only = [k for k in prod_map if k not in dev_map]
    if not dev_only and not prod_only:
        print(f"  {label}: 一致（共 {len(dev_map)} 筆）")
    else:
        print(f"  {label}: 開發機 {len(dev_map)} 筆／正式機 {len(prod_map)} 筆")
        if dev_only:
            print(f"    開發機有、正式機缺少（{len(dev_only)} 筆）：{sorted(dev_only)}")
        if prod_only:
            print(f"    正式機有、開發機缺少（{len(prod_only)} 筆）：{sorted(prod_only)}")
    return dev_only, prod_only


def _diff_netarch_products(dev_data, prod_data):
    dev_gens = {g["id"]: (g["family_code"], g["gen_name"]) for g in dev_data["generations"]}
    prod_gens = {g["id"]: (g["family_code"], g["gen_name"]) for g in prod_data["generations"]}

    def _rewrite(rows, gen_map):
        out = []
        for r in rows:
            gen_key = gen_map.get(r["generation_id"])
            if gen_key is None:
                print(f"    [警告] product id={r.get('id')} brand={r.get('brand')} model={r.get('model')} "
                      f"的 generation_id={r.get('generation_id')} 找不到對應世代，略過比對")
                continue
            out.append({**r, "_family_code": gen_key[0], "_gen_name": gen_key[1]})
        return out

    dev_rows = _rewrite(dev_data["products"], dev_gens)
    prod_rows = _rewrite(prod_data["products"], prod_gens)
    return _diff_rows(dev_rows, prod_rows, ("_family_code", "_gen_name", "brand", "model"), "products")


def run(categories, cfg):
    overall_gap = False
    for cat in categories:
        endpoints = CATEGORIES[cat]
        print(f"\n=== {cat} ===")
        dev_data, prod_data, ok = {}, {}, True
        for name, path, _key in endpoints:
            dev_rows = _fetch(cfg["dev"]["base_url"], cfg["dev"]["token"], path)
            prod_rows = _fetch(cfg["prod"]["base_url"], cfg["prod"]["token"], path)
            if dev_rows is None or prod_rows is None:
                ok = False
                continue
            dev_data[name] = dev_rows
            prod_data[name] = prod_rows
        if not ok:
            print(f"  {cat} 類別部分端點抓取失敗，略過比對")
            overall_gap = True
            continue
        for name, _path, key_fields in endpoints:
            if key_fields is None:
                dev_only, prod_only = _diff_netarch_products(dev_data, prod_data)
            else:
                dev_only, prod_only = _diff_rows(dev_data[name], prod_data[name], key_fields, name)
            if dev_only or prod_only:
                overall_gap = True
    return overall_gap


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--category", nargs="+", choices=list(CATEGORIES), default=list(CATEGORIES),
                         help="只核對指定類別，預設全部")
    args = parser.parse_args()

    cfg = _load_config()
    gap = run(args.category, cfg)

    print()
    if gap:
        print("結論：兩機內容有落差，上方列出的「正式機缺少」項目需要另外寫/跑同步腳本補上。")
        sys.exit(1)
    else:
        print("結論：核對範圍內兩機內容一致。")


if __name__ == "__main__":
    main()
