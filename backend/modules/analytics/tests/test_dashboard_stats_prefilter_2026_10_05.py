# -*- coding: utf-8 -*-
"""T40：/api/dashboard/stats 的速度修整不得改變輸出（稽核 F-06）。

做法（皆不改行為）：①核准流程／精算 JSON 只對「回應會用到的列」取出（其餘列取 NULL）；②每列 caseRecord 只解析一次
（原本付款、保固、設備、應收四段各解析一次）。

兩種題：
- 特徵題：混合狀態／成交標籤／部門／角色的固定資料，輸出與修整前逐值相同（GOLDEN 是在修整前的程式上產生的）。
  保固的 `daysLeft` 隨今天變動，比對時略去（`expiryDate` 仍比）。
- 結構題：每一列的 caseRecord 在一次請求內只解析一次（修整前是 4 次 ⇒ 紅）。
"""
import json

import pytest

#: 修整前（origin/train/t39 的 dashboard.py）產生；鍵＝「使用者|部門」。見 _golden_dump()
GOLDEN = r'''
{
 "admin2|a": {
  "activeCases": 1,
  "closedCases": 2,
  "customerCount": 0,
  "deviceSummary": {
   "expired": 1,
   "none": 1,
   "ok": 1,
   "soon": 0,
   "total": 3
  },
  "marginComparison": [
   {
    "actualMarginPct": 30.0,
    "customer": "客戶12",
    "estimatedMarginPct": 26.0,
    "grossProfit": 30000,
    "label": "客戶12",
    "profitDiff": 0,
    "projectName": "專案12",
    "quoteNo": "PF-012",
    "quotedPretax": 100000
   }
  ],
  "marginTop5": [
   {
    "label": "客戶06\n專案06",
    "margin": 35.5,
    "quoteNo": "PF-006"
   },
   {
    "label": "客戶12\n專案12",
    "margin": 26.0,
    "quoteNo": "PF-012"
   },
   {
    "label": "客戶08\n專案08",
    "margin": 25.0,
    "quoteNo": "PF-008"
   },
   {
    "label": "客戶11\n專案11",
    "margin": 22.0,
    "quoteNo": "PF-011"
   },
   {
    "label": "客戶13\n專案13",
    "margin": 20.0,
    "quoteNo": "PF-013"
   }
  ],
  "paymentItems": [
   {
    "amount": 73500,
    "customer": "客戶12",
    "label": "尾款",
    "pct": 70,
    "quoteNo": "PF-012"
   },
   {
    "amount": 73500,
    "customer": "客戶11",
    "label": "尾款",
    "pct": 70,
    "quoteNo": "PF-011"
   },
   {
    "amount": 73500,
    "customer": "客戶08",
    "label": "尾款",
    "pct": 70,
    "quoteNo": "PF-008"
   }
  ],
  "pendingList": [
   {
    "customer": "客戶03",
    "quoteDate": "2026-02-03",
    "quoteNo": "PF-003",
    "reasons": [
     "毛利低"
    ],
    "requestedBy": "申請人",
    "salesPerson": "開單者",
    "total": 105000.0
   }
  ],
  "pendingQuotes": 1,
  "projectSummary": {},
  "receivableSummary": {
   "feeTotal": 0,
   "netReceived": 94500.0,
   "received": 94500,
   "total": 315000,
   "unreceived": 220500
  },
  "sentQuotes": 5,
  "settledSummary": {
   "avgActualMarginPct": 30.0,
   "count": 1,
   "totalGrossProfit": 30000,
   "totalQuotedPretax": 100000
  },
  "totalQuotes": 8,
  "waitingForMe": 1,
  "warrantyWarnings": [
   {
    "customer": "客戶08",
    "expiryDate": "2021-01-01",
    "name": "舊設備",
    "quoteNo": "PF-008",
    "sn": "S-OLD"
   }
  ]
 },
 "admin2|all": {
  "activeCases": 2,
  "closedCases": 3,
  "customerCount": 0,
  "deviceSummary": {
   "expired": 2,
   "none": 1,
   "ok": 1,
   "soon": 0,
   "total": 4
  },
  "marginComparison": [
   {
    "actualMarginPct": 30.0,
    "customer": "客戶12",
    "estimatedMarginPct": 26.0,
    "grossProfit": 30000,
    "label": "客戶12",
    "profitDiff": 0,
    "projectName": "專案12",
    "quoteNo": "PF-012",
    "quotedPretax": 100000
   },
   {
    "actualMarginPct": 28.0,
    "customer": "客戶10",
    "estimatedMarginPct": 30.0,
    "grossProfit": 28000,
    "label": "客戶10",
    "profitDiff": 500,
    "projectName": "專案10",
    "quoteNo": "PF-010",
    "quotedPretax": 100000
   }
  ],
  "marginTop5": [
   {
    "label": "客戶06\n專案06",
    "margin": 35.5,
    "quoteNo": "PF-006"
   },
   {
    "label": "客戶10\n專案10",
    "margin": 30.0,
    "quoteNo": "PF-010"
   },
   {
    "label": "客戶12\n專案12",
    "margin": 26.0,
    "quoteNo": "PF-012"
   },
   {
    "label": "客戶08\n專案08",
    "margin": 25.0,
    "quoteNo": "PF-008"
   },
   {
    "label": "客戶11\n專案11",
    "margin": 22.0,
    "quoteNo": "PF-011"
   }
  ],
  "paymentItems": [
   {
    "amount": 73500,
    "customer": "客戶12",
    "label": "尾款",
    "pct": 70,
    "quoteNo": "PF-012"
   },
   {
    "amount": 73500,
    "customer": "客戶11",
    "label": "尾款",
    "pct": 70,
    "quoteNo": "PF-011"
   },
   {
    "amount": 73500,
    "customer": "客戶10",
    "label": "尾款",
    "pct": 70,
    "quoteNo": "PF-010"
   },
   {
    "amount": 73500,
    "customer": "客戶09",
    "label": "尾款",
    "pct": 70,
    "quoteNo": "PF-009"
   },
   {
    "amount": 73500,
    "customer": "客戶08",
    "label": "尾款",
    "pct": 70,
    "quoteNo": "PF-008"
   }
  ],
  "pendingList": [
   {
    "customer": "客戶03",
    "quoteDate": "2026-02-03",
    "quoteNo": "PF-003",
    "reasons": [
     "毛利低"
    ],
    "requestedBy": "申請人",
    "salesPerson": "開單者",
    "total": 105000.0
   }
  ],
  "pendingQuotes": 1,
  "projectSummary": {},
  "receivableSummary": {
   "feeTotal": 0,
   "netReceived": 157500.0,
   "received": 157500,
   "total": 525000,
   "unreceived": 367500
  },
  "sentQuotes": 8,
  "settledSummary": {
   "avgActualMarginPct": 29.0,
   "count": 2,
   "totalGrossProfit": 58000,
   "totalQuotedPretax": 200000
  },
  "totalQuotes": 13,
  "waitingForMe": 2,
  "warrantyWarnings": [
   {
    "customer": "客戶08",
    "expiryDate": "2021-01-01",
    "name": "舊設備",
    "quoteNo": "PF-008",
    "sn": "S-OLD"
   },
   {
    "customer": "客戶02",
    "expiryDate": "2021-01-01",
    "name": "舊設備",
    "quoteNo": "PF-002",
    "sn": "S-OLD"
   }
  ]
 },
 "admin2|b": {
  "activeCases": 0,
  "closedCases": 1,
  "customerCount": 0,
  "deviceSummary": {
   "expired": 1,
   "none": 0,
   "ok": 0,
   "soon": 0,
   "total": 1
  },
  "marginComparison": [
   {
    "actualMarginPct": 28.0,
    "customer": "客戶10",
    "estimatedMarginPct": 30.0,
    "grossProfit": 28000,
    "label": "客戶10",
    "profitDiff": 500,
    "projectName": "專案10",
    "quoteNo": "PF-010",
    "quotedPretax": 100000
   }
  ],
  "marginTop5": [
   {
    "label": "客戶10\n專案10",
    "margin": 30.0,
    "quoteNo": "PF-010"
   },
   {
    "label": "客戶07\n專案07",
    "margin": 10.0,
    "quoteNo": "PF-007"
   }
  ],
  "paymentItems": [
   {
    "amount": 73500,
    "customer": "客戶10",
    "label": "尾款",
    "pct": 70,
    "quoteNo": "PF-010"
   }
  ],
  "pendingList": [],
  "pendingQuotes": 0,
  "projectSummary": {},
  "receivableSummary": {
   "feeTotal": 0,
   "netReceived": 31500.0,
   "received": 31500,
   "total": 105000,
   "unreceived": 73500
  },
  "sentQuotes": 2,
  "settledSummary": {
   "avgActualMarginPct": 28.0,
   "count": 1,
   "totalGrossProfit": 28000,
   "totalQuotedPretax": 100000
  },
  "totalQuotes": 4,
  "waitingForMe": 1,
  "warrantyWarnings": [
   {
    "customer": "客戶02",
    "expiryDate": "2021-01-01",
    "name": "舊設備",
    "quoteNo": "PF-002",
    "sn": "S-OLD"
   }
  ]
 },
 "admin|a": {
  "activeCases": 1,
  "closedCases": 2,
  "customerCount": 0,
  "deviceSummary": {
   "expired": 1,
   "none": 1,
   "ok": 1,
   "soon": 0,
   "total": 3
  },
  "marginComparison": [
   {
    "actualMarginPct": 30.0,
    "customer": "客戶12",
    "estimatedMarginPct": 26.0,
    "grossProfit": 30000,
    "label": "客戶12",
    "profitDiff": 0,
    "projectName": "專案12",
    "quoteNo": "PF-012",
    "quotedPretax": 100000
   }
  ],
  "marginTop5": [
   {
    "label": "客戶06\n專案06",
    "margin": 35.5,
    "quoteNo": "PF-006"
   },
   {
    "label": "客戶12\n專案12",
    "margin": 26.0,
    "quoteNo": "PF-012"
   },
   {
    "label": "客戶08\n專案08",
    "margin": 25.0,
    "quoteNo": "PF-008"
   },
   {
    "label": "客戶11\n專案11",
    "margin": 22.0,
    "quoteNo": "PF-011"
   },
   {
    "label": "客戶13\n專案13",
    "margin": 20.0,
    "quoteNo": "PF-013"
   }
  ],
  "paymentItems": [
   {
    "amount": 73500,
    "customer": "客戶12",
    "label": "尾款",
    "pct": 70,
    "quoteNo": "PF-012"
   },
   {
    "amount": 73500,
    "customer": "客戶11",
    "label": "尾款",
    "pct": 70,
    "quoteNo": "PF-011"
   },
   {
    "amount": 73500,
    "customer": "客戶08",
    "label": "尾款",
    "pct": 70,
    "quoteNo": "PF-008"
   }
  ],
  "pendingList": [
   {
    "customer": "客戶03",
    "quoteDate": "2026-02-03",
    "quoteNo": "PF-003",
    "reasons": [
     "毛利低"
    ],
    "requestedBy": "申請人",
    "salesPerson": "開單者",
    "total": 105000.0
   }
  ],
  "pendingQuotes": 1,
  "projectSummary": {},
  "receivableSummary": {
   "feeTotal": 0,
   "netReceived": 94500.0,
   "received": 94500,
   "total": 315000,
   "unreceived": 220500
  },
  "sentQuotes": 5,
  "settledSummary": {
   "avgActualMarginPct": 30.0,
   "count": 1,
   "totalGrossProfit": 30000,
   "totalQuotedPretax": 100000
  },
  "totalQuotes": 8,
  "waitingForMe": 0,
  "warrantyWarnings": [
   {
    "customer": "客戶08",
    "expiryDate": "2021-01-01",
    "name": "舊設備",
    "quoteNo": "PF-008",
    "sn": "S-OLD"
   }
  ]
 },
 "admin|all": {
  "activeCases": 2,
  "closedCases": 3,
  "customerCount": 0,
  "deviceSummary": {
   "expired": 2,
   "none": 1,
   "ok": 1,
   "soon": 0,
   "total": 4
  },
  "marginComparison": [
   {
    "actualMarginPct": 30.0,
    "customer": "客戶12",
    "estimatedMarginPct": 26.0,
    "grossProfit": 30000,
    "label": "客戶12",
    "profitDiff": 0,
    "projectName": "專案12",
    "quoteNo": "PF-012",
    "quotedPretax": 100000
   },
   {
    "actualMarginPct": 28.0,
    "customer": "客戶10",
    "estimatedMarginPct": 30.0,
    "grossProfit": 28000,
    "label": "客戶10",
    "profitDiff": 500,
    "projectName": "專案10",
    "quoteNo": "PF-010",
    "quotedPretax": 100000
   }
  ],
  "marginTop5": [
   {
    "label": "客戶06\n專案06",
    "margin": 35.5,
    "quoteNo": "PF-006"
   },
   {
    "label": "客戶10\n專案10",
    "margin": 30.0,
    "quoteNo": "PF-010"
   },
   {
    "label": "客戶12\n專案12",
    "margin": 26.0,
    "quoteNo": "PF-012"
   },
   {
    "label": "客戶08\n專案08",
    "margin": 25.0,
    "quoteNo": "PF-008"
   },
   {
    "label": "客戶11\n專案11",
    "margin": 22.0,
    "quoteNo": "PF-011"
   }
  ],
  "paymentItems": [
   {
    "amount": 73500,
    "customer": "客戶12",
    "label": "尾款",
    "pct": 70,
    "quoteNo": "PF-012"
   },
   {
    "amount": 73500,
    "customer": "客戶11",
    "label": "尾款",
    "pct": 70,
    "quoteNo": "PF-011"
   },
   {
    "amount": 73500,
    "customer": "客戶10",
    "label": "尾款",
    "pct": 70,
    "quoteNo": "PF-010"
   },
   {
    "amount": 73500,
    "customer": "客戶09",
    "label": "尾款",
    "pct": 70,
    "quoteNo": "PF-009"
   },
   {
    "amount": 73500,
    "customer": "客戶08",
    "label": "尾款",
    "pct": 70,
    "quoteNo": "PF-008"
   }
  ],
  "pendingList": [
   {
    "customer": "客戶03",
    "quoteDate": "2026-02-03",
    "quoteNo": "PF-003",
    "reasons": [
     "毛利低"
    ],
    "requestedBy": "申請人",
    "salesPerson": "開單者",
    "total": 105000.0
   }
  ],
  "pendingQuotes": 1,
  "projectSummary": {},
  "receivableSummary": {
   "feeTotal": 0,
   "netReceived": 157500.0,
   "received": 157500,
   "total": 525000,
   "unreceived": 367500
  },
  "sentQuotes": 8,
  "settledSummary": {
   "avgActualMarginPct": 29.0,
   "count": 2,
   "totalGrossProfit": 58000,
   "totalQuotedPretax": 200000
  },
  "totalQuotes": 13,
  "waitingForMe": 0,
  "warrantyWarnings": [
   {
    "customer": "客戶08",
    "expiryDate": "2021-01-01",
    "name": "舊設備",
    "quoteNo": "PF-008",
    "sn": "S-OLD"
   },
   {
    "customer": "客戶02",
    "expiryDate": "2021-01-01",
    "name": "舊設備",
    "quoteNo": "PF-002",
    "sn": "S-OLD"
   }
  ]
 },
 "admin|b": {
  "activeCases": 0,
  "closedCases": 1,
  "customerCount": 0,
  "deviceSummary": {
   "expired": 1,
   "none": 0,
   "ok": 0,
   "soon": 0,
   "total": 1
  },
  "marginComparison": [
   {
    "actualMarginPct": 28.0,
    "customer": "客戶10",
    "estimatedMarginPct": 30.0,
    "grossProfit": 28000,
    "label": "客戶10",
    "profitDiff": 500,
    "projectName": "專案10",
    "quoteNo": "PF-010",
    "quotedPretax": 100000
   }
  ],
  "marginTop5": [
   {
    "label": "客戶10\n專案10",
    "margin": 30.0,
    "quoteNo": "PF-010"
   },
   {
    "label": "客戶07\n專案07",
    "margin": 10.0,
    "quoteNo": "PF-007"
   }
  ],
  "paymentItems": [
   {
    "amount": 73500,
    "customer": "客戶10",
    "label": "尾款",
    "pct": 70,
    "quoteNo": "PF-010"
   }
  ],
  "pendingList": [],
  "pendingQuotes": 0,
  "projectSummary": {},
  "receivableSummary": {
   "feeTotal": 0,
   "netReceived": 31500.0,
   "received": 31500,
   "total": 105000,
   "unreceived": 73500
  },
  "sentQuotes": 2,
  "settledSummary": {
   "avgActualMarginPct": 28.0,
   "count": 1,
   "totalGrossProfit": 28000,
   "totalQuotedPretax": 100000
  },
  "totalQuotes": 4,
  "waitingForMe": 0,
  "warrantyWarnings": [
   {
    "customer": "客戶02",
    "expiryDate": "2021-01-01",
    "name": "舊設備",
    "quoteNo": "PF-002",
    "sn": "S-OLD"
   }
  ]
 }
}
'''

