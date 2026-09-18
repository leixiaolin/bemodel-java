# -*- coding: utf-8 -*-
"""E2E：数据源绑定页「新增数据源」对话框（注册 / 连接测试 / 校验 / 角色 gating）

前置：前端 5173、后端 18080、MySQL 3306 均已运行。
测试数据 DS_E2E_TEST 指向现有 demo_his 库；结束后直接 SQL 清理平台库痕迹。
"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(r'D:\cursor_workspace\bemodel-java-main')
SHOTS = ROOT / 'output' / 'ui-test'
SHOTS.mkdir(parents=True, exist_ok=True)
BASE = 'http://127.0.0.1:5173'

env = {}
for line in (ROOT / 'bemodel-server-py' / '.env').read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip()

MYSQL_USER = env['MYSQL_USERNAME']
MYSQL_PASS = env['MYSQL_PASSWORD']

DS = dict(
    dsCode='DS_E2E_TEST',
    dsName='E2E测试库',
    productName='端到端测试',
    host='127.0.0.1',
    dbName='demo_his',
    username=MYSQL_USER,
)

results = []


def check(name, ok, detail=''):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} | {name} {detail}", flush=True)


def shot(page, name):
    page.screenshot(path=str(SHOTS / f'{name}.png'), full_page=True)


def msg_kind(page):
    msgs = page.locator('.el-message')
    if msgs.count() == 0:
        return None, ''
    last = msgs.nth(msgs.count() - 1)
    cls = last.get_attribute('class') or ''
    kind = ('success' if 'el-message--success' in cls else
            'warning' if 'el-message--warning' in cls else
            'error' if 'el-message--error' in cls else 'info')
    return kind, last.inner_text().strip()


def login(page, user, pwd):
    page.goto(BASE + '/login')
    page.wait_for_load_state('networkidle')
    page.get_by_placeholder('用户名').fill(user)
    page.get_by_placeholder('密码').fill(pwd)
    page.get_by_role('button', name='登 录').click()
    page.wait_for_url(lambda u: '/login' not in str(u), timeout=10000)
    page.wait_for_load_state('networkidle')


def fill_field(dlg, label, value):
    dlg.locator(f'.el-form-item:has(label:text-is("{label}")) input').first.fill(str(value))


with sync_playwright() as p:
    # 系统 Edge 作为 chromium 内核，免下载浏览器
    browser = p.chromium.launch(headless=True, channel='msedge')
    page = browser.new_page(viewport={'width': 1600, 'height': 1000})

    # ---------- admin：打开页面 ----------
    login(page, 'admin', 'admin123')
    page.goto(BASE + '/datasource')
    page.wait_for_load_state('networkidle')
    page.wait_for_selector('.ds-card', timeout=15000)
    check('admin 可见「新增数据源」卡片', page.locator('.add-card').count() == 1)
    shot(page, '01-ds-page-admin')

    # ---------- 打开对话框 + 空表单校验 ----------
    page.locator('.add-card').click()
    dlg = page.locator('.el-dialog').filter(has_text='新增数据源').first
    dlg.wait_for(state='visible', timeout=5000)
    shot(page, '02-dialog-open')

    dlg.get_by_role('button', name='注册').click()
    page.wait_for_selector('.el-form-item__error', timeout=5000)
    n_err = page.locator('.el-form-item__error:visible').count()
    # host 默认 127.0.0.1、端口默认 3306，空表单应命中其余 5 个必填项
    check('空表单校验拦截', n_err == 5, f'({n_err} 条必填提示)')
    shot(page, '03-validation')

    # ---------- 连接测试：错误密码 → 失败；正确密码 → 成功 ----------
    fill_field(dlg, '编码', DS['dsCode'])
    fill_field(dlg, '名称', DS['dsName'])
    fill_field(dlg, '产品线', DS['productName'])
    fill_field(dlg, '主机', DS['host'])
    fill_field(dlg, '数据库名', DS['dbName'])
    fill_field(dlg, '账号', DS['username'])
    fill_field(dlg, '密码', 'wrong_pw_e2e')

    dlg.get_by_role('button', name='测试连接').click()
    page.wait_for_selector('.el-message--warning', timeout=15000)
    kind, text = msg_kind(page)
    check('错误密码 → 连接失败提示', kind == 'warning' and '连接失败' in text, f'({text})')
    shot(page, '04-test-fail')

    fill_field(dlg, '密码', MYSQL_PASS)
    dlg.get_by_role('button', name='测试连接').click()
    page.wait_for_selector('.el-message--success', timeout=15000)
    kind, text = msg_kind(page)
    check('正确密码 → 连接成功提示', kind == 'success' and '连接成功' in text, f'({text})')

    # ---------- 注册 → 自动选中新卡片 → 自动扫描 ----------
    dlg.get_by_role('button', name='注册').click()
    page.wait_for_selector(f'.ds-card:has-text("{DS["dsName"]}")', timeout=15000)
    check('注册后新数据源卡片出现', True)

    page.wait_for_selector('.el-message:has-text("扫描完成")', timeout=30000)
    check('注册后自动扫描完成', True)
    page.wait_for_selector(
        f'.ds-card.active:has-text("{DS["dsName"]}")', timeout=10000)
    check('新数据源卡片被选中', True)
    page.wait_for_selector(
        '.el-card:has-text("物理表") .el-table__row', timeout=15000)
    shot(page, '05-registered-scanned')

    # ---------- 重复编码预检 ----------
    page.locator('.add-card').click()
    dlg = page.locator('.el-dialog').filter(has_text='新增数据源').first
    dlg.wait_for(state='visible', timeout=5000)
    fill_field(dlg, '编码', DS['dsCode'])
    fill_field(dlg, '名称', DS['dsName'])
    fill_field(dlg, '主机', DS['host'])
    fill_field(dlg, '数据库名', DS['dbName'])
    fill_field(dlg, '账号', DS['username'])
    fill_field(dlg, '密码', MYSQL_PASS)
    dlg.get_by_role('button', name='注册').click()
    page.wait_for_selector('.el-message--warning', timeout=10000)
    kind, text = msg_kind(page)
    check('重复编码前端预检', kind == 'warning' and '已存在' in text, f'({text})')
    page.keyboard.press('Escape')

    # ---------- viewer：无新增入口 ----------
    page.evaluate('localStorage.clear()')
    login(page, 'viewer', 'viewer123')
    page.goto(BASE + '/datasource')
    page.wait_for_load_state('networkidle')
    page.wait_for_selector('.ds-card', timeout=15000)
    check('viewer 不可见新增卡片', page.locator('.add-card').count() == 0)
    shot(page, '06-viewer')

    browser.close()

# ---------- 清理平台库测试痕迹 ----------
import pymysql

conn = pymysql.connect(
    host=env.get('MYSQL_HOST', '127.0.0.1'),
    port=int(env.get('MYSQL_PORT', '3306')),
    user=MYSQL_USER, password=MYSQL_PASS,
    database=env.get('MYSQL_DATABASE', 'bemodel_platform'), charset='utf8mb4')
try:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM bm_mapping WHERE ds_code='DS_E2E_TEST'")
        cur.execute("DELETE FROM bm_physical_column WHERE ds_code='DS_E2E_TEST'")
        cur.execute("DELETE FROM bm_physical_table WHERE ds_code='DS_E2E_TEST'")
        cur.execute("DELETE FROM bm_datasource WHERE ds_code='DS_E2E_TEST'")
    conn.commit()
    print('CLEANUP | DS_E2E_TEST 相关行已清理', flush=True)
finally:
    conn.close()

failed = [r for r in results if not r[1]]
print(f"\n=== {len(results) - len(failed)}/{len(results)} 通过 ===", flush=True)
sys.exit(1 if failed else 0)
