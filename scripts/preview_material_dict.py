"""
中建材料字典独立预览服务（不并入系统，只读 gz 文件）

用法：
    python scripts/preview_material_dict.py

访问：
    http://127.0.0.1:8778/

功能：
    - 数据概览（总条数/来源/层级/根节点）
    - 树形结构浏览（按需加载子节点）
    - 全文搜索（名称/编码）
    - 与现有系统字典对比（可选）
"""
import gzip
import json
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# ============================================================
# 配置
# ============================================================
DATA_FILE = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\material_dict_cleaned\zhongjian_material_dict_v5.json.gz'
PORT = 8778
HOST = '127.0.0.1'

# ============================================================
# 数据加载与索引
# ============================================================
print('正在加载中建材料字典数据...')
with gzip.open(DATA_FILE, 'rt', encoding='utf-8') as f:
    ALL_ITEMS = json.load(f)
print(f'加载完成: {len(ALL_ITEMS):,} 条')

# 编码 → 记录 索引
CODE_INDEX = {item['编码']: item for item in ALL_ITEMS}

# 父编码 → 子节点列表 索引
CHILDREN_INDEX = {}
for item in ALL_ITEMS:
    parent = item.get('父编码', '')
    if parent:
        CHILDREN_INDEX.setdefault(parent, []).append(item)

# 根节点（层级4，无父编码）
ROOTS = [item for item in ALL_ITEMS if not item.get('父编码', '')]
ROOTS.sort(key=lambda x: x['编码'])

# 统计信息
STATS = {
    'total': len(ALL_ITEMS),
    'sources': {},
    'levels': {},
    'types': {},
    'roots': len(ROOTS),
    'leaf_count': sum(1 for item in ALL_ITEMS if item['编码'] not in CHILDREN_INDEX),
}
from collections import Counter
for item in ALL_ITEMS:
    STATS['sources'][item.get('来源', '')] = STATS['sources'].get(item.get('来源', ''), 0) + 1
    STATS['levels'][str(item.get('层级', ''))] = STATS['levels'].get(str(item.get('层级', '')), 0) + 1
    t = item.get('类型', '(无)')
    STATS['types'][t] = STATS['types'].get(t, 0) + 1

print(f'根节点: {len(ROOTS)} 个')
print(f'叶子节点: {STATS["leaf_count"]:,} 个')
print(f'预览服务: http://{HOST}:{PORT}/')


# ============================================================
# HTTP 请求处理
# ============================================================
class DictPreviewHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # 静默日志

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html):
        body = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == '/' or path == '/index.html':
            self._send_html(PAGE_HTML)
        elif path == '/api/stats':
            self._send_json(STATS)
        elif path == '/api/roots':
            self._send_json([self._node_with_children_count(r) for r in ROOTS])
        elif path == '/api/children':
            code = params.get('code', [''])[0]
            exclude_leaves = params.get('exclude_leaves', ['0'])[0] == '1'
            children = CHILDREN_INDEX.get(code, [])
            if exclude_leaves:
                # 只返回有子节点的分类节点（非叶子）
                children = [c for c in children if len(CHILDREN_INDEX.get(c['编码'], [])) > 0]
            self._send_json([self._node_with_children_count(c) for c in children])
        elif path == '/api/search':
            q = params.get('q', [''])[0].strip()
            limit = int(params.get('limit', ['100'])[0])
            results = self._search(q, limit)
            self._send_json({'query': q, 'total': len(results), 'results': results})
        elif path == '/api/item':
            code = params.get('code', [''])[0]
            item = CODE_INDEX.get(code)
            if item:
                # 构建面包屑路径
                breadcrumb = self._build_breadcrumb(code)
                self._send_json({'item': item, 'breadcrumb': breadcrumb})
            else:
                self._send_json({'error': 'not found'}, status=404)
        else:
            self._send_json({'error': 'not found'}, status=404)

    def _node_with_children_count(self, node):
        return {
            '编码': node['编码'],
            '名称': node['名称'],
            '层级': node.get('层级'),
            '类型': node.get('类型', ''),
            '来源': node.get('来源', ''),
            '父编码': node.get('父编码', ''),
            '单位': node.get('单位', ''),
            '型号': node.get('型号', ''),
            '规格': node.get('规格', ''),
            '材质': node.get('材质', ''),
            '备注': node.get('备注', ''),
            'child_count': len(CHILDREN_INDEX.get(node['编码'], [])),
        }

    def _build_breadcrumb(self, code):
        path = []
        current = CODE_INDEX.get(code)
        while current:
            path.insert(0, {'编码': current['编码'], '名称': current['名称']})
            parent = current.get('父编码', '')
            current = CODE_INDEX.get(parent) if parent else None
        return path

    def _search(self, q, limit=100):
        if not q:
            return []
        q_lower = q.lower()
        results = []
        for item in ALL_ITEMS:
            if q_lower in item['名称'].lower() or q_lower in item['编码'].lower():
                results.append(self._node_with_children_count(item))
                if len(results) >= limit:
                    break
        return results


