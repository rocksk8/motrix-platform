# DOCSYNC-T52 — 第 46～51 班文件同步（05 視窗）

分支 `wip/t52-05-docsync`，基底 `origin/platform` cab72495d。只改文件，未跑 pytest、未動產生檔（UNIT-INDEX／CACHE-INDEX 等）。
平台層文件（PLAYBOOK、MODULE-GUIDE、PROD-DEV-CHANNEL、MONEY-FLOWS、CACHE-INDEX）屬 node-39，見 `DOCSYNC-N39-T52.md`。

## 已改（各模組 README.md／SPEC.md，事實來源＝各模組 CHANGELOG 與程式）
- payroll README／SPEC：端點與權限表、狀態與流程（S6 繞過關閉、不得自核、作廢已核准需最高管理者）、獎金基數＝營業利益（第 49 班移除 8 個 POST、GET 保留）、migration 與回滾缺口、approval-reveal 稽核、派發連結、IP。
- case README／SPEC：利潤規則 v2（管銷＝max(直接毛利,0)×比率、五項移除、慈善）、開關與權限、已結案不動、標籤用語、採購單銀行區塊與遮罩、旗標嚴格解析、`case.access.allowed`、FORM V3.19、第 51 班狀態晶片與材料連結。
- arap、subcontract、accounting、analytics、netplan、tender_radar、lodging、supply、filehub README：各加「第 46～51 班追加」節（預定付款日、查看收款人銀行稽核、派發⇄勞報單連結、嚴格布林、逐案權限、用語更名等）。
- INTEGRATION-POINTS.md：核對 58 個模組宣告的 capability，IP-112～115、IP-12 `allowed` 等皆已存在，**無需修改**。

## 發現過時但未動
- `settlement.html:1543` 提示文字過時（既有，非本批引入；屬程式檔，不在文件同步範圍）。
- 慈善（charity-on-quote）文件僅標「規劃中、尚未上線」，T52 落地後須再更新（case README 該節、analytics 標籤、IP）。
- 各模組文件普遍沒有稽核動作目錄（非慣例）；第 45 班後新增動作（`cashier.payee_bank_view`、`settings.po_bank_block.update`、`settings.overhead.update`、`quotation.overhead_pct_change`、`payslip.*`、`dispatch.payslip_link／unlink`、`user.put_rejected_subtract`）只在涉及處提及，未另建目錄。
- 產生檔與平台層文件不在本批範圍。