DEV_OLD = {"name": "舊設備", "sn": "S-OLD", "warrantyStart": "2020-01-01", "warrantyMonths": 12}      # 早已過保
DEV_FAR = {"name": "新設備", "sn": "S-FAR", "warrantyStart": "2099-01-01", "warrantyMonths": 36}      # 遠未到期
DEV_NONE = {"name": "無保固", "sn": "S-NONE"}


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _insert(quote_no, status, deal_tag, *, opener=None, sales_role=None, cr_extra=None, approval=None,
            settlement=None, net_margin=20.0, total=105000, with_cr=True):
    import db
    cr = {"payment": {"items": [
        {"type": "訂金", "pct": 30, "received": True, "receivedAt": "2026-03-01", "actualAmount": 31500, "feeAmount": 0},
        {"type": "尾款", "pct": 70, "received": False}]}}
    if sales_role is not None:
        cr["roles"] = {"sales": sales_role}
    cr.update(cr_extra or {})
    cr["ref"] = quote_no                                  # 每列的 caseRecord 文字都不同，計次才分得出「同一列解析幾次」
    data = {}
    if deal_tag:
        data["dealTag"] = deal_tag
    if with_cr:
        data["caseRecord"] = cr
    if approval is not None:
        data["approval"] = approval
    if settlement is not None:
        data["settlement"] = settlement
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, "
            "updated_at, deal_tag, quote_date, sales_person_id, sales_person, net_margin_pct) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, status, "客戶" + quote_no[-2:], "專案" + quote_no[-2:], total, round(total / 1.05),
             json.dumps(data, ensure_ascii=False), "2026-01-01T00:00:00", "2026-01-01T00:00:00",
             deal_tag, "2026-02-03", opener, "開單者", net_margin))
        conn.commit()
    finally:
        conn.close()


