# -*- coding: utf-8 -*-
"""報價表單 `FORM_VERSION` 守門：表單內容變了而版本號沒變 ⇒ 紅（擋建包）。

使用者表單原文：「加檢查，漏改就擋建包」。hichan-8d 查到 V2.0 之後有 24 個 commit 動過
`quotation-form.html` 而沒有遞增——這條規則（`docs/quick/mod-quotation.md`：「quotation-form.html
或其邏輯任何改動都須遞增——小改版 +0.1，大改版 +1」）在此之前完全靠人記。

# 做法

一本**帳**（`LEDGER`）：版本號 → 那一版表單的雜湊。雜湊前先：
- 拿掉 `const FORM_VERSION = '…'` 那一行（否則改版本號本身就會讓雜湊變）；
- 換行一律 LF（同一份內容在別台機器 checkout 成 CRLF 不可以變成「內容變了」）。

```
版本號在帳上、雜湊一樣     ⇒ 綠
版本號在帳上、雜湊不一樣   ⇒ 紅：內容變了而版本沒動 ⇒ 告訴你該 bump 成多少
版本號不在帳上、雜湊＝帳上最新那一版  ⇒ 綠（只改了版本號，A 要的對照組）
版本號不在帳上、雜湊也不同 ⇒ 紅：bump 了，但要把新版本登記進帳（印出那一行）
```
📌 帳以「推的當下 master 上的值」為基準（A 裁示）：V3.2 ＝ c0aa4d7。

# ⚠️ 範圍

只看 `frontend/pages/quotation-form.html` 本身。它引用的外部腳本（sidebar／notif／style.css…）
是全站共用，不是報價表單專屬；後端的報價版面（`pdf_gen`）也不在這一道守門裡。
"""
import hashlib
import pathlib
import re

FORM = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "pages" / "quotation-form.html"
_VERSION_LINE = re.compile(r"^\s*const FORM_VERSION = '(V\d+\.\d+)'\s*$")

