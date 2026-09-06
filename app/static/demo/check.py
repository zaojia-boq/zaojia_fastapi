#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
风格实验室 Demo 的静态自检（无需浏览器/依赖）
用法： python check.py
检查项：
  1. 内联 JS 语法（node --check）
  2. DOM 引用完整性（$('#id') 引用的 id 必须在 HTML 中存在）
  3. 页面路由一致性（nav data-page <-> #page-* 一一对应）
  4. 主题完整性（深空科技方案C token 完整）
  5. CSS 变量使用规范（禁止裸色值出现在 .card/.nav-item 等关键类的颜色属性上）
  6. 业务规则：清单编码前 9 位合规 + 特征列命名（项目特征描述，不用规格型号）
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(HERE, "index.html")
NODE = r"C:\Users\ht835\.workbuddy\binaries\node\versions\22.22.2-2\node.exe"

PAGES = ["dash", "boq", "price", "import", "batch", "dict", "match", "setting"]
THEMES = ["c"]  # 仅保留深空科技方案C
# 关键 token（每套主题都必须定义）
REQUIRED_TOKENS = [
    "--c-app-bg", "--c-side-bg", "--c-card", "--c-text", "--c-text-2",
    "--c-accent", "--c-ok", "--c-warn", "--c-err", "--r-lg", "--row-h",
]

errors, warns = [], []


def read():
    with open(HTML, encoding="utf-8") as f:
        return f.read()


def check_js(html):
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    if not scripts:
        errors.append("未找到内联 <script>")
        return
    if not os.path.exists(NODE):
        warns.append("未找到 node，跳过 JS 语法检查")
        return
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(scripts[-1])
        r = subprocess.run([NODE, "--check", path], capture_output=True, text=True)
        if r.returncode != 0:
            errors.append("JS 语法错误：\n" + (r.stderr or "")[:800])
    finally:
        os.unlink(path)


def check_dom_refs(html):
    ids = set(re.findall(r'id="([A-Za-z0-9_-]+)"', html))
    refs = set(re.findall(r"\$\('#([A-Za-z0-9_-]+)'\)", html))
    refs |= set(re.findall(r"querySelector\('#([A-Za-z0-9_-]+)'\)", html))
    missing = sorted(refs - ids)
    if missing:
        errors.append("JS 引用了不存在的 id：" + ", ".join(missing))


def check_routes(html):
    pages = set(re.findall(r'id="page-([a-z]+)"', html))
    navs = set(re.findall(r'data-page="([a-z]+)"', html))
    if navs - pages:
        errors.append("导航指向不存在的页面：" + ", ".join(sorted(navs - pages)))
    if pages - navs:
        errors.append("页面缺少导航入口：" + ", ".join(sorted(pages - navs)))
    for p in PAGES:
        if p not in pages:
            errors.append("缺少页面：" + p)


def check_themes(html):
    # 仅保留 C 深空科技方案，检查 data-theme="c" 块是否存在
    if 'data-theme="c"' not in html:
        errors.append("缺少主题 token 块：c")
        return
    block = re.search(r'\[data-theme="c"\]\{(.*?)\n\}', html, re.S)
    if not block:
        errors.append("缺少主题 token 块：c")
        return
    body = block.group(1)
    lack = [k for k in REQUIRED_TOKENS if k not in body]
    if lack:
        errors.append("主题 c 缺少 token：%s" % ", ".join(lack))


def check_no_bare_color(html):
    """关键组件类上不应出现裸颜色值（应走 token）"""
    css = re.search(r"<style>(.*?)</style>", html, re.S)
    if not css:
        return
    css = css.group(1)
    for sel in [".card{", ".nav-item{", ".kpi-val{", "thead th{", "tbody td{"]:
        i = css.find(sel)
        if i < 0:
            continue
        seg = css[i:i + 320]
        if re.search(r"(background|color)\s*:\s*#[0-9a-fA-F]{3,8}", seg):
            warns.append("疑似裸色值（建议走 token）：%s" % sel)