def _appr(me, status="pending"):
    return {"requestedBy": "x", "requestedByDisplay": "申請人", "reasons": ["毛利低"], "currentTier": 0,
            "tiers": [{"approvers": [{"username": me, "status": status}]}]}


def _fin(pct, profit, **kw):
    return {"status": "finalized", "summary": {"netProfit": profit, "netMarginPct": pct, "quotedPretax": 100000,
                                               "profitDiff": 500, **kw}}


@pytest.fixture()
def world(client, make_user):
    """部門 A（alice）、B（bob）；各種狀態／標籤／角色的報價單。回 {使用者名: 標頭, 'a': 部門A id, 'b': 部門B id}。"""
    import db
    # 修整只動讀取方式；輸出特徵用 superadmin／admin（逐案可見與財務檢視皆直通）比對。
    # 角色／財務卡片的權限矩陣見 test_dashboard_finance_cards_access_*。
    users = {n: make_user(n, role=r) for n, r in (("pf_admin", "superadmin"), ("pf_admin2", "admin"), ("pf_alice", "sales"),
                                                   ("pf_bob", "sales"))}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO divisions (name, created_at) VALUES ('測試處', '2026-01-01T00:00:00')")
        div = conn.execute("SELECT id FROM divisions WHERE name='測試處'").fetchone()[0]
        for n in ("部門A", "部門B"):
            conn.execute("INSERT INTO departments (division_id, name, created_at) VALUES (?,?,'2026-01-01T00:00:00')", (div, n))
        a = conn.execute("SELECT id FROM departments WHERE name='部門A'").fetchone()[0]
        b = conn.execute("SELECT id FROM departments WHERE name='部門B'").fetchone()[0]
        ids = {}
        for u, d, disp in (("pf_alice", a, "愛麗絲"), ("pf_bob", b, "鮑伯")):
            conn.execute("UPDATE users SET department_id=?, display_name=? WHERE username=?", (d, disp, u))
            ids[u] = conn.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    al, bo = ids["pf_alice"], ids["pf_bob"]
    alice_role = {"username": "pf_alice", "display": "愛麗絲"}
    # 草稿（不屬任何統計，但算進 totalQuotes）；有 caseRecord 的草稿（保固仍會被算到）
    _insert("PF-001", "草稿", "", opener=al, with_cr=False)
    _insert("PF-002", "草稿", "", opener=bo, cr_extra={"devices": [DEV_OLD]})
    # 待審核／簽核中（waitingForMe、pendingList）
    _insert("PF-003", "待審核", "", opener=al, approval=_appr("pf_admin2"), with_cr=False)
    _insert("PF-004", "簽核中", "", opener=bo, approval=_appr("pf_admin2"), with_cr=False)
    _insert("PF-005", "簽核中", "", opener=al, approval=_appr("pf_admin2", "approved"), with_cr=False)
    # 已送出（marginTop5 的候選）
    _insert("PF-006", "已送出", "", opener=al, net_margin=35.5, with_cr=False)
    _insert("PF-007", "已送出", "已作廢", opener=bo, net_margin=10.0, with_cr=False)
    # 已成案／已結案（付款、應收、保固、設備）
    _insert("PF-008", "已送出", "已成案", opener=al, sales_role=alice_role, net_margin=25.0,
            cr_extra={"devices": [DEV_OLD, DEV_FAR, DEV_NONE]})
    _insert("PF-009", "已送出", "已成案", opener=bo, sales_role="沒有帳號的人", net_margin=18.0)
    _insert("PF-010", "已送出", "已結案", opener=bo, net_margin=30.0, settlement=_fin(28.0, 28000))
    _insert("PF-011", "已送出", "已結案", opener=al, net_margin=22.0,
            settlement={"status": "draft", "summary": {"netProfit": 1, "netMarginPct": 99.0, "quotedPretax": 1}})
    _insert("PF-012", "已送出", "已結案", opener=al, net_margin=26.0,
            settlement={"status": "finalized", "summary": {"grossProfit": 30000, "grossMarginPct": 30.0, "quotedPretax": 100000}})
    # 非成案但帶有精算 JSON（不得進 marginComparison）
    _insert("PF-013", "已送出", "", opener=al, settlement=_fin(50.0, 50000), with_cr=False)
    return {"admin": _login(client, *users["pf_admin"]), "admin2": _login(client, *users["pf_admin2"]), "a": a, "b": b}


