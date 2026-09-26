"""e2e 共用：畫面上每個看得到的 `select[x-model]`，DOM 選中值 ≠ Alpine 模型值的清單（空＝一致）。

自 test_e2e_reports_period_select_matches_model 抽出（M08 搬遷：該檔隨營運分析模組搬走，其他頁的同型題仍要用）。
"""
MISMATCHES_JS = """() => [...document.querySelectorAll('select[x-model], select[x-model\\\\.number]')]
  .filter(s => s.offsetParent !== null)
  .map(s => {
    const expr = s.getAttribute('x-model') ?? s.getAttribute('x-model.number')
    let model
    try { model = Alpine.evaluate(s, expr) } catch (e) { model = '<err>' }
    return { expr, dom: s.value, model: model == null ? '' : String(model) }
  })
  .filter(r => r.dom !== r.model)"""