#: 版本號 → 表單雜湊（拿掉版本號那一行、換行統一 LF 之後的 sha256）。
#: 🔑 bump 版本號時，照紅燈訊息把新的一行加在最後面。
LEDGER = {
    "V3.2": "298eb2e5e1a8ea8b55f229c7858f233beb745f02390af77bbe9129768f3eed0b",
    # V3.3（AC1，2026-09-24）：稅別選單取代 1～4% 稅率；舊單須改選法定稅別。
    "V3.3": "150f2ce783b0ce899ae070e0e145482fe83f7a67be5b017b98611f9f6ff76fe2",
    # V3.4（N14，2026-09-24）：內部成本區五個間接費改用文字框，接受千分位與全形數字。
    "V3.4": "d3ae947b74f10dfddbcc24ff1d5f3a16a453234424d11f6c3e8e30e6a3db7376",
    # V3.5（CU2b，2026-09-24）：用詞統一，成案確認視窗「完結案件」→「結案」。
    "V3.5": "50a278412a0931a70659f55dc94385b36489e6d0179b098c1ae77729165b29f1",
    # V3.6（2026-09-25）：新單載入期間使用者先點的條款組／打的條款，不再被預設組蓋回去；載入中點方塊不再誤跳「已改過」確認。
    "V3.6": "c41d54e353173dafdfb89de4f2a09e7e717dbb6e9c3205e9cb28da6c83bfbfec",
    # V3.7（R2，2026-09-25）：零稅率／免稅要選依據（營業稅法 §7、§8），送審前必填。
    "V3.7": "d9ef3bdcf0ff01d857837038d804e51e55bcd257cf5a534107dc917949d3e2df",
    # V3.8（X-R，2026-09-26，稽核 S-4）：免稅依據改營業稅法 §8 逐款下拉，下方顯示條文出處。
    "V3.8": "15882f3ed0ccf53a065a43b3a4c4cb24dc25c582dcc9d6d26740752eaa182e3a",
    # V3.9（X-VAT，2026-09-26）：金額／稅額改用 static/legal-round.js 四捨五入（與後端一致）。
    "V3.9": "e42e775f9955409b5baff053901aebe715a062b74c8c53ae9a618de2a9f781aa",
    # V3.10（個資蒐集告知，2026-09-26；列車上改號，V3.9 已被 X-VAT 使用）：聯絡人下方加告知區塊（列印告知書、已告知紀錄）。
    "V3.10": "7a6144213a3b04032c3fbf08ffe62a56dccd41bc6a34e39d610f43337a1b77af",
    # V3.11（H10 品牌設定，第十四班列車補號）：分頁圖示改讀 /api/system/branding/favicon（品牌包漏 bump，列車 --train 抓到）。
    "V3.11": "3712ad39fdf3c56889a3b5729d477470db4c80c0065644443a1ec44edaff8bf4",
    # V3.12（N1，2026-09-30）：成本欄「帶入承攬商報價」＋與承攬商報價的總差額提示。
    "V3.12": "e6ccb49c4c67635073b88457ab4821cbbbbcfefc9921767b591b90b35f52004d",
    # V3.13（2026-09-30，W1 檔案預覽 P1）：報價單附件開啟改用共用預覽元件（頁內預覽窗，不再開新分頁／換 photo-token）。
    "V3.13": "34caa8bc402939fccd7100d1974c1e04ca75c518115960e6002f4523ca506349",
# V3.14（2026-10-01，本地日期）：報價日期預設值與送審時間改用本地日期（MotrixDate；台灣 00:00–08:00 不再得到前一天）。
"V3.14": "cfa10080ec0d21d3db854eff16247f7520a384c2ae4ec1159db82cff89bc2598",
    # V3.15（2026-10-01，客戶回簽單）：回簽附件列出上傳者與時間、刪除鈕只給上傳者本人或 admin+、案件進度旁新增選填的「客戶回簽單 ＋上傳」入口；開啟既有報價單時一併帶入回簽欄位（清單與已回簽狀態）。
    "V3.15": "e885dc38b9427262702801ba6e710b8acde0fb4d3b8eba6aabdebea7241a1f06",
    # V3.16（2026-10-02，材料申請改字）：案件進度的階段標籤「叫料出貨」改稱「材料申請出貨」（只改顯示文字）
    "V3.16": "c901afcc97076006ec98c1cd32e018876d3a55ff2a4ac81965b31341d7dcdb83",
    # V3.17（第 39 班，2026-10-05）：公益金不為負——虧損案（直接毛利＜0）以 0 計並顯示「虧損案公益金以 0 計」。
    "V3.17": "e5003bdce559c168d7ddb9d4a6faeb93e07e6ac09e255d2359337dad95a4f674",
    # V3.18（第 47 班，2026-10-08）：報價人改選他人時，電話／Email 改由 GET /api/users/sales-contact 帶入（使用者清單對一般人員不再含別人的聯絡方式）。
    "V3.18": "9899da7ca5a7a748157203e9c403bc210cc3018fae7101f5bf0e203785fc67b1",
    # V3.19（第 48 班 S3，2026-10-09）：利潤算式改呼叫 static/profit-rules.js；管銷分攤比率（直接毛利×%，最高管理者可調、偏離預設警示）——口徑開關預設 legacy，畫面與數字不變；五個間接成本輸入拿掉（新口徑不計，舊單既有值唯讀顯示）。
    "V3.19": "5dd3efc404a0253a42c962a73cedc1096c58a496b1f82da01c21cf65dc7114dd",
    # V3.20（第 52 班，2026-10-10）：公益捐款基數——新基（charity_basis_mode=total）＝報價含稅金額×1%（標籤「公益捐款（報價含稅 1%）」，不看毛利、虧損案照扣）；舊基維持直接毛利×1%。
    "V3.20": "671d3bb323dacf678455852abb42db94405067aaa7fb172210a7a07017d76bfc",
    # V3.21（M1-a，2026-10-11）：毛利率顏色門檻改用 static/margin-tone.js 單一來源（報價單列表與報價單表單一致；案件管理沒有毛利率顏色）。
    "V3.21": "03f07e7720b5f07aadc8b5a074a70e1ed91dfa34ba6539fef2b4f8cf762d37ad",
    # V3.22（2026-10-11，t55）：欄位名稱「售後服務」改為「售後服務及備註說明」（表單、列印預覽、條款組管理；只改顯示，欄位鍵 afterSales 與已存資料不變）。
    "V3.22": "4b3d30ae4124e8bcd54007439dea8d5e5a93d5fe101f4e9b9dc328595947ca52",
    # V3.23（2026-10-13，M3 T5／T6）：擇一方案——品項組別、合計依方案選擇、計入品項合計、內部方案比較面板、備註說明句預覽。
    "V3.23": "71953f64288da314dca69ddd38beb947705cf91d221919a7bbb5e4bb4bee4c8a",
    # V3.24（2026-10-13）：內部損益區新增「專案毛利%」（不扣進項稅／管銷／公益）、未填成本提醒、可選的低於門檻提醒。
    "V3.24": "70c421a72d8830fdc8c5018e8e7409087a068e66aa01d8817f13efaf30058b0c",
    # V3.25（2026-10-15，S-ST2）：空白案件預設階段 seed 先等版面／旗標讀完；已發布階段樣板時不自動建立 5 個預設階段。
    "V3.25": "865ef9785ae66ba9caa96844fa0055d16460c03a1e94d9e6b183a6f42c0f9c90",
    # V3.26（2026-10-15，T62 e2e）：自訂欄位清空時送 {}（後端「沒送這個鍵＝保留舊值」，只有 {} 才會清掉）。
    "V3.26": "0d5786c9a44e81bb8e686a5a656a8706701f3b41816e0864b283b721a00f6c4d",
    # V3.27（2026-10-15，T64 A／B）：利潤顏色門檻改讀設定（預設＝原本的 12／20）；金額、日期走共用顯示格式器 MotrixFormat（預設輸出逐字相同）。
    "V3.27": "732b5f78d95b987ca441805953790de237c9c3bb9db6f415ea351b31f862d6c2",
    # V3.28（2026-10-15，T65）：三處儲存時間顯示改走共用格式器（輸出不變）
    "V3.28": "6dd52ee22b753944ca212b894a9b28566ca58560372490a16afa8ae3115818a3",
    # V3.29（2026-10-16，T66）：複製為新報價單後拖曳排序失效修復（init() 複製分支漏綁尾巴）；畫面不變。
    "V3.29": "33fb0d1f86126fea24c6dbadce5ebc87714b178f4aab37f0462ebed2cf07fe25",
    # V3.30（2026-10-17，T68 Q1）：公益比率可設定——報價單上的公益比率顯示改看這張單自己的戳記（沒有＝1%）。
    "V3.30": "823189c5721d29f2e9dcdec6d9c2697564c776216b0aaf1b61e625b4d6b71199",
    # V3.31（2026-10-17，T70-1）：新增模式「補登歷史案件」區塊（僅最高管理者且設定中心開關有效時出現）。
    "V3.31": "3d2a5cb35e12c207585383376248ed130a5280700236dde6bd72e853c3a5b57f",
    "V3.32": "eaa93caa402c80cd85bd260f346873a5210545d81466ef444f3ca1c9cb9aa0b3",
    "V3.33": "0a889862e43f6079b694d8c745584e0b7ccd0337fa670e45e432605d5ef8ff0b",
    # V3.34（2026-11-07，簽核二擇一 S1／S5）：核准綁內容指紋（`?id=` 載入路徑補設 _contentFp）；旗標單核准前跳「維持／編輯」、複查編輯走 POST /review-edit。
    "V3.34": "3e65cf8f8b9aa703594321e74105bf7dd8a7e99f109be0ae1c40f64ec6d86135",
    # V3.35（2026-11-11）：品項明細三個多行欄（品名／廠牌型號／備註）載入既有單、改值、欄寬變動時自動撐高，不再看起來被裁切。
    "V3.35": "ccc01661a699d5287d19cdd2bc5bbf7d071914a40d2fae79b01d7fa0779d16fa",
    # V3.36（2026-11-11）：送審前置檢查（沒部門／沒主管先攔下）、送審失敗顯示後端原因並還原狀態、已送出單選「已成案」改只打 PATCH（修 EM11 起的卡住）。
    "V3.36": "cc758ed914f67a53d1fd4613cfd4c695b3c0fee161e6ba5ce1af740ca734508f",
    # V3.38（2026-11-11，UX A6／E2）：送出審核確認視窗與按鈕補「這會…」說明、取消折讓說明；「INTERNAL · 成本分機」改白話「內部成本與利潤」。
    "V3.38": "9354622331a92886ff1d929f268869dabadb3f09b77d73b94593498b4db8000e",
    # V3.39（2026-11-11，簽核人編輯）：簽核人檢視待審核／簽核中時欄位預設 disabled、常駐「編輯」鈕（reconfirm_mode=on 才顯示）；核准前彈窗退場「編輯內容」；第 3 層以後編輯提示整條回第 1 層。
    "V3.39": "9dcbfae3a77ae7c34ee206ca290aa1fd341249c65bc9f598c404f13b15b28604",
    # V3.40（2026-11-11，UX 提案 C1～C3）：成本區預設收合（一行內部利潤摘要）、無金額不上警示色；品項表收合 7 欄＋備註改列下展開；客戶區眼睛鈕、個資告知預設收合。（V3.36 留給簽核人編輯鎖定分支）
    "V3.40": "9e7e64238e78dd73b50afa4cc7f40621eaf46ef1dba03766511c3ca9250d2d76",
    # V3.41（2026-11-11，多人同時編輯保護）：存檔撞樂觀鎖 409 時頂端持續橫幅＋「載入最新版」鈕、暫停自動存檔（原本 60 秒自動存檔撞 409 是無聲失敗）。
    "V3.41": "86ac311d7fd2e5cec565b963f8cad344dc9224b118199b16a9cd7fc0f8e165af",
    # V3.42（2026-11-11，ops）：待審核／簽核中，非簽核人（最高管理者、申請人…）開著單整張鎖唯讀＋橫幅「僅簽核人可編輯」。
    "V3.42": "34f8c8e59f38e4634513562c67e47178538a3992ae81c3b0f6307bc55b593b4d",
    # V3.43（2026-11-13，T81 整合）：手機／直立平板版面（工具列可換行、品項明細卡片化）；使用者可見稱呼統一為「最高管理者」。
    "V3.43": "c9cee597b1f6261c091ce7a14ae6136953bc3cba2aed606c89b2cf8bf07003ad",
    # V3.44（2026-11-13，我的帳號／報價用信箱）：業務聯絡信箱改讀 quoteEmailEffective（報價用信箱→公司對外信箱→本人 Email），舊名 quoteEmail 保留一版。
    #   T82 整合期同一版（V3.44 尚未出貨，只登記一次）另含：估價單（開單時可選報價單／估價單）、品項明細列對齊（≥768px）。
    "V3.44": "94dcc6344a18f7d570e8885309a83ae2b79843cc69455625192570e4c84efe08",
    # V3.45（2026-11-13，fix/superadmin-approver-edit-entry）：最高管理者（含同時是當層簽核人）開著待審核／簽核中的單，工具列有「解鎖編輯」入口；
    #   解鎖後欄位真的可編輯、「重新鎖定」真的鎖回去；送審人看到的唯讀橫幅多一行「要修改請先按『收回草稿』」；解鎖中隱藏核准／退回／駁回、不自動存檔、重新鎖定有未存修改先確認（h9 審查 M1／L1／L2；V3.45 尚未出貨，hash 同版更新）。
    "V3.45": "8c40e82c3e99f8f4f603b1d61b6d39e4a4ccc20a2cf5b7a677b26e389788dcc4",
}