def _scrub(o):
    """略去隨今天變動的欄位（保固剩餘天數）。"""
    if isinstance(o, dict):
        return {k: _scrub(v) for k, v in o.items() if k not in ("daysLeft", "financeVisible")}      # financeVisible 是修整後才有的新鍵（見 access 測試）
    if isinstance(o, list):
        return [_scrub(v) for v in o]
    return o


def _snapshot(client, w):
    out = {}
    for who in ("admin", "admin2"):
        for dept in (None, "a", "b"):
            r = client.get("/api/dashboard/stats", headers=w[who], params={"department_id": w[dept]} if dept else {})
            assert r.status_code == 200, r.text
            out["%s|%s" % (who, dept or "all")] = _scrub(r.json())
    return out


def _golden_dump(client, w):      # 在修整前的程式上跑一次，把結果貼成 GOLDEN
    return json.dumps(_snapshot(client, w), ensure_ascii=False, sort_keys=True, indent=1)


def test_output_is_identical_to_the_pre_change_golden_for_mixed_rows_roles_and_departments(client, world):
    assert GOLDEN is not None, "GOLDEN 尚未產生"
    got = _snapshot(client, world)
    want = json.loads(GOLDEN)
    assert set(got) == set(want)
    for k in sorted(want):
        assert got[k] == _without_finance_cards(k, want[k]), k