def check_codes(html):
    """业务规则：清单编码前 9 位必须是合规国标码（9 位纯数字）
    回归点：030228006（重整器）/ 030413010（小区路灯）曾误写成
    030228000 / 030413001（10 位错误码多了一个 0），此处断言不再回退。"""
    codes = re.findall(r"'(\d{12})','", html)
    if not codes:
        warns.append("未解析到 12 位清单编码，跳过编码校验")
        return
    bad = [c for c in codes if not re.match(r"^\d{9}\d{3}$", c)]
    if bad:
        errors.append("编码不是 12 位数字：" + ", ".join(bad[:5]))
        return
    prefix9 = {c[:9] for c in codes}
    wrong = [p for p in prefix9 if not re.match(r"^\d{9}$", p)]
    if wrong:
        errors.append("前 9 位非法：" + ", ".join(wrong[:5]))
    for must in ["030228006", "030413010"]:
        if must not in prefix9:
            errors.append("缺少已知易错规范码前缀 %s（前 9 位集合：%s）"
                          % (must, ", ".join(sorted(prefix9)[:8])))
    # 10 位错误码多了一个 0 的情况，给出正确写法
    fix = {"030228000": "030228006", "030413001": "030413010"}
    for forbidden, right in fix.items():
        if forbidden in prefix9:
            errors.append("出现已确认的错误编码前缀 %s，正确应为 %s" % (forbidden, right))


def check_feature_column(html):
    """业务规则：清单表特征列统一叫「项目特征描述」（国标正式列名），不用「规格型号」。

    回归点（2026-09-02）：检索结果表头曾写作「规格型号」，且导入列映射把源表头
    「规格型号」映射到了系统里并不存在的 `spec` 字段。现规定：
      - 界面表头必须是「项目特征描述」；
      - 「规格型号」只作为 item_feature 的别名出现在导入映射的「源表头」位置，
        其目标字段必须是 item_feature，不得是 spec（M3 §14.1 命名约定）。
    """
    if "<th>规格型号</th>" in html:
        errors.append('表头仍写作「规格型号」，应为「项目特征描述」')
    if "<th>项目特征描述</th>" not in html:
        errors.append("未找到「项目特征描述」表头")

    blk = re.search(r"const MAP_ROWS\s*=\s*\[(.*?)\];", html, re.S)
    if not blk:
        warns.append("未找到 MAP_ROWS，跳过导入列映射校验")
        return
    rows = re.findall(r"\['([^']*)','([^']*)','([^']*)'\]", blk.group(1))
    if not rows:
        warns.append("MAP_ROWS 解析为空，跳过导入列映射校验")
        return
    pairs = {(src, tgt) for src, tgt, _ in rows}
    targets = {tgt for _, tgt, _ in rows}

    if "spec" in targets:
        errors.append("导入列映射指向了不存在的字段 `spec`，"
                      "「规格型号」应作为 item_feature 的别名映射到 item_feature")
    if ("规格型号", "item_feature") not in pairs:
        errors.append("导入列映射缺少「规格型号」→ item_feature 的别名映射")
    if ("项目特征描述", "item_feature") not in pairs:
        errors.append("导入列映射缺少「项目特征描述」→ item_feature 的主映射")


def main():
    if not os.path.exists(HTML):
        print("找不到 index.html")
        return 1
    html = read()
    check_js(html)
    check_dom_refs(html)
    check_routes(html)
    check_themes(html)
    check_codes(html)
    check_feature_column(html)
    check_no_bare_color(html)

    print("=" * 52)
    print("风格实验室 Demo 自检")
    print("=" * 52)
    print("页面数：%d    主题数：%d    文件大小：%.1f KB"
          % (len(re.findall(r'id="page-', html)), len(THEMES), len(html.encode("utf-8")) / 1024))
    if warns:
        print("\n[WARN] %d 项" % len(warns))
        for w in warns:
            print("  - " + w)
    if errors:
        print("\n[FAIL] %d 项" % len(errors))
        for e in errors:
            print("  - " + e)
        return 1
    print("\n[PASS] 全部检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
