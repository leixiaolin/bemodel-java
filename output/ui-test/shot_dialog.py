# -*- coding: utf-8 -*-
"""视口截图：新增数据源对话框打开 + 校验错误状态"""
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:5173'
SHOTS = Path(__file__).parent

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, channel='msedge')
    page = browser.new_page(viewport={'width': 1600, 'height': 1000})
    page.goto(BASE + '/login')
    page.wait_for_load_state('networkidle')
    page.get_by_placeholder('用户名').fill('admin')
    page.get_by_placeholder('密码').fill('admin123')
    page.get_by_role('button', name='登 录').click()
    page.wait_for_url(lambda u: '/login' not in str(u), timeout=10000)
    page.goto(BASE + '/datasource')
    page.wait_for_load_state('networkidle')
    page.wait_for_selector('.add-card', timeout=15000)

    page.locator('.add-card').click()
    dlg = page.locator('.el-dialog').filter(has_text='新增数据源').first
    dlg.wait_for(state='visible', timeout=5000)
    page.wait_for_timeout(300)
    page.screenshot(path=str(SHOTS / '07-dialog-filled.png'))  # 视口截图，含遮罩

    dlg.get_by_role('button', name='注册').click()
    page.wait_for_selector('.el-form-item__error', timeout=5000)
    page.wait_for_timeout(300)
    page.screenshot(path=str(SHOTS / '08-dialog-errors.png'))
    browser.close()
print('done')
