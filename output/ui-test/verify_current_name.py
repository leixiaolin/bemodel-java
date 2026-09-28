# 运行时验证：el-tabs 内部 currentName 是否被污染为对象
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

    page.locator('.el-table__body tr').first.click()
    page.wait_for_timeout(1500)

    result = page.evaluate("""() => {
        const el = document.querySelector('.el-drawer.open .el-tabs');
        if (!el) return 'no tabs el';
        let c = el.__vueParentComponent;
        while (c && c.type.name !== 'ElTabs') c = c.parent;
        if (!c || !c.exposed) return 'no ElTabs comp';
        const cn = c.exposed.currentName;
        const v = cn ? cn.value : '(none)';
        return typeof v === 'string' || typeof v === 'number'
            ? String(v) : 'NON-STRING: ' + Object.prototype.toString.call(v) + ' keys=' + Object.keys(v).slice(0,6).join(',');
    }""")
    print('ElTabs.currentName =', result)

    browser.close()