def form_fingerprint(text):
    """回 `(版本號, 雜湊)`。找不到版本號那一行 ⇒ 版本號是 None。"""
    lines = text.replace("\r\n", "\n").split("\n")
    version, kept = None, []
    for line in lines:
        m = _VERSION_LINE.match(line)
        if m and version is None:
            version = m.group(1)
            continue
        kept.append(line)
    return version, hashlib.sha256("\n".join(kept).encode("utf-8")).hexdigest()


def _next_versions(version):
    major, minor = (int(x) for x in version[1:].split("."))
    return "V%d.%d" % (major, minor + 1), "V%d.0" % (major + 1)


def verdict(text, ledger):
    """回 `(ok, 訊息)`。規則見本檔開頭的表。"""
    version, digest = form_fingerprint(text)
    if version is None:
        return False, "找不到 `const FORM_VERSION = 'Vx.y'` 那一行——守門量不到東西。"
    if version in ledger:
        if ledger[version] == digest:
            return True, ""
        minor, major = _next_versions(version)
        return False, (
            "quotation-form.html 的內容變了，而 FORM_VERSION 還是 %s。\n"
            "⇒ 小改版（欄位微調／樣式／文案）改成 %s；大改版（版型結構／新增區塊／流程變更）改成 %s。\n"
            "⇒ 改完之後，把新版本登記進 tests/test_form_version_bumped_2026_09_24.py 的 LEDGER。"
            % (version, minor, major))
    latest = list(ledger)[-1]
    if ledger[latest] == digest:
        return True, ""          # 只改了版本號，內容與帳上最新那一版相同
    return False, (
        "FORM_VERSION 已改成 %s，但帳上還沒有這一版。\n"
        "⇒ 在 tests/test_form_version_bumped_2026_09_24.py 的 LEDGER 最後加一行：\n"
        '    "%s": "%s",' % (version, version, digest))


