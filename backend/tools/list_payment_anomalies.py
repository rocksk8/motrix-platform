"""列出「收款資料異常」——純唯讀，不寫入任何東西（2026-09-11 新增）。

**用途**：上線後要逐筆補的那份清單，直接在機器上跑就看得到，不必登入網頁、
也不必等報表。正式機上跑就是正式機的數字。

**背景**（詳見 `MOTRIX-ERP-QUICK.md` §5.12）：「已收款」勾選與「收款日期」是兩個
各自獨立的欄位，只填一個的話，收入報表與未收報表**兩邊都撈不到**——錢就從所有
月報表上消失，而且畫面上原本沒有任何提示。

用法：
    cd backend
    python tools/list_payment_anomalies.py                 # 讀預設 db
    python tools/list_payment_anomalies.py --db 路徑\某.db  # 讀指定副本

⚠️ 正式機上請用 `--db` 指到副本，或至少確認本程式**只做 SELECT**（它真的只做
SELECT，但在正式機養成這個習慣比較安全）。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="要讀的 sqlite 檔（預設用 db.DB_PATH）")
    args = ap.parse_args()

    import db as dbmod
    if args.db:
        dbmod.DB_PATH = args.db
    from helpers.tax_calc import payment_item_amounts

    conn = dbmod.get_db()
    try:
        rows = conn.execute("""
            SELECT quote_no, customer_name, project_name, sales_person, total, pretax,
                   json_extract(data_json,'$.caseRecord') AS cr_json
            FROM quotations
            WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '')
                  IN ('已成案','已結案')
        """).fetchall()
    finally:
        conn.close()

    items = []
    for row in rows:
        try:
            cr = json.loads(row["cr_json"] or "{}")
        except Exception:
            continue
        pay = (cr.get("payment") or {}).get("items", [])
        if not pay:
            continue
        amounts = payment_item_amounts(row["total"] or 0, pay, row["pretax"])
        for idx, pi in enumerate(pay):
            rcvd = bool(pi.get("received"))
            rat = (pi.get("receivedAt") or "")[:10]
            if rcvd and not rat:
                kind = "已勾已收款、沒填日期 → 不屬於任何月份"
            elif rat and not rcvd:
                kind = "填了日期、沒勾已收款 → 收入與未收兩邊都不算"
            else:
                continue
            aa = pi.get("actualAmount")
            items.append({
                "quoteNo": row["quote_no"],
                "customer": row["customer_name"] or "",
                "project": row["project_name"] or "",
                "type": pi.get("type", "第%d期" % (idx + 1)),
                "amount": aa if aa is not None else amounts[idx],
                "receivedAt": rat,
                "kind": kind,
            })

    items.sort(key=lambda x: -float(x["amount"] or 0))
    print("資料庫：%s" % dbmod.DB_PATH)
    print("收款資料異常：%d 筆，合計 NT$ %s\n" % (
        len(items), format(int(sum(float(i["amount"] or 0) for i in items)), ",")))
    if not items:
        print("（沒有異常，全部款項的「已收款」與「收款日期」都一致）")
        return
    print("  %-18s %-14s %-10s %14s  %s" % ("案件號", "客戶", "款項", "金額", "問題"))
    for i in items:
        print("  %-18s %-14s %-10s %14s  %s" % (
            i["quoteNo"], i["customer"][:12], i["type"][:8],
            "NT$ " + format(int(float(i["amount"] or 0)), ","), i["kind"]))
    print("\n修法：案件管理 → 該案件 → 案件資訊 → 款項明細，把缺的那一半補上"
          "（系統刻意不自動補：錢收到了沒有是人的判斷）。")


if __name__ == "__main__":
    main()
