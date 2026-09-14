"""One-off patch: 補齊交換器選型導覽缺漏品牌（Omada/Netgear/Aruba/D-Link/Peplink）。

背景：switch_guide_seed.py 原始資料只有 6 筆產品，Omada/Netgear/Aruba/D-Link/Peplink
每個品牌的 L2/L3/PoE/網管/非網管/核心交換機型號都不完整。本檔案補上已網路查證過的
真實型號（2026-08-10 查證，逐筆附官方來源 URL），只收錄可信度高的型號，
本地 AI 初稿中查無實據的型號（Netgear XSM2516T/XSM2528T、D-Link DSC-1230/1380/1480）
已剔除不收錄。

用法：在 backend 目錄下執行一次 `python switch_guide_patch_2026-08.py`。
本腳本直接寫 motrix_erp.db（非 demo db），跑過一次後不要重複執行（已用
brand+model 查重跳過），也不要回頭改 switch_guide_seed.py 本身。
"""
import json

from db import get_db

# [category_code, brand, model, url, label, price_note]
NEW_PRODUCTS = [
    # ---- 非網管 UNMANAGED ----
    ["UNMANAGED", "Netgear", "GS748PP", "https://www.netgear.com/business/wired/switches/",
     "Netgear GS748PP 官網系列頁（48埠／PoE+非網管）", "US$749.99（2026-08 官網查價）"],
    ["UNMANAGED", "Netgear", "GS105PP", "https://www.netgear.com/business/wired/switches/",
     "Netgear GS105PP 官網系列頁（5埠／PoE+非網管）", "US$114.99（2026-08 官網查價）"],
    ["UNMANAGED", "D-Link", "DES-1024A", "https://www.dlink.com/en/products/des-1024a-24-port-fast-ethernet-unmanaged-switch",
     "D-Link DES-1024A 原廠頁（24埠 Fast Ethernet 100M，非Gigabit，勿標錯速率）", "洽詢經銷商（2026-08 查證未列牌價）"],
    ["UNMANAGED", "D-Link", "DES-1016D", "https://www.dlink.com/en/products/des-1016d-16-port-fast-ethernet-unmanaged-switch",
     "D-Link DES-1016D 原廠頁（16埠 Fast Ethernet 100M，非Gigabit）", "洽詢經銷商（2026-08 查證未列牌價）"],
    ["UNMANAGED", "Aruba", "Instant On 1430 8G PoE (R8R46A)", "https://www.arubainstanton.com/products/switches/1430-series/",
     "Aruba Instant On 1430 系列原廠頁（8埠／Class4 PoE非網管）", "US$100~150（2026-08 查價，第三方通路約略區間）"],

    # ---- 簡易網管 / L2+ SMART_L2PLUS ----
    ["SMART_L2PLUS", "Netgear", "GS324TPv2", "https://www.netgear.com/business/wired/switches/",
     "Netgear GS324TPv2 官網系列頁（24埠 PoE+／2 SFP，Smart Managed）", "US$249.99（2026-08 官網查價）"],
    ["SMART_L2PLUS", "D-Link", "DGS-1210-26", "https://www.dlink.com/en/products/dgs-1210-26--26-port-gigabit-smart-managed-switch",
     "D-Link DGS-1210-26 原廠頁（26埠 Gigabit Smart Managed L2+）", "洽詢經銷商（2026-08 查證未列牌價）"],
    ["SMART_L2PLUS", "Aruba", "Instant On 1930 24G 4SFP+ 195W PoE (JL683A)", "https://www.arubainstanton.com/products/switches/1930-series/",
     "Aruba Instant On 1930 系列原廠頁（24埠／195W PoE／4 SFP+，L2+）", "US$400~550（2026-08 查價，第三方通路約略區間）"],
    ["SMART_L2PLUS", "TP-Link", "Omada SG3428", "https://www.omadanetworks.com/us/business-networking/all-omada-switch/",
     "TP-Link Omada Access 系列原廠頁（SG3428，24埠+4 SFP，L2+全網管）", "洽詢經銷商（2026-08 查證未列牌價）"],
    ["SMART_L2PLUS", "Peplink", "SD Switch 24-Port (PLS-24-H2G-410W)", "https://www.peplink.com/products/wifi-poe/switch-series/",
     "Peplink SD Switch 24埠原廠頁（PoE+ 410W，InControl2雲端管理L2）", "洽詢經銷商（2026-08 查證未列牌價）"],

    # ---- L3 全網管 / 核心 MANAGED_L3 ----
    ["MANAGED_L3", "Netgear", "M4300-12X12F (XSM4324S)", "https://www.netgear.com/support/product/m4300-12x12f",
     "Netgear M4300-12X12F 原廠頁（24埠10G，12x10GBASE-T+12xSFP+，L3可堆疊）", "洽詢經銷商（2026-08 查證未列牌價）"],
    ["MANAGED_L3", "Netgear", "M4500-48XF8C (XSM4556)", "https://www.netgear.com/business/wired/switches/fully-managed/m4500/",
     "Netgear M4500-48XF8C 原廠頁（48x10G/25G SFP28 + 8x100G QSFP28，Netgear最高階核心機種）", "洽詢經銷商（2026-08 查證未列牌價）"],
    ["MANAGED_L3", "D-Link", "DGS-1520-52MP", "https://shop.us.dlink.com/collections/enterprise-switches",
     "D-Link Enterprise 系列頁（DGS-1520-52MP，52埠／740W PoE，L3可堆疊，現行主力）", "洽詢經銷商（2026-08 查證未列牌價）"],
    ["MANAGED_L3", "TP-Link", "Omada S7500-24Y4C", "https://www.omadanetworks.com/us/business-networking/all-omada-switch/",
     "TP-Link Omada Campus 系列原廠頁（S7500-24Y4C，24x25G+4x100G，真正核心層，2Tbps）", "洽詢經銷商（2026-08 查證未列牌價）"],
]


def main():
    conn = get_db()
    existing = {(r["brand"], r["model"]) for r in conn.execute("SELECT brand, model FROM switch_products").fetchall()}
    max_sort = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM switch_products").fetchone()["m"]

    inserted, skipped = 0, 0
    for category_code, brand, model, url, label, price_note in NEW_PRODUCTS:
        if (brand, model) in existing:
            print(f"跳過（已存在）：{brand} {model}")
            skipped += 1
            continue
        if not conn.execute("SELECT 1 FROM switch_categories WHERE code=?", (category_code,)).fetchone():
            print(f"跳過（分類不存在 {category_code}）：{brand} {model}")
            skipped += 1
            continue
        max_sort += 1
        conn.execute(
            "INSERT INTO switch_products (category_code, brand, model, url, label, price_note, specs_json, sort_order) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (category_code, brand, model, url, label, price_note, json.dumps([], ensure_ascii=False), max_sort),
        )
        print(f"已新增：[{category_code}] {brand} {model}")
        inserted += 1

    conn.commit()
    conn.close()
    print(f"\n完成：新增 {inserted} 筆，跳過 {skipped} 筆。")


if __name__ == "__main__":
    main()