def _without_finance_cards(key, golden):
    """第42班：GOLDEN 是修整前（admin 有財務卡片）的輸出；現在財務卡片只給 superadmin 與財務角色 ⇒ admin2 的卡片欄位為空，其餘不變。"""
    if not key.startswith("admin2|"):
        return golden
    w = dict(golden)
    w["paymentItems"], w["marginTop5"], w["marginComparison"], w["settledSummary"] = [], [], [], {}
    w["receivableSummary"] = {"total": 0, "received": 0, "unreceived": 0, "feeTotal": 0, "netReceived": 0}
    return w


def test_each_case_record_is_parsed_once_per_request(client, world, monkeypatch):
    """付款、保固、設備、應收四段原本各自 json.loads 一次同一份 caseRecord。"""
    import modules.analytics.api.dashboard as dash
    seen = []
    real = json.loads

    def counting(s, *a, **kw):
        if isinstance(s, str) and '"payment"' in s:          # caseRecord 的文字（本檔的 fixture 都有 payment）
            seen.append(s)
        return real(s, *a, **kw)

    monkeypatch.setattr(dash.json, "loads", counting)
    r = client.get("/api/dashboard/stats", headers=world["admin"])
    assert r.status_code == 200, r.text
    assert seen, "沒有解析到 caseRecord：前提不成立"
    assert max(seen.count(x) for x in set(seen)) == 1, "同一份 caseRecord 在一次請求內被解析了不只一次"