def test_form_version_is_bumped_whenever_the_quotation_form_changes():
    ok, msg = verdict(FORM.read_text(encoding="utf-8"), LEDGER)
    assert ok, msg


# ══════════════════════════════════════════════════════════════════════
# 對照組：規則本身（合成輸入，不看真的表單）
# ══════════════════════════════════════════════════════════════════════

_BASE = "<html>\n  const FORM_VERSION = 'V3.2'\n  <div>報價</div>\n</html>\n"
_LEDGER = {"V3.2": form_fingerprint(_BASE)[1]}


def test_form_version_rule_same_content_same_version_is_green():
    assert verdict(_BASE, _LEDGER) == (True, "")


def test_form_version_rule_changed_content_without_a_bump_is_red_and_says_how_much():
    ok, msg = verdict(_BASE.replace("報價", "報價單"), _LEDGER)
    assert not ok and "V3.3" in msg and "V4.0" in msg, msg


def test_form_version_rule_only_bumping_the_version_is_green():
    """A 要的對照組：只改 FORM_VERSION ⇒ 綠。"""
    assert verdict(_BASE.replace("'V3.2'", "'V3.3'"), _LEDGER) == (True, "")


def test_form_version_rule_a_bump_with_new_content_must_be_registered():
    text = _BASE.replace("'V3.2'", "'V3.3'").replace("報價", "報價單")
    ok, msg = verdict(text, _LEDGER)
    assert not ok and '"V3.3": "%s"' % form_fingerprint(text)[1] in msg, msg


def test_form_version_rule_line_endings_do_not_count_as_a_change():
    """同一份內容 checkout 成 CRLF（別台機器）不可以被當成「內容變了」。"""
    assert verdict(_BASE.replace("\n", "\r\n"), _LEDGER) == (True, "")


def test_form_version_rule_a_comment_mentioning_the_version_is_still_content():
    """只拿掉**那一行宣告**；註解裡寫到 FORM_VERSION 的文字照樣算內容。"""
    ok, _msg = verdict(_BASE.replace("<div>", "<!-- FORM_VERSION 說明 --><div>"), _LEDGER)
    assert not ok
