# P1／P3 突變清單（能力目錄＋可自訂點）

> 稽核 AUDIT-D-P1P3 P-S4：突變清單落地，讓人照著重跑。最後一次執行：2026-09-26 02:41（分支 wip/x-p1p3-fix）。
> P01～P16 沿用稽核 D 的編號（程式位置已隨 P-M1 修正改動）；M／S／O 為本次修正新增。

**重跑方法**：對表中的檔案做「原文 → 突變」的單一取代（原文在檔案內必須恰好出現一次），在 `backend/` 執行 `python -m pytest tests/platform/test_platform_catalog.py -q -rf -p no:cacheprovider --basetemp=%TEMP%\motrix-pytest-<視窗>-adhoc`（不加 -n：不搶測試鎖），確認「預期轉紅」每一題都在 FAILED 裡，然後還原並核對檔案雜湊。⏎ 代表換行。

| # | 突變 | 檔案 | 原文 → 突變 | 預期轉紅（題名或參數 id 子字串） | 結果 |
|---|---|---|---|---|---|
| P01 | 排版守門對不在點清單的 target 放行 | `backend/core/customization.py` | ``             out.append(_p(path + ".target", "不是登記過的可自訂點：%r" % (target,))) `` → ``             pass `` | 程式沒有提供的欄位；test_hidden_point_is_rejected_by_layout_guard；test_unloaded_module_points_are_rejected | 🔴 7 題紅 |
| P02 | 不檢查該點允許的操作 | `backend/core/customization.py` | ``         if op not in p["ops"]: `` → ``         if False: `` | 隱藏核心欄位；改名核心欄位；側欄改名 | 🔴 3 題紅 |
| P03 | 核心欄位可 hide／relabel | `backend/core/customization.py` | `` "ops": list(OPS_CORE_FIELD if core else OPS_DISPLAY_FIELD)} `` → `` "ops": list(OPS_DISPLAY_FIELD)} `` | test_core_and_display_fields_get_different_ops；隱藏核心欄位 | 🔴 3 題紅 |
| P04 | 欄位可移到別的容器 | `backend/core/customization.py` | ``     elif p["kind"] == "field" and not _same_container(p, dest): `` → ``     elif False: `` | 欄位搬到別張表單；列表欄位搬到表單 | 🔴 2 題紅 |
| P05 | 不驗 schema 版本 | `backend/core/customization.py` | ``     if c.get("schema") not in SCHEMA_VERSIONS or isinstance(c.get("schema"), bool): `` → ``     if False: `` | 看不懂的 schema | 🔴 3 題紅 |
| P06 | 頁面不必在 pages[].path | `backend/core/customization.py` | ``         if name not in declared_pages: `` → ``         if False: `` | 頁面不在 pages[] | 🔴 1 題紅 |
| P07 | 選單項不必是本頁按鈕 | `backend/core/customization.py` | ``             if it not in akeys: `` → ``             if False: `` | 選單項目不是按鈕 | 🔴 1 題紅 |
| P08 | perm 不驗 | `backend/core/customization.py` | ``         if "perm" in act and act["perm"] not in perms: `` → ``         if False: `` | 按鈕權限不在 permissions | 🔴 1 題紅 |
| P09 | 不認得的鍵放行（module.json 與排版操作共用 _check_keys） | `backend/core/customization.py` | ``         if k not in required and k not in optional: `` → ``         if False: `` | 不認得的頂層鍵；不認得的鍵；鍵名打錯 | 🔴 5 題紅 |
| P10 | 端點不存在不報 | `backend/core/catalog.py` | ``         if ep and ep not in have: `` → ``         if False: `` | test_point_with_missing_endpoint_is_hidden_and_reported；test_hidden_point_is_rejected_by_layout_guard | 🔴 4 題紅 |
| P11 | 版型不存在不報 | `backend/core/catalog.py` | ``         elif p["template"] not in templates: `` → ``         elif False: `` | test_output_with_missing_template_is_hidden_and_reported | 🔴 1 題紅 |
| P12 | 有問題的點照樣列出（_module_points 不過濾） | `backend/core/catalog.py` | ``         if p["id"] in bad:⏎            continue `` → ``         pass `` | test_point_with_missing_endpoint_is_hidden_and_reported；test_hidden_point_is_rejected_by_layout_guard；test_output_points_need_output_engine | 🔴 6 題紅 |
| P13 | 同一區段允許兩個擁有者 | `backend/core/catalog.py` | ``         if old is not None and old[0] != owner: `` → ``         if False: `` | test_two_owners_for_one_section_is_an_error | 🔴 1 題紅 |
| P14 | 區段例外不隔離 | `backend/core/catalog.py` | ``         except Exception as e:                                  # noqa: BLE001 一個區段壞掉 `` → ``         except ZeroDivisionError as e:                                  # noqa: BLE001 一個區段壞掉 `` | test_broken_section_does_not_break_catalog | 🔴 1 題紅 |
| P15 | loader 不呼叫 require_valid | `backend/core/loader.py` | ``             customization.require_valid(manifest) `` → ``             pass  # customization.require_valid(manifest) `` | test_loader_refuses_module_with_broken_customization | 🔴 1 題紅 |
| P16 | 非超級管理員可讀 | `backend/routers/platform_catalog.py` | `` _require_user(authorization, require_superadmin=True) `` → `` _require_user(authorization, require_superadmin=False) `` | test_catalog_endpoint_superadmin_only | 🔴 1 題紅 |
| M1a | check_layout 改吃未過濾的點（稽核探針的原狀） | `backend/core/catalog.py` | ``     return customization._check_ops(layout_points(module_key), ops) `` → ``     return customization._check_ops([p for m in registry.loaded() if module_key in (None, m.key) for p in customization._raw_points(m.manifest)], ops) `` | test_hidden_point_is_rejected_by_layout_guard；test_menu_drops_hidden_buttons；test_only_one_way_to_get_points | 🔴 7 題紅 |
| M1b | 選單 items 不過濾被藏起的按鈕 | `backend/core/catalog.py` | ``             items = [it for it in p["items"] if it not in bad] `` → ``             items = list(p["items"]) `` | test_menu_drops_hidden_buttons；test_menu_with_all_buttons_hidden_is_hidden | 🔴 2 題紅 |
| M1c | layout_points 不依 module_key 篩選 | `backend/core/catalog.py` | ``         if module_key is None or m.key == module_key: `` → ``         if True: `` | test_unloaded_module_points_are_rejected | 🔴 1 題紅 |
| M1d | build() 繞過 _module_points 直接取 _raw_points | `backend/core/catalog.py` | ``         pts, problems = _module_points(m, templates, eps) `` → ``         pts, problems = customization._raw_points(man), [] `` | test_only_one_way_to_get_points；test_point_with_missing_endpoint_is_hidden_and_reported；test_menu_drops_hidden_buttons | 🔴 6 題紅 |
| M2a | select_template 不驗版型 | `backend/core/customization.py` | ``             if not isinstance(choices, list) or o["template"] not in choices: `` → ``             if False: `` | 選不存在的版型 | 🔴 1 題紅 |
| M2b | 可選版型取模組自己寫的那一個，不取輸出引擎 | `backend/core/catalog.py` | ``             p = dict(p, templates=sorted(templates)) `` → ``             p = dict(p, templates=[p["template"]]) `` | test_select_template_choices_come_from_output_engine | 🔴 1 題紅 |
| S1a | move 不驗目的地種類（MOVE_DEST_KINDS） | `backend/core/customization.py` | ``     elif dest["kind"] not in kinds: `` → ``     elif False: `` | 區塊移到按鈕底下；按鈕移到區塊 | ⚪ 未轉紅（見註） |
| S1b | 不在 MOVE_DEST_KINDS 的點也可以帶 to | `backend/core/customization.py` | ``     kinds = MOVE_DEST_KINDS.get(p["kind"]) `` → ``     kinds = MOVE_DEST_KINDS.get(p["kind"], tuple(OPS_BY_KIND) + ("field",)) `` | 匯出換容器；選單換容器；側欄換群組 | 🔴 3 題紅 |
| S1c | 區塊可移到別張表單 | `backend/core/customization.py` | ``     elif p["kind"] == "section" and dest["id"] != p.get("parent"): `` → ``     elif False: `` | 區塊移到別張表單 | 🔴 1 題紅 |
| S1d | 按鈕可放進別頁的選單 | `backend/core/customization.py` | ``     elif p["kind"] == "action" and _page_of(dest["id"], "/menu:") != _page_of(p["id"], "/action:"): `` → ``     elif False: `` | test_action_moves_only_into_same_page_menu | 🔴 1 題紅 |
| S1e | index 不驗 | `backend/core/customization.py` | ``     if "index" in o and (not isinstance(o["index"], int) or isinstance(o["index"], bool) or o["index"] < 0): `` → ``     if False: `` | index 為負 | 🔴 1 題紅 |
| S2a | 排版操作不驗鍵 | `backend/core/customization.py` | ``         _check_keys(o, *OP_KEYS[op], path, out) `` → ``         pass `` | 不認得的鍵；鍵名打錯；側欄帶群組鍵 | 🔴 4 題紅 |
| S2b | reorder 不驗 order | `backend/core/customization.py` | ``             if not isinstance(order, list) or len(order) != len(kids) or set(order) != set(kids): `` → ``             if False: `` | reorder 少一個；reorder 夾帶別的點；test_menu_drops_hidden_buttons | 🔴 3 題紅 |
| S2c | add_section 不驗撞名 | `backend/core/customization.py` | ``                 if "%s/section:%s" % (target, o["key"]) in by_id: `` → ``                 if False: `` | 新增區塊撞名 | 🔴 1 題紅 |
| O2 | 側欄可改名 | `backend/core/customization.py` | ``     "sidebar": ("move", "hide", "show"), `` → ``     "sidebar": ("move", "hide", "show", "relabel"), `` | 側欄改名 | 🔴 1 題紅 |

## 註

- S1a：**等價突變（未轉紅，保留）**：每一種可帶 `to` 的點都另有更嚴的容器檢查——欄位 `_same_container`（內含種類）、區塊 `to == parent`（必為 form）、按鈕 `_page_of(to, '/menu:')` 同頁（非選單 id 不會相等）——所以拿掉種類檢查不改變任何結果。留著它是為了錯誤訊息與 `MOVE_DEST_KINDS` 對 P9 的說明作用；若之後新增可帶 `to` 的種類而沒有專屬檢查，這一行就是唯一的防線。
- 「未載入模組」（P-M1 第三項）沒有程式突變：`layout_points` 的來源只有 `registry.loaded()`，未載入模組的 manifest 不在 registry 裡。題目 `test_unloaded_module_points_are_rejected` 以同一份描述 `register` 之後轉為通過作為正對照，證明它確實在看載入狀態。
- 單一入口守門 `test_only_one_way_to_get_points` 的正對照是 `test_entry_guard_positive_control`（別處呼叫、允許檔的別的函式、模組層 import 各亮一次）。
