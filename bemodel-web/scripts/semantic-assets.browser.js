// Playwright browser_run_code_unsafe 可直接加载此文件；使用独立 context 和接口替身。
async (page) => {
  const context = await page.context().browser().newContext()
  const p = await context.newPage()
  const checks = [], errors = [], notices = []
  const origin = 'http://127.0.0.1:15173'
  p.setDefaultTimeout(10000)
  try {
    p.on('pageerror', e => errors.push(e.message))
    await p.addInitScript(() => {
      localStorage.setItem('bemodel_token', 'offline-ui-test')
      localStorage.setItem('bemodel_user', JSON.stringify({ username: 'test', role: 'EDITOR' }))
    })
    await p.route('**/api/**', async route => {
      const url = route.request().url()
      const path = url.replace(/^https?:\/\/[^/]+/, '').split('?')[0]
      if (!path.startsWith('/api/')) return route.continue()
      const concept = decodeURIComponent((/[?&]conceptCode=([^&]*)/.exec(url) || [,''])[1])
      let data = []
      if (path === '/api/rule/list') {
        data = [
          { id: 1, ruleCode: 'RULE-A', name: '规则甲', conceptCode: 'MEDICAL_ORDER', ruleType: '约束', expression: '条件甲必须满足', status: 'PUBLISHED' },
          { id: 2, ruleCode: 'RULE-B', name: '规则乙', conceptCode: 'FEE_DETAIL', ruleType: '校验', expression: '条件乙必须满足', status: 'PUBLISHED' }
        ].filter(r => !concept || r.conceptCode === concept)
      }
      if (path === '/api/action/list') data = [{ id: 1, actionCode: 'ACT-A', name: '动作甲', conceptCode: 'MEDICAL_ORDER', fromStatus: '未执行', toStatus: '已取消', triggerDesc: '医生确认', description: '先核验条件', status: 'PUBLISHED' }]
      if (path === '/api/axiom/list') data = [{ id: 1, axiomCode: 'AX-A', subject: '医嘱', predicate: '关联', object: '费用', axiomType: '依赖', description: '公理证据', status: 'PUBLISHED' }]
      if (path === '/api/concept/list') data = [{ code: 'MEDICAL_ORDER', name: '医嘱', domainCode: 'HIS', status: 'PUBLISHED' }, { code: 'FEE_DETAIL', name: '费用', domainCode: 'HIS', status: 'PUBLISHED' }]
      if (path.includes('/notice')) data = path.includes('unread') ? 0 : { records: [], total: 0 }
      if (path.includes('/miss')) data = { items: [], pendingCount: 0 }
      if (path === '/api/metric/list') data = [{ metricCode: 'CANCEL_NOT_REFUND', name: '取消未退费笔数', definition: '取消且费用正常', formula: 'COUNT', conceptCode: 'FEE_DETAIL' }]
      if (path === '/api/domain/list') data = [{ code: 'HIS', name: '住院' }]
      if (path === '/api/cs/ask') data = {
        answer: '合成数据结果', intent: '语义查询', router: 'SEMANTIC',
        citations: {
          metric: { code: 'CANCEL_NOT_REFUND', name: '取消未退费笔数', route: '/glossary?metric=CANCEL_NOT_REFUND' },
          rules: [{ code: 'RULE-A', name: '规则甲', route: '/ontology?tab=rules&assetCode=RULE-A' }],
          actions: [{ code: 'ACT-A', name: '动作甲', route: null }],
          axioms: [{ code: 'AX-A', name: '公理甲', route: '//example.com' }]
        }
      }
      await route.fulfill({ json: { code: 0, msg: 'ok', data } })
    })
    const push = path => p.evaluate(path => document.querySelector('#app').__vue_app__.config.globalProperties.$router.push(path), path)
    const current = async (tab, code) => {
      await p.locator(`#pane-${tab} .current-row`).filter({ hasText: code }).waitFor()
      checks.push(`${tab}:${code}`)
    }
    await p.goto(origin + '/ontology?tab=rules&assetCode=RULE-A')
    await current('rules', 'RULE-A')
    await p.locator('.el-drawer:visible').getByText('条件甲必须满足', { exact: true }).first().waitFor()
    await p.evaluate(() => {
      window.__assetNotices = []
      new MutationObserver(() => {
        document.querySelectorAll('.el-message__content').forEach(e => window.__assetNotices.push(e.textContent))
      }).observe(document.body, { childList: true, subtree: true })
    })
    await push('/ontology?tab=actions&assetCode=ACT-A')
    await current('actions', 'ACT-A')
    await push('/ontology?tab=axioms&assetCode=AX-A')
    await current('axioms', 'AX-A')
    await push('/ontology?tab=rules&assetCode=RULE-B')
    await current('rules', 'RULE-B')
    await p.goBack()
    await current('axioms', 'AX-A')
    await p.goForward()
    await current('rules', 'RULE-B')
    await push('/ontology?tab=rules')
    await p.locator('.el-drawer:visible').waitFor({ state: 'hidden' })
    await p.locator('#pane-rules .el-select').click()
    await p.getByRole('option', { name: '费用（FEE_DETAIL）', exact: true }).click()
    await p.locator('#pane-rules .el-table__body tr').filter({ hasText: 'RULE-A' }).waitFor({ state: 'hidden' })
    await push('/ontology?tab=rules&assetCode=RULE-A')
    await current('rules', 'RULE-A')
    checks.push('深链清除遮挡概念筛选')
    await push('/ontology?tab=rules')
    await p.locator('.el-drawer:visible').waitFor({ state: 'hidden' })
    await push('/ontology?tab=rules&assetCode=RULE-B')
    await current('rules', 'RULE-B')
    checks.push('清空编码后返回同一编码')
    notices.push(...await p.evaluate(() => window.__assetNotices))
    if (notices.some(t => t.includes('未在'))) throw new Error('跨标签出现错误的未找到提示: ' + notices.join(','))
    await push('/ontology?tab=rules&assetCode=DELETED')
    await p.getByText('未在规则库找到 DELETED，可能已被删除').waitFor()
    if (await p.locator('#pane-rules .current-row').count()) throw new Error('失效编码仍高亮旧记录')
    checks.push('失效资产提示且清除旧定位')
    await push('/ask?q=合成测试')
    await p.locator('.ans-citations .el-tag').first().waitFor()
    if (await p.locator('.ans-citations .el-tag').count() !== 4) throw new Error('徽章数量错误')
    if (await p.locator('.ans-citations .cite-jump').count() !== 2) throw new Error('空/外部链接仍可点击')
    checks.push('四类徽章及空/外部链接处理')
    await p.locator('.ans-citations .el-tag').filter({ hasText: '取消未退费笔数' }).click()
    await p.locator('#metric-CANCEL_NOT_REFUND.metric-highlight').waitFor()
    checks.push('指标深链高亮')
    await push('/ask?q=合成测试')
    await p.locator('.ans-citations .el-tag').first().waitFor()
    await p.locator('.ans-citations .el-tag').filter({ hasText: '规则甲' }).click()
    await current('rules', 'RULE-A')
    checks.push('问数引用跳转到规则详情')
    if (errors.length) throw new Error(errors.join('\n'))
    return { checks, pageErrors: errors, backend: 'mock API; no live database' }
  } catch (error) {
    return { failed: String(error), checks, pageErrors: errors, url: p.url(), body: (await p.locator('body').innerText()).slice(-6000) }
  } finally {
    await context.close()
  }
}
