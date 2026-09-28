# 最终验证：点击有属性的概念（患者 PATIENT），确认默认显示"属性"页签内容
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1600, 'height': 900})
    page.goto('http://127.0.0.1:5173/login')
    page.wait_for_load_state('networkidle')
    page.fill('input[type="text"], .el-input__inner >> nth=0', 'admin')
    page.fill('input[type="password"]', 'admin123')
    page.click('button:has-text("登")')
    page.wait_for_url('**/architecture', timeout=10000)

    # 走架构页下钻路径（?concept=PATIENT），同时覆盖 URL 联动场景
    page.goto('http://127.0.0.1:5173/ontology?concept=PATIENT')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(2000)
    drawer = page.locator('.el-drawer.open')
    print('URL下钻抽屉打开:', drawer.count() == 1)
    attrs_pane = drawer.locator('#pane-attrs')
    print('URL下钻 属性pane可见:', attrs_pane.is_visible(), '属性行数:', attrs_pane.locator('.el-table__row').count())
    page.keyboard.press('Escape')
    page.wait_for_timeout(600)

    # 再走表格行点击路径（本次修复的场景）
    page.goto('http://127.0.0.1:5173/ontology')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(1200)
    page.locator('.el-table__row', has_text='患者').first.click()
    page.wait_for_timeout(2000)
    drawer = page.locator('.el-drawer.open')
    print('行点击抽屉打开:', drawer.count() == 1)
    active = drawer.locator('.el-tabs__item.is-active')
    print('激活页签:', active.inner_text() if active.count() else '(无)')
    attrs_pane = drawer.locator('#pane-attrs')
    print('属性pane可见:', attrs_pane.is_visible(), '属性行数:', attrs_pane.locator('.el-table__row').count())
    for r in attrs_pane.locator('.el-table__row').all()[:3]:
        print('  -', r.inner_text().replace('\n', ' | '))
    page.screenshot(path='output/ui-test/drawer_fixed.png', full_page=False)

    # 页签切换仍正常（图页签）
    drawer.locator('.el-tabs__item', has_text='关系').click()
    page.wait_for_timeout(800)
    print('切换后 关系pane可见:', drawer.locator('#pane-relations').is_visible())
    print('切换后 属性pane隐藏:', not drawer.locator('#pane-attrs').is_visible())

    browser.close()
