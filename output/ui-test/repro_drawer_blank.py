# 复现：本体管理 → 点击概念行 → 详情抽屉默认页签是否空白
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
    page.goto('http://127.0.0.1:5173/ontology')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(1500)

    rows = page.locator('.el-table__body tr')
    print('概念行数:', rows.count())
    rows.first.click()
    page.wait_for_timeout(2000)

    drawer = page.locator('.el-drawer.open')
    print('抽屉可见:', drawer.count())
    page.screenshot(path='output/ui-test/drawer_initial.png', full_page=False)

    tabs = drawer.locator('.el-tabs__item')
    print('页签数量:', tabs.count())
    for i in range(tabs.count()):
        t = tabs.nth(i)
        print(f'  页签[{i}] text={t.inner_text()!r} aria-selected={t.get_attribute("aria-selected")} id={t.get_attribute("id")}')

    panes = drawer.locator('.el-tab-pane')
    print('pane 数量:', panes.count())
    for i in range(panes.count()):
        pn = panes.nth(i)
        box = pn.bounding_box()
        style = pn.get_attribute('style')
        shown = pn.is_visible()
        print(f'  pane[{i}] style={style!r} visible={shown} box={box} tbl_rows={pn.locator(".el-table__row").count()}')

    browser.close()