# ============================================================
# 预览页面 HTML
# ============================================================
PAGE_HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>中建材料字典预览（14万条）</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #0f1117; color: #e0e0e0; }
  .header { background: linear-gradient(135deg, #1a1d29, #252a3a); padding: 20px 30px; border-bottom: 1px solid #333; display: flex; justify-content: space-between; align-items: center; }
  .header h1 { font-size: 20px; color: #fff; }
  .header h1 span { color: #4d7cfe; font-size: 14px; margin-left: 10px; }
  .badge { background: #4d7cfe; color: #fff; padding: 4px 12px; border-radius: 12px; font-size: 12px; }
  .container { display: flex; height: calc(100vh - 70px); }
  .sidebar { width: 380px; border-right: 1px solid #333; display: flex; flex-direction: column; background: #151820; }
  .search-box { padding: 15px; border-bottom: 1px solid #333; }
  .search-box input { width: 100%; padding: 10px 14px; background: #1e2230; border: 1px solid #333; border-radius: 6px; color: #fff; font-size: 14px; outline: none; }
  .search-box input:focus { border-color: #4d7cfe; }
  .search-result-info { padding: 8px 15px; font-size: 12px; color: #888; }
  .tree { flex: 1; overflow-y: auto; padding: 10px 0; }
  .tree-node { cursor: pointer; padding: 6px 15px; display: flex; align-items: center; gap: 8px; font-size: 13px; transition: background 0.15s; }
  .tree-node:hover { background: #1e2230; }
  .tree-node.active { background: rgba(77,124,254,0.15); border-left: 3px solid #4d7cfe; }
  .tree-node .toggle { width: 16px; text-align: center; color: #666; flex-shrink: 0; }
  .tree-node .toggle.has-children { color: #4d7cfe; }
  .tree-node .code { color: #888; font-family: monospace; font-size: 11px; flex-shrink: 0; }
  .tree-node .name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tree-node .count { color: #666; font-size: 11px; flex-shrink: 0; }
  .tree-children { display: none; }
  .tree-children.expanded { display: block; }
  .main { flex: 1; overflow-y: auto; padding: 25px 30px; }
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin-bottom: 25px; }
  .stat-card { background: #1a1d29; border: 1px solid #333; border-radius: 8px; padding: 18px; }
  .stat-card .label { font-size: 12px; color: #888; margin-bottom: 6px; }
  .stat-card .value { font-size: 24px; font-weight: 600; color: #fff; }
  .stat-card .value.blue { color: #4d7cfe; }
  .stat-card .value.green { color: #4caf50; }
  .stat-card .value.orange { color: #ff9800; }
  .section { background: #1a1d29; border: 1px solid #333; border-radius: 8px; padding: 20px; margin-bottom: 20px; }
  .section h2 { font-size: 16px; color: #fff; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 1px solid #333; }
  .breadcrumb { font-size: 13px; color: #888; margin-bottom: 15px; }
  .breadcrumb span { color: #4d7cfe; cursor: pointer; }
  .breadcrumb span:hover { text-decoration: underline; }
  .detail-grid { display: grid; grid-template-columns: 120px 1fr; gap: 10px 20px; font-size: 14px; }
  .detail-grid .key { color: #888; }
  .detail-grid .val { color: #fff; }
  .children-table { width: 100%; border-collapse: collapse; margin-top: 15px; }
  .children-table th { text-align: left; padding: 10px; background: #1e2230; color: #888; font-size: 12px; font-weight: 500; border-bottom: 1px solid #333; }
  .children-table td { padding: 10px; border-bottom: 1px solid #252a3a; font-size: 13px; cursor: pointer; }
  .children-table tr:hover { background: #1e2230; }
  .children-table .code { color: #4d7cfe; font-family: monospace; }
  .tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
  .tag.consumable { background: rgba(76,175,80,0.15); color: #4caf50; }
  .tag.reusable { background: rgba(255,152,0,0.15); color: #ff9800; }
  .tag.concrete { background: rgba(77,124,254,0.15); color: #4d7cfe; }
  .empty { text-align: center; padding: 60px 20px; color: #666; }
  .empty .icon { font-size: 48px; margin-bottom: 15px; opacity: 0.3; }
  .loading { text-align: center; padding: 20px; color: #666; font-size: 13px; }
  .source-bar { display: flex; height: 24px; border-radius: 4px; overflow: hidden; margin-top: 8px; }
  .source-bar div { display: flex; align-items: center; justify-content: center; font-size: 11px; color: #fff; }
</style>
</head>
<body>
<div class="header">
  <h1>中建材料字典预览 <span>独立预览 · 不并入系统 · 只读</span></h1>
  <span class="badge" id="totalBadge">加载中...</span>
</div>
<div class="container">
  <div class="sidebar">
    <div class="search-box">
      <input type="text" id="searchInput" placeholder="搜索名称或编码（如：电缆、I110）..." />
    </div>
    <div class="search-result-info" id="searchInfo"></div>
    <div class="tree" id="tree"></div>
  </div>
  <div class="main" id="main">
    <div class="loading">正在加载数据概览...</div>
  </div>
</div>

<script>
let stats = null;
let expandedNodes = new Set();
let activeCode = null;

async function api(url) {
  const r = await fetch(url);
  return r.json();
}

async function init() {
  stats = await api('/api/stats');
  document.getElementById('totalBadge').textContent = stats.total.toLocaleString() + ' 条';
  renderOverview();
  const roots = await api('/api/roots');
  renderTree(roots, 0);
}

function renderOverview() {
  const main = document.getElementById('main');
  const sources = Object.entries(stats.sources).sort((a,b) => b[1]-a[1]);
  const levels = Object.entries(stats.levels).sort((a,b) => parseInt(a[0])-parseInt(b[0]));
  const types = Object.entries(stats.types).sort((a,b) => b[1]-a[1]);
  const colors = ['#4d7cfe', '#4caf50', '#ff9800', '#9c27b0', '#00bcd4'];

  let html = `
    <div class="stats-grid">
      <div class="stat-card"><div class="label">总记录数</div><div class="value blue">${stats.total.toLocaleString()}</div></div>
      <div class="stat-card"><div class="label">根节点（大类）</div><div class="value green">${stats.roots}</div></div>
      <div class="stat-card"><div class="label">叶子节点（明细）</div><div class="value orange">${stats.leaf_count.toLocaleString()}</div></div>
      <div class="stat-card"><div class="label">数据来源</div><div class="value">${sources.length}</div></div>
    </div>

    <div class="section">
      <h2>数据来源分布</h2>
      <div class="source-bar">
        ${sources.map((s,i) => `<div style="width:${(s[1]/stats.total*100).toFixed(1)}%;background:${colors[i%colors.length]}" title="${s[0]}: ${s[1].toLocaleString()} (${(s[1]/stats.total*100).toFixed(1)}%)">${(s[1]/stats.total*100)>5 ? s[0] : ''}</div>`).join('')}
      </div>
      <div style="margin-top:10px;font-size:13px;color:#888;">
        ${sources.map((s,i) => `<span style="margin-right:20px;"><span style="display:inline-block;width:10px;height:10px;background:${colors[i%colors.length]};border-radius:2px;margin-right:6px;"></span>${s[0]}: ${s[1].toLocaleString()} (${(s[1]/stats.total*100).toFixed(1)}%)</span>`).join('')}
      </div>
    </div>

    <div class="section">
      <h2>层级分布</h2>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(100px,1fr));gap:10px;">
        ${levels.map(([l,c]) => `<div style="background:#1e2230;padding:12px;border-radius:6px;text-align:center;"><div style="font-size:20px;font-weight:600;color:#4d7cfe;">${c.toLocaleString()}</div><div style="font-size:11px;color:#888;margin-top:4px;">层级 ${l}</div></div>`).join('')}
      </div>
      <div style="margin-top:12px;font-size:12px;color:#666;">树形结构：层级4(根) → 层级6 → 层级8 → 层级11 → 层级13(叶子)，编码长度对应层级（4→6→8→11→13位）</div>
    </div>

    <div class="section">
      <h2>类型分布</h2>
      <div style="font-size:13px;">
        ${types.map(([t,c]) => `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #252a3a;"><span>${t}</span><span style="color:#4d7cfe;">${c.toLocaleString()}</span></div>`).join('')}
      </div>
    </div>

    <div class="section">
      <h2>39 个根节点（大类）</h2>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;">
        <div id="rootList"></div>
      </div>
    </div>
  `;
  main.innerHTML = html;
  loadRootsList();
}

async function loadRootsList() {
  const roots = await api('/api/roots');
  document.getElementById('rootList').outerHTML = roots.map(r =>
    `<div style="background:#1e2230;padding:10px;border-radius:6px;cursor:pointer;font-size:13px;" onclick="selectNode('${r.编码}')">
      <div style="color:#4d7cfe;font-family:monospace;font-size:11px;">${r.编码}</div>
      <div style="color:#fff;margin-top:4px;">${r.名称}</div>
      <div style="color:#666;font-size:11px;margin-top:4px;">${r.child_count.toLocaleString()} 个子类</div>
    </div>`
  ).join('');
}

function renderTree(nodes, level) {
  const tree = document.getElementById('tree');
  if (level === 0) tree.innerHTML = '';
  nodes.forEach(node => {
    const div = document.createElement('div');
    div.className = 'tree-node';
    div.dataset.code = node.编码;
    div.style.paddingLeft = (15 + level * 16) + 'px';
    const hasChildren = node.child_count > 0;
    div.innerHTML = `
      <span class="toggle ${hasChildren ? 'has-children' : ''}">${hasChildren ? '▶' : '·'}</span>
      <span class="code">${node.编码}</span>
      <span class="name">${node.名称}</span>
      ${hasChildren ? `<span class="count">${node.child_count}</span>` : ''}
    `;
    div.onclick = (e) => {
      e.stopPropagation();
      if (hasChildren) {
        toggleNode(node.编码, div, level);
      }
      selectNode(node.编码);
    };
    tree.appendChild(div);
    if (hasChildren) {
      const childrenDiv = document.createElement('div');
      childrenDiv.className = 'tree-children';
      childrenDiv.id = 'children-' + node.编码;
      tree.appendChild(childrenDiv);
    }
  });
}

async function toggleNode(code, nodeDiv, level) {
  const childrenDiv = document.getElementById('children-' + code);
  const toggle = nodeDiv.querySelector('.toggle');
  if (expandedNodes.has(code)) {
    expandedNodes.delete(code);
    childrenDiv.classList.remove('expanded');
    childrenDiv.innerHTML = '';
    toggle.textContent = '▶';
  } else {
    expandedNodes.add(code);
    toggle.textContent = '▼';
    childrenDiv.innerHTML = '<div class="loading">加载中...</div>';
    childrenDiv.classList.add('expanded');
    const children = await api('/api/children?code=' + code + '&exclude_leaves=1');
    childrenDiv.innerHTML = '';
    renderTreeInto(children, level + 1, childrenDiv);
  }
}

function renderTreeInto(nodes, level, container) {
  nodes.forEach(node => {
    const div = document.createElement('div');
    div.className = 'tree-node';
    div.style.paddingLeft = (15 + level * 16) + 'px';
    const hasChildren = node.child_count > 0;
    div.innerHTML = `
      <span class="toggle ${hasChildren ? 'has-children' : ''}">${hasChildren ? '▶' : '·'}</span>
      <span class="code">${node.编码}</span>
      <span class="name">${node.名称}</span>
      ${hasChildren ? `<span class="count">${node.child_count}</span>` : ''}
    `;
    div.onclick = (e) => {
      e.stopPropagation();
      if (hasChildren) toggleNode(node.编码, div, level);
      selectNode(node.编码);
    };
    container.appendChild(div);
    if (hasChildren) {
      const childrenDiv = document.createElement('div');
      childrenDiv.className = 'tree-children';
      childrenDiv.id = 'children-' + node.编码;
      container.appendChild(childrenDiv);
    }
  });
}

async function selectNode(code) {
  activeCode = code;
  document.querySelectorAll('.tree-node').forEach(n => n.classList.remove('active'));
  const nodeDiv = document.querySelector(`.tree-node[data-code="${code}"]`);
  if (nodeDiv) nodeDiv.classList.add('active');

  const data = await api('/api/item?code=' + code);
  const children = await api('/api/children?code=' + code);
  renderDetail(data, children);
}

function renderDetail(data, children) {
  const main = document.getElementById('main');
  const item = data.item;
  const bc = data.breadcrumb;
  const typeTag = item.类型 ? `<span class="tag ${item.类型==='消耗材料'?'consumable':item.类型==='周转材料'?'reusable':'concrete'}">${item.类型}</span>` : '';
  const isLeaf = children.length === 0;

  let html = `
    <div class="breadcrumb">
      ${bc.map((b,i) => `<span onclick="selectNode('${b.编码}')">${b.名称}</span>${i < bc.length-1 ? ' / ' : ''}`).join('')}
    </div>
    <div class="section">
      <h2>${item.名称} ${typeTag} ${isLeaf ? '<span class="tag concrete">叶子节点</span>' : ''}</h2>
      <div class="detail-grid">
        <div class="key">编码</div><div class="val" style="font-family:monospace;color:#4d7cfe;">${item.编码}</div>
        <div class="key">层级</div><div class="val">${item.层级}</div>
        <div class="key">来源</div><div class="val">${item.来源 || '-'}</div>
        <div class="key">父编码</div><div class="val" style="font-family:monospace;">${item.父编码 || '（根节点）'}</div>
        ${item.单位 ? `<div class="key">单位</div><div class="val">${item.单位}</div>` : ''}
        ${item.型号 ? `<div class="key">型号</div><div class="val">${item.型号}</div>` : ''}
        ${item.规格 ? `<div class="key">规格</div><div class="val" style="color:#4caf50;font-weight:600;">${item.规格}</div>` : ''}
        ${item.材质 ? `<div class="key">材质</div><div class="val">${item.材质}</div>` : ''}
        ${item.备注 ? `<div class="key">备注</div><div class="val">${item.备注}</div>` : ''}
        <div class="key">子节点数</div><div class="val">${children.length.toLocaleString()}</div>
      </div>
    </div>
  `;

  if (children.length > 0) {
    // 判断子节点是否有规格字段
    const hasSpec = children.some(c => c.规格);
    const hasModel = children.some(c => c.型号);
    const hasUnit = children.some(c => c.单位);
    const hasMaterial = children.some(c => c.材质);

    html += `
      <div class="section">
        <h2>子节点（${children.length.toLocaleString()} 个）</h2>
        <table class="children-table">
          <thead><tr>
            <th style="width:130px;">编码</th>
            <th>名称</th>
            ${hasSpec ? '<th style="width:120px;">规格</th>' : ''}
            ${hasModel ? '<th style="width:100px;">型号</th>' : ''}
            ${hasUnit ? '<th style="width:60px;">单位</th>' : ''}
            ${hasMaterial ? '<th style="width:80px;">材质</th>' : ''}
            <th style="width:60px;">层级</th>
            <th style="width:80px;">子节点</th>
          </tr></thead>
          <tbody>
            ${children.map(c => `<tr onclick="selectNode('${c.编码}')">
              <td class="code">${c.编码}</td>
              <td>${c.名称}</td>
              ${hasSpec ? `<td style="color:#4caf50;">${c.规格 || '-'}</td>` : ''}
              ${hasModel ? `<td>${c.型号 || '-'}</td>` : ''}
              ${hasUnit ? `<td>${c.单位 || '-'}</td>` : ''}
              ${hasMaterial ? `<td>${c.材质 || '-'}</td>` : ''}
              <td>${c.层级}</td>
              <td>${c.child_count > 0 ? c.child_count.toLocaleString() : '（叶子）'}</td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>
    `;
  } else {
    html += `<div class="section"><div class="empty"><div class="icon">📄</div><div>叶子节点 — 无下级子节点</div><div style="margin-top:10px;font-size:13px;color:#888;">规格: ${item.规格 || '无'} | 型号: ${item.型号 || '无'} | 单位: ${item.单位 || '无'} | 材质: ${item.材质 || '无'}</div></div></div>`;
  }

  main.innerHTML = html;
  main.scrollTop = 0;
}

// 搜索
let searchTimer = null;
document.getElementById('searchInput').addEventListener('input', (e) => {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  if (!q) {
    document.getElementById('searchInfo').textContent = '';
    init();
    return;
  }
  searchTimer = setTimeout(async () => {
    document.getElementById('searchInfo').textContent = '搜索中...';
    const data = await api('/api/search?q=' + encodeURIComponent(q) + '&limit=200');
    document.getElementById('searchInfo').textContent = `找到 ${data.total} 条（最多显示200条）`;
    const tree = document.getElementById('tree');
    tree.innerHTML = '';
    renderTreeInto(data.results, 0, tree);
  }, 300);
});

init();
</script>
</body>
</html>'''


# ============================================================
# 启动服务
# ============================================================
if __name__ == '__main__':
    server = HTTPServer((HOST, PORT), DictPreviewHandler)
    print(f'\n预览服务已启动: http://{HOST}:{PORT}/')
    print('按 Ctrl+C 停止服务')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n服务已停止')
        server.server_close()
