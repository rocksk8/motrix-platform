# -*- coding: utf-8 -*-
"""`EM1` · 長錯誤訊息（>25 字）——讀者錯了的那幾條換成畫面上的詞（`docs/windows/SPEC-EM1.md` §2b／§3）。

§2b① 要改的 6 條：5 條在這裡（第 6 條 `startup.py` 的 Edge 路徑已在 `EM10` 改掉）。
§3 驗收：
① 改後訊息**不含**它對應的程式詞彙（逐條釘，不是關鍵字黑名單）
③ 其餘長訊息**一個字都沒變**（凍結清單：2026-09-24 以 ast 從 HEAD 抽出、扣掉要改的 6 條，共 40 條）
④ 訊息裡的畫面詞彙在對應的 html 裡**逐字找得到**
⑤ `map_points.py` 那段 uvicorn／access log 的設計理由搬進註解，**註解裡那一段要還在**
⚠️ ② 資訊量不減是人工題：對照紀錄寫在 commit 訊息裡。
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"

#: ③ 凍結清單：(檔案, 訊息原文)。⚠️ 這張表紅的時候，先確認是不是有人「順手改」了文案。
_UNTOUCHED = (
    ('routers/approval_delegates.py',
     '僅能設定自己的簽核代理人，如需代替他人設定請聯絡最高管理員'),
    ('routers/auth.py',
     '驗證碼不正確，請確認驗證 App 時間與密鑰輸入無誤'),
    ('routers/auth.py',
     '手機目前登入的帳號跟這次核准請求不符，請改用密碼核准'),
    ('routers/auth.py',
     '此 Passkey 是在舊的系統網域下註冊的，因網域變更已失效且無法復原。請改用密碼登入後，到「修改密碼」頁重新註冊一張。'),
    ('routers/bonus.py',
     '「手動指定」需要至少指定一位人員，否則這個項目永遠不會出現在任何一張獎金分潤單上。'),
    ('routers/bonus.py',
     '這張獎金分潤單已經發放，不能直接作廢——錢已經出去了，請先開立沖銷傳票，沖銷完成後再處理這張單。'),
    ('routers/case_extra_expenses.py',
     '這筆額外支出已核准，附件已上鎖。要補憑證請按「編輯」提出變更申請，新附件會在簽核通過後一併生效'),
    ('routers/cashier.py',
     'status 必須為 unreceived／received／all'),
    ('routers/completion_notes.py',
     '已回簽（客戶已驗收）的完工單不可撤銷核准，請先取消回簽'),
    ('routers/completion_notes.py',
     '系統已設定簽核流程，此完工單缺少簽核層資料，請重新送審'),
    ('modules/subcontract/api/contractor_vouchers.py',
     '此帳號沒有檢視財務金額的權限（需要「財務金額可視」模組）'),
    ('modules/subcontract/api/contractor_vouchers.py',
     '系統已設定簽核流程，此申請缺少簽核層資料，請重新送審'),
    ('modules/daily_tasks/api.py',
     'year_month 格式錯誤，應為 YYYY-MM'),
    ('routers/dashboard.py',
     '僅管理員或具『應收帳款／銷售訂單』模組的使用者可查閱'),
    ('routers/dashboard.py',
     '此帳號沒有檢視財務金額的權限（需要「財務金額可視」模組）'),
    ('routers/dev_crm.py',
     '此案件已連結報價單，如需異動或解除請透過「修改連結」送審'),
    ('routers/inventory.py',
     '僅在庫（未出貨/未登載）狀態可直接刪除，其餘狀態請用「退回庫存」調整'),
    ('routers/inventory.py',
     '序號不得為空白（每一台實體設備都需要實際序號才能建立庫存）'),
    ('routers/invoice_vouchers.py',
     '此帳號沒有檢視財務金額的權限（需要「財務金額可視」模組）'),
    ('routers/invoice_vouchers.py',
     '系統已設定簽核流程，此憑據缺少簽核層資料，請重新送審'),
    ('routers/map_points.py',
     'X-Map-Position 的格式是 <lat>,<lon>,<accuracy>'),
    ('routers/map_points.py',
     '給了座標就要給 accuracy（公尺）——我們不替瀏覽器猜一個誤差值'),
    ('routers/org_structure.py',
     '此部門仍有使用者，請先將人員轉移到其他部門或設為未分類'),
    ('routers/payment_requests.py',
     '此帳號沒有檢視財務金額的權限（需要「財務金額可視」模組）'),
    ('routers/payment_requests.py',
     '系統已設定簽核流程，此請款單缺少簽核層資料，請重新送審'),
    ('routers/quotations.py',
     '此帳號沒有檢視財務金額的權限（需要「財務金額可視」模組）'),
    ('routers/quotations.py',
     '案件已結案並鎖定，此操作不支援於已結案案件（如需修正請透過案件資料整體編輯，或聯繫最高管理員）'),
    ('routers/quotations.py',
     '報價單需完成簽核（狀態為「已送出」）才能標記為「已成案」'),
    ('routers/quotations.py',
     '這個版本的存檔檔案已不存在（PDF 存檔目錄可能被搬移或清理過）'),
    ('routers/quotations.py',
     '這樣設定會讓階段之間互相循環依賴，請重新選擇前置階段'),
    ('routers/quotations.py',
     '系統已設定簽核流程，此報價單缺少簽核層資料。請請申請人收回並重新送審，以套用最新簽核設定'),
    ('routers/reports.py',
     '僅管理員、或具『營運報表』／『應收帳款』模組的使用者可存取報表'),
    ('routers/reports.py',
     'CSV 編碼無法辨識，請確認匯出檔案格式（支援 UTF-8 / Big5）'),
    ('routers/shipping_notes.py',
     '已回簽（客戶確認收貨）的出貨單不可撤銷核准，請先取消回簽'),
    ('routers/shipping_notes.py',
     '系統已設定簽核流程，此出貨單缺少簽核層資料，請重新送審'),
    ('routers/system.py',
     '除了 localhost 之外，Origin 必須是 https://（瀏覽器規格要求）'),
    ('routers/system.py',
     'RP ID 與 Origin 必須同時設定或同時清空'),
    ('routers/system.py',
     '找不到可發送對象：請確認「信件與通知收件設定」的測試信收件人，並為其帳號填寫 Email'),
    ('routers/system.py',
     'cycle_start_day 需介於 1～28 之間（29 以後的日子二月沒有）'),
)
# M11 的「沒有要變更的設定（scanHours／notifyHours）」由 modules/tender_radar/tests/ 自己釘（2026-09-25）


def _page(name):
    """畫面上看得到的文字。

    📌 2026-09-24（B7）：權限畫面（users.html）的模組名稱改由 `/api/modules/catalog`
       供給（唯一來源 helpers/module_registry.py），不再寫死在頁面裡 ⇒ 那一頁的「畫面詞彙」
       ＝頁面文字＋registry 的模組名稱。斷言不變。
    """
    text = (ROOT / "frontend" / name).read_text(encoding="utf-8")
    if name == "pages/users.html":
        from helpers.module_registry import MODULES
        text += " " + " ".join(label for _k, label, _g in MODULES)
    return text


#: (檔案, 函式, 挑出那一條的關鍵片段, 不可以再出現的程式詞彙, 必須在畫面上找得到的詞, 畫面檔)
CASES = (
    ("routers/case_action_items.py", None, "需要工程主管確認", ("project_approve_eng",),
     ("案件待辦－工程主管確認",), "pages/users.html"),     # CU2b 用詞裁示：代辦→待辦
    ("routers/case_action_items.py", None, "需要業務確認", ("project_approve_biz",),
     ("案件待辦－業務確認",), "pages/users.html"),
    ("routers/system.py", None, "記錄對象", ("log_date", "user_id", "content"),
     ("日期", "記錄對象", "工作內容"), "pages/case-management.html"),
    ("routers/system.py", None, "備份目標", ("backend", "local_drive", "s3"),
     ("備份目標", "本機磁碟機", "S3 相容物件儲存"), "pages/company-profile-settings.html"),
    ("modules/subcontract/api/vendor_contractors.py", None, "不支援的驗收操作", ("pending_acceptance", "accepted", "action"),
     ("待驗收", "確認驗收"), "pages/case-management.html"),
)


def _all_details(rel):
    tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
    return [n.args[1].value for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "HTTPException"
            and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant)
            and isinstance(n.args[1].value, str)]


def test_em1_the_five_messages_speak_the_screen_words_not_the_code_words():
    for rel, _fn, anchor, banned, screen, page in CASES:
        hits = [d for d in _all_details(rel) if anchor in d]
        assert hits, "%s 找不到含「%s」的訊息 —— 退回改錨點" % (rel, anchor)
        for msg in hits:
            bad = [w for w in banned if w in msg]
            assert not bad, "%s 的訊息仍含程式詞彙 %r：%r" % (rel, bad, msg)
            html = _page(page)
            missing = [w for w in screen if w not in msg or w not in html]
            assert not missing, (
                "%s 的訊息 %r：這些畫面詞彙沒有同時出現在訊息與 %s：%r"
                % (rel, msg, page, missing))


def test_em1_the_map_message_no_longer_explains_our_logs_but_the_comment_still_does():
    src = (BACKEND / "routers" / "map_points.py").read_text(encoding="utf-8")
    msgs = [d for d in _all_details("routers/map_points.py") if "網址" in d]
    assert msgs, "找不到座標放在網址上的那一句 —— 退回改錨點"
    for m in msgs:
        assert "uvicorn" not in m and "access log" not in m, "理由仍在給使用者看的訊息裡：%r" % m
        assert "X-Map-Position" in m, "訊息要說出改用什麼：%r" % m
    comments = "\n".join(l for l in src.splitlines() if l.strip().startswith("#"))
    assert "access log" in comments, "那段設計理由沒有搬進註解（§3⑤：它是這個決定唯一的記錄）"


def test_em1_the_other_long_messages_did_not_change_a_single_character():
    missing = []
    cache = {}
    from core import source_tree
    for rel, msg in _UNTOUCHED:
        if not source_tree.module_installed(rel):
            continue                      # 模組被拿掉（選配／反向控制）：它的訊息本來就不在
        if rel not in cache:
            cache[rel] = set(_all_details(rel))
        if msg not in cache[rel]:
            missing.append((rel, msg[:60]))
    assert not missing, (
        "這些長訊息被改了或不見了（EM1 只改 5 條，其餘一個字都不動）：\n%s"
        % "\n".join("  %s  %r" % x for x in missing))
