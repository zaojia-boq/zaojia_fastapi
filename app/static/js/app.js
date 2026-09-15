/* =====================================================================
   造价数据库 · 前端交互（深空科技方案）
   ---------------------------------------------------------------------
   重要约定（数据禁编造铁律）：
   所有业务数据均由服务端（Jinja 模板 + app/services/page_services.py）
   渲染完成；本脚本「绝不注入或覆盖」服务端数据，只负责纯客户端交互增强
   与受控的后端调用（导入 / 批次生命周期）。

   交互范围：
     1. 主题切换与持久化（深空 / 浅色，首次访问跟随系统偏好）
     2. 分段控件（<button> 段）的选中态切换
     3. 上传区点击 / 拖拽高亮
     4. 物料字典树展开 / 收起（不重建树，只切换 .hide）
     5. 导入向导步骤条推进（纯 UI）
     6. 匹配确认分段筛选（本页即时过滤，不请求服务端）
     7. 导入向导真流程：上传 → 预览 → 执行入库（M2.6.4 / P1-1）
     8. 批次生命周期：软删 / 还原 / 硬删（M2.6.5 / P1-2）
   ===================================================================== */
(function () {
  'use strict';

  const $  = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  /* ===================== 令牌与 API 调用 ===================== */
  function getToken() {
    try {
      const l = localStorage.getItem('zj-token');
      if (l) return l;
    } catch (e) {}
    const m = document.cookie.match(/(?:^|;\s*)zj_token=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }
  function setToken(t) {
    try { localStorage.setItem('zj-token', t); } catch (e) {}
  }
  async function apiFetch(path, opts) {
    opts = opts || {};
    const headers = Object.assign({}, opts.headers || {});
    const token = getToken();
    if (token) headers['Authorization'] = 'Bearer ' + token;
    // 自动设置 Content-Type: application/json（当 body 是 JSON 字符串时）
    if (opts.body && typeof opts.body === 'string' && !headers['Content-Type']) {
      headers['Content-Type'] = 'application/json';
    }
    return fetch(path, Object.assign({}, opts, { headers }));
  }
  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function toast(msg, type) {
    const el = $('#batchToast') || $('#zjToast');
    if (!el) return;
    el.textContent = msg;
    el.className = 'toast ' + (type || '');
    el.classList.remove('hide');
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.add('hide'), 3200);
  }

  /* ===================== 主题 ===================== */
  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    const btn = $('#themeToggle');
    if (btn) btn.innerHTML = theme === 'light' ? '☀' : '☾';
    try { localStorage.setItem('zj-theme', theme); } catch (e) {}
  }
  function currentTheme() {
    return document.documentElement.getAttribute('data-theme') || 'dark';
  }
  function initTheme() {
    applyTheme(currentTheme());
    const btn = $('#themeToggle');
    if (btn) btn.addEventListener('click', () => {
      applyTheme(currentTheme() === 'light' ? 'dark' : 'light');
      syncSettingsMode();
    });
    const setMode = $('#setMode');
    if (setMode) {
      syncSettingsMode();
      setMode.addEventListener('click', e => {
        const b = e.target.closest('button[data-mode]');
        if (!b || b.disabled) return;
        applyTheme(b.dataset.mode || 'dark');
        syncSettingsMode();
      });
    }
    const setTheme = $('#setTheme');
    if (setTheme) {
      setTheme.addEventListener('change', () => {
        try { localStorage.setItem('zj-theme-variant', setTheme.value); } catch (e) {}
      });
    }
  }
  function syncSettingsMode() {
    const setMode = $('#setMode');
    if (!setMode) return;
    const t = currentTheme();
    $$('button', setMode).forEach(b => b.classList.toggle('on', b.dataset.mode === t));
  }

  /* ===================== 分段控件 ===================== */
  function bindSeg() {
    $$('.seg').forEach(seg => {
      if (!seg.querySelector('button')) return;
      seg.addEventListener('click', e => {
        const b = e.target.closest('button');
        if (!b || b.disabled) return;
        $$('button', seg).forEach(x => x.classList.remove('on'));
        b.classList.add('on');
      });
    });
  }

  /* ===================== 上传区高亮 ===================== */
  function bindDrop() {
    $$('.drop').forEach(d => {
      d.addEventListener('click', () => { d.style.borderColor = 'var(--c-accent)'; });
      d.addEventListener('dragover', e => { e.preventDefault(); d.classList.add('drag'); });
      d.addEventListener('dragleave', () => d.classList.remove('drag'));
      d.addEventListener('drop', e => { e.preventDefault(); d.classList.remove('drag'); });
    });
  }

  /* ===================== 物料字典树（懒加载+分页+缓存+搜索版） ===================== */
  function bindDictTree() {
    const tree = $('#dictTree');
    if (!tree) return;

    // 缓存：已加载的子节点 { nodeId: { page, data, loadedAll } }
    const cache = {};
    const PAGE_SIZE = 100;

    // 展开状态记忆（localStorage）
    const EXPANDED_KEY = 'dict_tree_expanded_v1';
    function getExpandedSet() {
      try { return new Set(JSON.parse(localStorage.getItem(EXPANDED_KEY) || '[]')); }
      catch (e) { return new Set(); }
    }
    function saveExpanded(id, expanded) {
      const set = getExpandedSet();
      const sid = String(id);
      if (expanded) set.add(sid); else set.delete(sid);
      try { localStorage.setItem(EXPANDED_KEY, JSON.stringify([...set])); } catch (e) {}
    }
    // 自动展开一个节点（若未加载则先加载，加载后递归展开其子节点中记忆的）
    async function autoExpandNode(nodeId) {
      const node = tree.querySelector('.tree-node[data-id="' + CSS.escape(nodeId) + '"]');
      if (!node) return;
      const caret = node.querySelector('.tree-caret');
      const children = tree.querySelector('.tree-children[data-children="' + CSS.escape(nodeId) + '"]');
      if (!children) return;
      if (node.dataset.loaded !== 'true') {
        const ok = await loadChildren(nodeId, children, caret, 1);
        if (!ok) return;
      }
      children.style.display = 'block';
      if (caret) { caret.textContent = '−'; caret.classList.add('open'); }
      // 递归展开子节点中记忆的
      const expandedSet = getExpandedSet();
      const childNodes = children.querySelectorAll(':scope > .tree-node:not(.load-more-node)');
      for (const cn of childNodes) {
        if (expandedSet.has(cn.dataset.id)) {
          await autoExpandNode(cn.dataset.id);
        }
      }
    }

    // 逐级展开一条祖先链（从 l1 到直接父节点），用于搜索后定位节点
    async function expandPath(ancestorIds) {
      for (const aid of ancestorIds) {
        const node = tree.querySelector('.tree-node[data-id="' + CSS.escape(aid) + '"]');
        if (!node) continue;
        const caret = node.querySelector('.tree-caret');
        const children = tree.querySelector('.tree-children[data-children="' + CSS.escape(aid) + '"]');
        if (!children) continue;
        if (node.dataset.loaded !== 'true') {
          await loadChildren(aid, children, caret, 1);
        }
        children.style.display = 'block';
        if (caret) { caret.textContent = '−'; caret.classList.add('open'); }
      }
    }

    // 清除搜索状态：恢复所有节点显示和原始文本
    function resetTreeDisplay() {
      const nodes = tree.querySelectorAll('.tree-node:not(.load-more-node)');
      nodes.forEach(node => {
        node.style.display = '';
        const a = node.querySelector('a');
        if (!a) return;
        const rawName = a.dataset.name || '';
        const codeEl = a.querySelector('span');
        const codeHtml = codeEl ? codeEl.outerHTML : '';
        a.innerHTML = codeHtml + escapeHtml(rawName);
      });
    }

    // 动态创建子节点HTML
    function createChildNode(child, parentDepth) {
      const depth = parentDepth + 1;
      const hasCaret = child.hasChild ? '+' : '';
      const caretClass = child.hasChild ? '' : '';
      const childrenContainer = child.hasChild
        ? '<div class="tree-children" data-children="' + child.id + '" style="display:none"></div>'
        : '';
      const codeHtml = child.code ? '<span style="color:#64748b;font-family:monospace;font-size:11px;margin-right:6px">' + escapeHtml(child.code) + '</span>' : '';
      return '' +
        '<div class="tree-node" data-id="' + child.id + '" data-level="' + child.level + '" data-loaded="false"' +
        ' style="padding-left:' + (8 + depth * 16) + 'px">' +
        '<span class="tree-caret ' + caretClass + '" data-caret="' + child.id + '">' + hasCaret + '</span>' +
        '<a href="/admin/dict?sel=' + child.id + '" data-name="' + escapeHtml(child.name) + '" style="color:inherit;text-decoration:none;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' +
        codeHtml + escapeHtml(child.name) + '</a></div>' + childrenContainer;
    }

    // 创建"加载更多"按钮
    function createLoadMoreBtn(nodeId, parentDepth, loadedCount, total) {
      const depth = parentDepth + 1;
      return '<div class="tree-node load-more-node" data-load-more="' + nodeId + '"' +
        ' style="padding-left:' + (8 + depth * 16) + 'px;cursor:pointer;color:#4D7CFE">' +
        '<span style="margin-right:8px">⤵</span>' +
        '<a style="color:#4D7CFE;text-decoration:none;flex:1">加载更多（已显示 ' + loadedCount + '/' + total + '）</a></div>';
    }

    // 懒加载子节点（支持分页）
    async function loadChildren(nodeId, childrenContainer, caret, page) {
      page = page || 1;
      try {
        if (caret) caret.textContent = '⟳'; // 加载中指示
        const resp = await apiFetch('/api/dict/children?parent_id=' + nodeId + '&page=' + page + '&page_size=' + PAGE_SIZE);
        if (!resp.ok) {
          if (caret) caret.textContent = '+';
          toast('加载子节点失败', 'err');
          return false;
        }
        const data = await resp.json();
        const node = tree.querySelector('.tree-node[data-id="' + CSS.escape(nodeId) + '"]');
        const depth = node ? parseInt(node.style.paddingLeft) || 8 : 8;
        const parentDepth = Math.floor((depth - 8) / 16);

        // 更新缓存
        if (!cache[nodeId]) {
          cache[nodeId] = { page: 0, data: [], loadedAll: false, total: data.total };
        }
        cache[nodeId].page = page;
        cache[nodeId].total = data.total;
        cache[nodeId].loadedAll = !data.has_more;
        cache[nodeId].data = cache[nodeId].data.concat(data.children);

        // 渲染（第一页替换，后续追加）
        if (page === 1) {
          if (data.children && data.children.length > 0) {
            childrenContainer.innerHTML = data.children.map(c => createChildNode(c, parentDepth)).join('');
          } else {
            childrenContainer.innerHTML = '<div class="muted small" style="padding-left:' + (8 + (parentDepth + 1) * 16) + 'px">（无子节点）</div>';
          }
        } else {
          // 移除旧的"加载更多"按钮
          const oldBtn = childrenContainer.querySelector('[data-load-more]');
          if (oldBtn) oldBtn.remove();
          // 追加新节点
          const html = data.children.map(c => createChildNode(c, parentDepth)).join('');
          childrenContainer.insertAdjacentHTML('beforeend', html);
        }

        // 如果还有更多，添加"加载更多"按钮
        if (data.has_more) {
          const loadedCount = cache[nodeId].data.length;
          childrenContainer.insertAdjacentHTML('beforeend', createLoadMoreBtn(nodeId, parentDepth, loadedCount, data.total));
        }

        // 标记为已加载（至少第一页已加载）
        if (node && page === 1) node.dataset.loaded = 'true';
        if (caret) caret.textContent = '+';
        return true;
      } catch (e) {
        if (caret) caret.textContent = '+';
        toast('加载子节点异常: ' + e.message, 'err');
        return false;
      }
    }

    // 树点击事件（展开/收起 + 加载更多）
    tree.addEventListener('click', async e => {
      // 处理"加载更多"按钮
      const loadMoreBtn = e.target.closest('[data-load-more]');
      if (loadMoreBtn) {
        const nodeId = loadMoreBtn.dataset.loadMore;
        const children = tree.querySelector('.tree-children[data-children="' + CSS.escape(nodeId) + '"]');
        if (!children) return;
        const cached = cache[nodeId];
        const nextPage = cached ? cached.page + 1 : 2;
        await loadChildren(nodeId, children, null, nextPage);
        return;
      }

      // 处理展开/收起
      const caret = e.target.closest('.tree-caret[data-caret]');
      if (!caret) return;
      const id = caret.dataset.caret;
      const children = tree.querySelector('.tree-children[data-children="' + CSS.escape(id) + '"]');
      if (!children) return;

      const node = tree.querySelector('.tree-node[data-id="' + CSS.escape(id) + '"]');
      const loaded = node ? node.dataset.loaded === 'true' : false;

      // 如果未加载，先懒加载
      if (!loaded) {
        const ok = await loadChildren(id, children, caret, 1);
        if (!ok) return;
      }

      // 展开/收起
      const isHidden = children.style.display === 'none' || children.style.display === '';
      children.style.display = isHidden ? 'block' : 'none';
      caret.textContent = isHidden ? '−' : '+';
      caret.classList.toggle('open', isHidden);
      saveExpanded(id, isHidden);
    });

    // 全局搜索（后端 API）+ 自动展开祖先链 + 关键词高亮
    const searchInput = $('#dictTreeSearch');
    if (searchInput) {
      let searchTimer = null;
      let searchAbort = null;

      // 前端降级搜索（仅已加载节点）
      function fallbackFrontendSearch(keyword) {
        const kw = keyword.toLowerCase();
        const nodes = tree.querySelectorAll('.tree-node:not(.load-more-node)');
        nodes.forEach(node => {
          const a = node.querySelector('a');
          if (!a) return;
          const rawName = a.dataset.name || '';
          const codeEl = a.querySelector('span');
          const codeHtml = codeEl ? codeEl.outerHTML : '';
          if (!kw || rawName.toLowerCase().includes(kw)) {
            node.style.display = '';
            if (kw) {
              const idx = rawName.toLowerCase().indexOf(kw);
              a.innerHTML = codeHtml + escapeHtml(rawName.substring(0, idx)) +
                '<span class="tree-hl">' + escapeHtml(rawName.substring(idx, idx + kw.length)) + '</span>' +
                escapeHtml(rawName.substring(idx + kw.length));
            } else {
              a.innerHTML = codeHtml + escapeHtml(rawName);
            }
          } else {
            node.style.display = 'none';
            a.innerHTML = codeHtml + escapeHtml(rawName);
          }
        });
      }

      searchInput.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(async () => {
          const keyword = searchInput.value.trim();
          if (!keyword) {
            resetTreeDisplay();
            return;
          }
          // 取消上一次搜索
          if (searchAbort) searchAbort.abort();
          searchAbort = new AbortController();

          try {
            const resp = await apiFetch('/api/dict/search?keyword=' +
              encodeURIComponent(keyword) + '&limit=50', { signal: searchAbort.signal });
            if (!resp.ok) { fallbackFrontendSearch(keyword); return; }
            const data = await resp.json();
            const matches = data.matches || [];

            if (matches.length === 0) {
              resetTreeDisplay();
              // 隐藏所有节点（提示无结果）
              tree.querySelectorAll('.tree-node:not(.load-more-node)').forEach(n => n.style.display = 'none');
              return;
            }

            // 收集匹配节点 ID 和祖先 ID
            const matchIds = new Set();
            const visibleIds = new Set();
            for (const m of matches) {
              matchIds.add(String(m.id));
              visibleIds.add(String(m.id));
              for (const aid of (m.ancestor_ids || [])) visibleIds.add(String(aid));
            }

            // 逐级展开所有匹配节点的祖先链（去重）
            const allChains = [];
            const seenChain = new Set();
            for (const m of matches) {
              const key = (m.ancestor_ids || []).join(',');
              if (!seenChain.has(key)) {
                seenChain.add(key);
                allChains.push(m.ancestor_ids || []);
              }
            }
            for (const chain of allChains) {
              await expandPath(chain);
            }

            // 过滤显示 + 高亮
            const allNodes = tree.querySelectorAll('.tree-node:not(.load-more-node)');
            allNodes.forEach(node => {
              const nid = node.dataset.id;
              const a = node.querySelector('a');
              if (!a) return;
              const rawName = a.dataset.name || '';
              const codeEl = a.querySelector('span');
              const codeHtml = codeEl ? codeEl.outerHTML : '';

              if (matchIds.has(nid)) {
                node.style.display = '';
                const idx = rawName.toLowerCase().indexOf(keyword.toLowerCase());
                if (idx >= 0) {
                  a.innerHTML = codeHtml + escapeHtml(rawName.substring(0, idx)) +
                    '<span class="tree-hl">' + escapeHtml(rawName.substring(idx, idx + keyword.length)) + '</span>' +
                    escapeHtml(rawName.substring(idx + keyword.length));
                } else {
                  a.innerHTML = codeHtml + escapeHtml(rawName);
                }
              } else if (visibleIds.has(nid)) {
                node.style.display = '';
                a.innerHTML = codeHtml + escapeHtml(rawName);
              } else {
                node.style.display = 'none';
                a.innerHTML = codeHtml + escapeHtml(rawName);
              }
            });

            // 滚动到第一个匹配节点
            const firstHL = tree.querySelector('.tree-hl');
            if (firstHL) {
              firstHL.closest('.tree-node').scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
          } catch (e) {
            if (e.name !== 'AbortError') fallbackFrontendSearch(keyword);
          }
        }, 300);
      });
    }

    // 页面加载时恢复展开状态（初始 l1 节点中记忆的自动展开，递归到深层）
    const expandedSet = getExpandedSet();
    tree.querySelectorAll(':scope > .tree-node').forEach(l1Node => {
      if (expandedSet.has(l1Node.dataset.id)) {
        autoExpandNode(l1Node.dataset.id);
      }
    });
  }

  /* ===================== 导入向导步骤条 ===================== */
  function bindImportWizard() {
    const steps = $$('#impSteps .step');
    const lines = $$('#impSteps .step-line');
    const next = $('#impNext');
    const prev = $('#impPrev');
    if (!steps.length) return;

    const panes = $$('.imp-pane');
    let cur = Math.max(0, steps.findIndex(s => s.classList.contains('on')));
    if (cur < 0) cur = 0;

    const apply = (idx) => {
      cur = Math.max(0, Math.min(idx, steps.length - 1));
      steps.forEach((s, i) => { s.classList.toggle('done', i < cur); s.classList.toggle('on', i === cur); });
      lines.forEach((l, i) => l.classList.toggle('done', i < cur));
      panes.forEach((p, i) => p.classList.toggle('hide', i !== cur));
    };

    // 按钮在模板中初始 disabled；上传成功后由导入流程启用（纯 UI）
    if (next) next.addEventListener('click', () => apply(cur + 1));
    if (prev) prev.addEventListener('click', () => apply(cur - 1));
  }

  /* ===================== 导入向导真流程（M2.6.4 / P1-1） ===================== */
  function bindImportFlow() {
    const fileInput = $('#impFile');
    const drop = $('#impDrop');
    if (!fileInput || !drop) return;

    drop.addEventListener('click', () => fileInput.click());
    drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drag'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('drag'));
    drop.addEventListener('drop', e => {
      e.preventDefault(); drop.classList.remove('drag');
      if (e.dataTransfer.files && e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]);
    });
    fileInput.addEventListener('change', () => {
      if (fileInput.files && fileInput.files[0]) uploadFile(fileInput.files[0]);
    });

    // 令牌：优先用输入框（并持久化到 localStorage 供后续 fetch 复用）
    const tokenInput = $('#impToken');
    if (tokenInput) {
      const existing = getToken();
      if (existing) tokenInput.value = existing;
      tokenInput.addEventListener('change', () => {
        if (tokenInput.value.trim()) setToken(tokenInput.value.trim());
      });
    }

    const exec = $('#impExecute');
    if (exec) exec.addEventListener('click', doExecute);
  }

  function showFileInfo(html) {
    const el = $('#impFileInfo');
    if (el) el.innerHTML = html;
  }

  async function uploadFile(file) {
    const tokenInput = $('#impToken');
    if (tokenInput && tokenInput.value.trim()) setToken(tokenInput.value.trim());

    const fd = new FormData();
    fd.append('file', file);
    showFileInfo('正在解析 <b>' + escapeHtml(file.name) + '</b> …');

    let resp;
    try {
      resp = await apiFetch('/api/import/upload', { method: 'POST', body: fd });
    } catch (e) {
      showFileInfo('网络错误：' + escapeHtml(e.message));
      return;
    }
    if (resp.status === 401) {
      showFileInfo('未授权（401）：请在下方填写开发令牌后重试');
      toast('未授权：请先填写开发令牌', 'err');
      return;
    }
    if (!resp.ok) {
      const t = await resp.text().catch(() => '');
      showFileInfo('解析失败：' + escapeHtml(t.slice(0, 240)));
      return;
    }

    const data = await resp.json().catch(() => null);
    if (!data) { showFileInfo('解析响应异常'); return; }

    // 暂存上传产物，供步骤 5 执行入库使用
    window.__impFile = {
      file_token: data.file_token,
      tmp_path: data.tmp_path,
      filename: data.filename,
      sheet_name: data.sheet_name,
      headers: data.headers || [],
      auto_mapping: data.field_mapping || {},
      rows: data.rows || [],
    };
    window.__impMapping = Object.assign({}, data.field_mapping || {});

    showFileInfo(
      '<div class="stat-line"><span>文件</span><b>' + escapeHtml(data.filename || file.name) + '</b></div>' +
      '<div class="stat-line"><span>工作表</span><b>' + escapeHtml(data.sheet_name || '—') + '</b></div>' +
      '<div class="stat-line"><span>文件类型</span><b class="mono">' + escapeHtml(data.file_type || 'xlsx') + '</b></div>' +
      '<div class="stat-line"><span>解析行数</span><b class="mono">' + (data.row_count || 0) + '</b></div>'
    );

    // M2 深化：模板自动匹配 — 如果有推荐模板，自动应用并提示
    if (data.recommended_template) {
      const tpl = data.recommended_template;
      if (tpl.mapping && Object.keys(tpl.mapping).length > 0) {
        window.__impMapping = Object.assign({}, tpl.mapping);
        window.__impFile.auto_mapping = Object.assign({}, tpl.mapping);
        toast('已自动应用推荐模板「' + tpl.name + '」（相似度 ' + tpl.similarity + '）', 'ok');
      }
    }

    renderMapping(data);
    renderPreview(data);
    renderValidation(data);

    const next = $('#impNext'); if (next) next.disabled = false;
    const exec = $('#impExecute'); if (exec) { exec.disabled = false; exec.textContent = '执行入库'; }
    toast('解析完成，请继续配置后执行入库', 'ok');
  }

  // M2 深化：标准字段列表（用于映射下拉框）
  let __standardFields = [];
  let __templateList = [];

  // 页面加载时获取标准字段和模板列表
  async function initMappingData() {
    try {
      const [fieldsResp, tplResp] = await Promise.all([
        apiFetch('/api/import/standard-fields'),
        apiFetch('/api/import/templates'),
      ]);
      if (fieldsResp.ok) {
        const data = await fieldsResp.json();
        __standardFields = data.fields || [];
      }
      if (tplResp.ok) {
        const data = await tplResp.json();
        __templateList = data.templates || [];
        updateTemplateSelect();
      }
    } catch (e) {
      console.warn('获取映射数据失败:', e);
    }
  }

  function updateTemplateSelect() {
    const sel = $('#impTplLoad');
    if (!sel) return;
    sel.innerHTML = '<option value="">— 选择模板 —</option>';
    for (const tpl of __templateList) {
      const opt = document.createElement('option');
      opt.value = tpl.name;
      opt.textContent = tpl.name + (tpl.description ? ' — ' + tpl.description : '');
      sel.appendChild(opt);
    }
  }

  function renderMapping(data) {
    const box = $('#impMapping');
    const count = $('#impMapCount');
    const tplBar = $('#impTemplateBar');
    const mapNote = $('#impMapNote');
    if (!box) return;

    const headers = data.headers || [];
    const mapping = data.field_mapping || {};

    if (tplBar) tplBar.style.display = 'block';
    if (mapNote) mapNote.style.display = 'block';

    // 渲染可编辑映射表格
    let html = '<table class="data-table" style="width:100%;font-size:13px"><thead><tr>' +
      '<th style="text-align:left;padding:6px 8px;border-bottom:1px solid #e5e7eb">原始列名</th>' +
      '<th style="text-align:left;padding:6px 8px;border-bottom:1px solid #e5e7eb">映射到标准字段</th>' +
      '<th style="text-align:left;padding:6px 8px;border-bottom:1px solid #e5e7eb">示例值</th>' +
      '</tr></thead><tbody>';

    for (let i = 0; i < headers.length; i++) {
      const header = headers[i] || '';
      if (!header.trim()) continue;
      const currentField = mapping[header] || '';
      // 取第一行的示例值
      const sampleVal = (data.rows && data.rows[0] && data.rows[0][i] !== undefined) ? String(data.rows[0][i]).slice(0, 30) : '';

      html += '<tr>' +
        '<td style="padding:6px 8px;border-bottom:1px solid #f3f4f6;font-family:monospace">' + escapeHtml(header) + '</td>' +
        '<td style="padding:4px 8px;border-bottom:1px solid #f3f4f6">' +
        '<select class="inp map-field-select" data-header="' + escapeHtml(header) + '" style="width:100%;padding:4px 8px;font-size:13px" onchange="updateFieldMapping(this)">' +
        '<option value="">— 不映射 —</option>';
      for (const f of __standardFields) {
        const selected = currentField === f.name ? 'selected' : '';
        const reqMark = f.required ? ' *' : '';
        html += '<option value="' + f.name + '" ' + selected + '>' + f.label + reqMark + ' (' + f.type + ')</option>';
      }
      html += '</select></td>' +
        '<td style="padding:6px 8px;border-bottom:1px solid #f3f4f6;color:#6b7280;font-size:12px">' + escapeHtml(sampleVal) + '</td>' +
        '</tr>';
    }
    html += '</tbody></table>';

    // 未识别列提示
    const unrec = (data.unrecognized_columns || []);
    if (unrec.length) {
      html += '<div class="note mt"><span>ⓘ</span><div>未自动识别列：' + escapeHtml(unrec.join('、')) + '，请手动选择映射字段或忽略。</div></div>';
    }

    box.innerHTML = html;
    if (count) count.textContent = (data.row_count || 0) + ' 行';

    // 保存当前映射到全局变量
    window.__impMapping = Object.assign({}, mapping);
  }

  // 更新单个字段映射
  function updateFieldMapping(selectEl) {
    const header = selectEl.dataset.header;
    const field = selectEl.value;
    if (!window.__impMapping) window.__impMapping = {};
    if (field) {
      window.__impMapping[header] = field;
    } else {
      delete window.__impMapping[header];
    }
  }

  // 保存映射模板
  async function saveMappingTemplate() {
    const nameEl = $('#impTplName');
    const name = nameEl ? nameEl.value.trim() : '';
    if (!name) { toast('请输入模板名称', 'err'); return; }
    if (!window.__impMapping || Object.keys(window.__impMapping).length === 0) {
      toast('没有可保存的映射', 'err'); return;
    }

    const headers = window.__impFile ? (window.__impFile.headers || []) : [];
    try {
      const resp = await apiFetch('/api/import/templates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name,
          mapping: window.__impMapping,
          headers: headers,
          description: '用户手动保存的字段映射模板',
        }),
      });
      if (resp.ok) {
        toast('模板「' + name + '」已保存', 'ok');
        // 刷新模板列表
        const tplResp = await apiFetch('/api/import/templates');
        if (tplResp.ok) {
          const data = await tplResp.json();
          __templateList = data.templates || [];
          updateTemplateSelect();
        }
      } else {
        const err = await resp.text().catch(() => '');
        toast('保存失败：' + err.slice(0, 100), 'err');
      }
    } catch (e) {
      toast('保存失败：' + e.message, 'err');
    }
  }

  // 加载映射模板
  async function loadMappingTemplate(name) {
    if (!name) return;
    try {
      const resp = await apiFetch('/api/import/templates/' + encodeURIComponent(name));
      if (resp.ok) {
        const tpl = await resp.json();
        if (tpl.mapping) {
          window.__impMapping = Object.assign({}, tpl.mapping);
          // 更新下拉框选中状态
          const selects = document.querySelectorAll('.map-field-select');
          for (const sel of selects) {
            const header = sel.dataset.header;
            sel.value = tpl.mapping[header] || '';
          }
          toast('模板「' + name + '」已加载', 'ok');
        }
      } else {
        toast('加载模板失败', 'err');
      }
    } catch (e) {
      toast('加载失败：' + e.message, 'err');
    }
  }

  // 重置为自动映射
  function resetMappingToAuto() {
    if (window.__impFile && window.__impFile.auto_mapping) {
      window.__impMapping = Object.assign({}, window.__impFile.auto_mapping);
      const selects = document.querySelectorAll('.map-field-select');
      for (const sel of selects) {
        const header = sel.dataset.header;
        sel.value = window.__impMapping[header] || '';
      }
      toast('已重置为自动映射', 'ok');
    }
  }

  function renderPreview(data) {
    const box = $('#impPreview');
    const count = $('#impPreviewCount');
    if (!box) return;
    box.innerHTML =
      '<div class="stat-line"><span class="muted">识别行数</span><b class="mono">' + (data.row_count || 0) + '</b></div>' +
      '<div class="stat-line"><span class="muted">跳过行</span><b class="mono">' + (data.skipped_count || 0) + '</b></div>' +
      '<div class="stat-line"><span class="muted">异常行</span><b class="mono">' + (data.anomaly_count || 0) + '</b></div>' +
      '<div class="stat-line"><span class="muted">解析合计</span><b class="mono">' + (data.parsed_total || 0) + '</b></div>';
    if (count) count.textContent = (data.row_count || 0) + ' 行';
  }

  // M2 深化：渲染数据质量校验报告
  function renderValidation(data) {
    const box = $('#impValidation');
    if (!box) return;
    const val = data.validation;
    if (!val) { box.style.display = 'none'; return; }

    box.style.display = 'block';

    // 状态标签
    const statusEl = $('#impValidationStatus');
    if (statusEl) {
      if (val.can_import) {
        statusEl.textContent = '✓ 可导入';
        statusEl.style.color = '#059669';
      } else {
        statusEl.textContent = '✗ 阻断导入';
        statusEl.style.color = '#dc2626';
      }
    }

    // 统计数字
    const errEl = $('#impValError');
    const warnEl = $('#impValWarning');
    const validEl = $('#impValValid');
    if (errEl) errEl.textContent = val.error_count || 0;
    if (warnEl) warnEl.textContent = val.warning_count || 0;
    if (validEl) validEl.textContent = (val.valid_rows || 0) + ' / ' + (val.total_rows || 0);

    // 明细
    const detailBox = $('#impValidationDetail');
    const resultsBox = $('#impValidationResults');
    const toggleBtn = $('#impValToggle');
    const results = val.results || [];

    if (results.length > 0 && resultsBox) {
      let html = '';
      for (const r of results.slice(0, 50)) {
        const color = r.level === 'error' ? '#dc2626' : (r.level === 'warning' ? '#d97706' : '#6b7280');
        const label = r.level === 'error' ? '错误' : (r.level === 'warning' ? '警告' : '信息');
        html += '<div style="padding:4px 0;border-bottom:1px solid #f3f4f6">' +
          '<span style="color:' + color + ';font-weight:600;margin-right:6px">[' + label + ']</span>' +
          '<span class="muted">第 ' + (r.row_index + 1) + '行 · ' + escapeHtml(r.field || '') + '：</span>' +
          escapeHtml(r.message || '') +
          '</div>';
      }
      if (results.length > 50) {
        html += '<div class="muted small mt" style="padding:4px 0">仅显示前 50 条，共 ' + results.length + ' 条</div>';
      }
      resultsBox.innerHTML = html;
      if (detailBox) detailBox.style.display = 'none';
      if (toggleBtn) {
        toggleBtn.style.display = 'inline-block';
        toggleBtn.textContent = '展开明细';
      }
    } else {
      if (resultsBox) resultsBox.innerHTML = '<div class="muted small" style="padding:8px 0">无校验问题</div>';
      if (detailBox) detailBox.style.display = 'none';
      if (toggleBtn) toggleBtn.style.display = 'none';
    }

    // 如果有错误，禁用执行按钮
    const exec = $('#impExecute');
    if (exec && !val.can_import) {
      exec.disabled = true;
      exec.textContent = '存在错误，无法导入';
      toast('数据校验未通过，请修正后重试', 'err');
    }
  }

  async function doExecute() {
    if (!window.__impFile) { toast('请先上传文件', 'err'); return; }
    const exec = $('#impExecute');
    const srcEl = document.querySelector('input[name="impSourceType"]:checked');
    const src = srcEl ? srcEl.value : 'completed';
    const province = $('#impProvince') ? $('#impProvince').value.trim() : '';
    const period = $('#impPeriod') ? $('#impPeriod').value.trim() : '';

    const fd = new FormData();
    fd.append('file_token', window.__impFile.file_token);
    fd.append('tmp_path', window.__impFile.tmp_path);
    fd.append('data_source_type', src);
    if (province) fd.append('province', province);
    if (period) fd.append('price_period', period);
    // M2 深化：传入用户调整后的字段映射
    if (window.__impMapping && Object.keys(window.__impMapping).length > 0) {
      fd.append('field_mapping', JSON.stringify(window.__impMapping));
    }

    if (exec) { exec.disabled = true; exec.textContent = '入库中…'; }
    let resp;
    try {
      resp = await apiFetch('/api/import/execute', { method: 'POST', body: fd });
    } catch (e) {
      toast('网络错误：' + e.message, 'err');
      if (exec) { exec.disabled = false; exec.textContent = '执行入库'; }
      return;
    }
    const data = await resp.json().catch(() => ({}));
    if (resp.ok && data.ok) {
      toast('入库成功：' + (data.batch_name || ''), 'ok');
      const box = $('#impConfirm');
      if (box) box.innerHTML =
        '<div class="empty"><div class="ico">✓</div><div class="t">入库完成</div>' +
        '<div class="s">批次 <b>' + escapeHtml(data.batch_name || '') + '</b> 已创建，新增 ' +
        (data.stats.created || 0) + ' / 更新 ' + (data.stats.updated || 0) + ' 行。</div></div>';
      setTimeout(() => location.reload(), 1200);
    } else {
      toast('入库失败：' + (data.detail || resp.status), 'err');
      if (exec) { exec.disabled = false; exec.textContent = '执行入库'; }
    }
  }

  /* ===================== 批次生命周期（M2.6.5 / P1-2） ===================== */
  let hdId = null, hdName = null;

  function bindBatchActions() {
    document.addEventListener('click', e => {
      const btn = e.target.closest('.js-soft, .js-restore, .js-hard');
      if (!btn) return;
      const id = btn.dataset.id, name = btn.dataset.name;
      if (btn.classList.contains('js-soft')) softDelete(id, name);
      else if (btn.classList.contains('js-restore')) restoreBatch(id, name);
      else if (btn.classList.contains('js-hard')) openHardModal(id, name);
    });

    const close = () => { const m = $('#hdModal'); if (m) m.classList.add('hide'); };
    const c = $('#hdClose'); if (c) c.addEventListener('click', close);
    const cx = $('#hdCancel'); if (cx) cx.addEventListener('click', close);
    const ok = $('#hdOk'); if (ok) ok.addEventListener('click', confirmHardDelete);
  }

  function openHardModal(id, name) {
    hdId = id; hdName = name;
    const hint = $('#hdNameHint'); if (hint) hint.textContent = name;
    const inp = $('#hdConfirmInput'); if (inp) inp.value = '';
    const err = $('#hdErr'); if (err) err.classList.add('hide');
    const m = $('#hdModal'); if (m) m.classList.remove('hide');
  }

  async function softDelete(id, name) {
    const reason = window.prompt('软删除批次「' + name + '」，请输入原因（必填）：', '整批回滚');
    if (reason === null) return;
    if (!reason.trim()) { toast('原因不能为空', 'err'); return; }
    const resp = await apiFetch('/api/import/batches/' + id + '/soft-delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: reason.trim() }),
    });
    if (resp.ok) { toast('已软删除：' + name, 'ok'); setTimeout(() => location.reload(), 600); }
    else { const d = await resp.json().catch(() => ({})); toast('失败：' + (d.detail || resp.status), 'err'); }
  }

  async function restoreBatch(id, name) {
    if (!window.confirm('确认还原批次「' + name + '」？')) return;
    const resp = await apiFetch('/api/import/batches/' + id + '/restore', { method: 'POST' });
    if (resp.ok) { toast('已还原：' + name, 'ok'); setTimeout(() => location.reload(), 600); }
    else { const d = await resp.json().catch(() => ({})); toast('失败：' + (d.detail || resp.status), 'err'); }
  }

  async function confirmHardDelete() {
    const inp = $('#hdConfirmInput');
    const name = inp ? inp.value.trim() : '';
    const err = $('#hdErr');
    if (name !== hdName) {
      if (err) { err.textContent = '输入的批次名与「' + hdName + '」不一致，已取消'; err.classList.remove('hide'); }
      return;
    }
    const resp = await apiFetch('/api/import/batches/' + hdId + '/hard-delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm_name: name }),
    });
    if (resp.ok) {
      const d = await resp.json().catch(() => ({}));
      toast('已硬删除：' + (d.batch_name || hdName), 'ok');
      if ($('#hdModal')) $('#hdModal').classList.add('hide');
      setTimeout(() => location.reload(), 600);
    } else {
      const d = await resp.json().catch(() => ({}));
      if (err) { err.textContent = '失败：' + (d.detail || resp.status); err.classList.remove('hide'); }
    }
  }

  /* ===================== 匹配确认筛选 ===================== */
  function bindMatchFilter() {
    const seg = $('#matchSeg');
    const list = $('#matchList');
    if (!seg || !list) return;
    const items = $$('.match-item', list);
    const filter = (mode) => {
      items.forEach(it => {
        const score = parseFloat(it.dataset.score || '0') || 0;
        let show = true;
        if (mode === 'high') show = score >= 90;
        else if (mode === 'low') show = score < 75;
        it.style.display = show ? '' : 'none';
      });
      // 同步 URL（筛选状态可刷新保持/分享）
      const params = new URLSearchParams(location.search);
      if (mode === 'all') params.delete('filter');
      else params.set('filter', mode);
      const qs = params.toString();
      history.replaceState(null, '', qs ? location.pathname + '?' + qs : location.pathname);
    };
    // 初始化时读取 URL 参数（?filter=high/low 直接生效）
    const initMode = new URLSearchParams(location.search).get('filter');
    if (initMode === 'high' || initMode === 'low') {
      const b = seg.querySelector('button[data-filter="' + initMode + '"]');
      if (b) {
        $$('button', seg).forEach(x => x.classList.remove('on'));
        b.classList.add('on');
        filter(initMode);
      }
    }
    seg.addEventListener('click', e => {
      const b = e.target.closest('button[data-filter]');
      if (!b || b.disabled) return;
      $$('button', seg).forEach(x => x.classList.remove('on'));
      b.classList.add('on');
      filter(b.dataset.filter || 'all');
    });
  }

  /* ===================== 匹配确认（单个+批量） ===================== */
  function bindMatchConfirm() {
    const list = $('#matchList');
    if (!list) return;

    // 单个确认
    list.addEventListener('click', async e => {
      const btn = e.target.closest('.js-confirm-match');
      if (!btn || btn.disabled) return;
      const boqId = btn.dataset.boqId;
      const dictId = btn.dataset.dictId;
      const dictName = btn.dataset.dictName || '';
      if (!boqId || !dictId) return;
      if (!window.confirm('确认将此条目标记为「' + dictName + '」？\n（仅填空 B 类字段，不覆盖已有值）')) return;

      btn.disabled = true;
      btn.textContent = '确认中...';
      try {
        const resp = await apiFetch('/api/match/confirm', {
          method: 'POST',
          body: JSON.stringify({
            operator: 'dev-user',
            reason: '匹配确认页面人工确认',
            items: [{ boq_item_id: parseInt(boqId), dict_id: parseInt(dictId) }],
          }),
        });
        if (resp.ok) {
          toast('已确认：' + dictName + '（最高置信候选）', 'ok');
          const item = btn.closest('.match-item');
          if (item) item.remove();
          // 更新待确认数量
          const sub = document.querySelector('.card-sub');
          if (sub) {
            const remaining = document.querySelectorAll('.match-item').length;
            sub.innerHTML = sub.innerHTML.replace(/本期展示 \\d+ 条/, '本期展示 ' + remaining + ' 条');
          }
        } else {
          const err = await resp.json().catch(() => ({}));
          toast('确认失败：' + (err.detail || resp.statusText), 'err');
          btn.disabled = false;
          btn.textContent = '确认为此项';
        }
      } catch (err) {
        toast('确认失败：' + err.message, 'err');
        btn.disabled = false;
        btn.textContent = '确认为此项';
      }
    });

    // 全选当前页（只勾选可见条目，配合筛选使用）
    const selectAllBtn = $('#selectAllBtn');
    if (selectAllBtn) {
      selectAllBtn.addEventListener('click', () => {
        const visible = $$('.match-item', list).filter(it => it.style.display !== 'none');
        const checkboxes = visible.map(it => it.querySelector('.match-check')).filter(Boolean);
        const allChecked = checkboxes.every(cb => cb.checked);
        checkboxes.forEach(cb => { cb.checked = !allChecked; });
        selectAllBtn.textContent = allChecked ? '全选当前页' : '取消全选';
        toast((allChecked ? '已取消勾选' : '已勾选 ') + checkboxes.length + ' 条', 'ok');
      });
    }

    // 批量确认
    const batchConfirmBtn = $('#batchConfirmBtn');
    if (batchConfirmBtn) {
      batchConfirmBtn.addEventListener('click', async () => {
        const checked = $$('.match-check:checked', list);
        if (!checked.length) { toast('请先勾选要确认的条目', 'warn'); return; }
        if (!window.confirm('确认批量回填 ' + checked.length + ' 条？（取每条 Top1 候选）')) return;

        const items = [];
        checked.forEach(cb => {
          const boqId = cb.dataset.boqId;
          const item = cb.closest('.match-item');
          const topBtn = item ? item.querySelector('.js-confirm-match') : null;
          const dictId = topBtn ? topBtn.dataset.dictId : null;
          if (boqId && dictId) items.push({ boq_item_id: parseInt(boqId), dict_id: parseInt(dictId) });
        });
        if (!items.length) { toast('没有可确认的候选', 'warn'); return; }

        batchConfirmBtn.disabled = true;
        batchConfirmBtn.textContent = '确认中...';
        try {
          const resp = await apiFetch('/api/match/confirm', {
            method: 'POST',
            body: JSON.stringify({ operator: 'dev-user', reason: '批量确认', items }),
          });
          if (resp.ok) {
            const result = await resp.json().catch(() => ({}));
            const filled = result.data ? result.data.filled : items.length;
            toast('批量确认成功：' + filled + ' 条（取 Top1 最高置信候选）', 'ok');
            // 已确认条目从列表移除
            checked.forEach(cb => {
              const item = cb.closest('.match-item');
              if (item) item.remove();
            });
            // 更新待确认数量显示
            const sub = document.querySelector('.card-sub');
            if (sub) {
              const remaining = document.querySelectorAll('.match-item').length;
              sub.innerHTML = sub.innerHTML.replace(/本期展示 \\d+ 条/, '本期展示 ' + remaining + ' 条');
            }
            // 重置全选按钮文字
            const sab = document.querySelector('#selectAllBtn');
            if (sab) sab.textContent = '全选当前页';
          } else {
            const err = await resp.json().catch(() => ({}));
            toast('批量确认失败：' + (err.detail || resp.statusText), 'err');
          }
        } catch (err) {
          toast('批量确认失败：' + err.message, 'err');
        } finally {
          batchConfirmBtn.disabled = false;
          batchConfirmBtn.textContent = '批量确认';
        }
      });
    }

    // 批量忽略（仅前端标记，不调用 API——忽略语义为"暂不处理"）
    const batchIgnoreBtn = $('#batchIgnoreBtn');
    if (batchIgnoreBtn) {
      batchIgnoreBtn.addEventListener('click', () => {
        const checked = $$('.match-check:checked', list);
        if (!checked.length) { toast('请先勾选要忽略的条目', 'warn'); return; }
        checked.forEach(cb => { const item = cb.closest('.match-item'); if (item) item.style.display = 'none'; });
        toast('已忽略 ' + checked.length + ' 条（刷新后恢复）', 'ok');
      });
    }

    // 手动添加并确认
    const manualModal = document.querySelector('#manualAddModal');
    if (manualModal) {
      let currentBoqId = null;
      let dictCache = null;

      // 加载分类列表
      async function loadDict() {
        if (dictCache) return dictCache;
        try {
          const resp = await apiFetch('/api/dict');
          if (resp.ok) {
            dictCache = await resp.json();
            return dictCache;
          }
        } catch (e) {}
        return { l1: [], l2: [] };
      }

      // 打开弹窗
      list.addEventListener('click', async e => {
        const btn = e.target.closest('.js-manual-add');
        if (!btn) return;
        currentBoqId = btn.dataset.boqId;
        const name = btn.dataset.name || '';
        const feat = btn.dataset.feat || '';

        // 填充表单
        document.querySelector('#manualName').value = name;
        document.querySelector('#manualSpec').value = feat;
        document.querySelector('#manualSynonyms').value = '';
        document.querySelector('#manualNote').value = '';

        // 加载分类并填充级联
        const data = await loadDict();
        const l1Sel = document.querySelector('#manualL1');
        const l2Sel = document.querySelector('#manualL2');
        l1Sel.innerHTML = '<option value="">请选择一级分类</option>' +
          data.l1.map(n => '<option value="' + n.id + '">' + n.name + '</option>').join('');
        l2Sel.innerHTML = '<option value="">请先选择一级分类</option>';

        l1Sel.onchange = () => {
          const l1Id = parseInt(l1Sel.value);
          const l2List = data.l2.filter(n => n.parent_id === l1Id);
          l2Sel.innerHTML = '<option value="">请选择二级分类</option>' +
            l2List.map(n => '<option value="' + n.id + '">' + n.name + '</option>').join('');
        };

        manualModal.style.display = 'flex';
      });

      // 关闭弹窗
      manualModal.addEventListener('click', e => {
        if (e.target === manualModal || e.target.closest('[data-close]')) {
          manualModal.style.display = 'none';
        }
      });

      // 提交
      const submitBtn = document.querySelector('#manualAddSubmit');
      if (submitBtn) {
        submitBtn.addEventListener('click', async () => {
          const l1Id = document.querySelector('#manualL1').value;
          const l2Id = document.querySelector('#manualL2').value;
          const name = document.querySelector('#manualName').value.trim();
          const spec = document.querySelector('#manualSpec').value.trim();
          const synonyms = document.querySelector('#manualSynonyms').value.trim();
          const note = document.querySelector('#manualNote').value.trim();

          if (!l1Id || !l2Id) { toast('请选择一级和二级分类', 'warn'); return; }
          if (!name) { toast('请输入物料名称', 'warn'); return; }

          submitBtn.disabled = true;
          submitBtn.textContent = '添加中...';

          try {
            // 1. 创建 l3 物料分类
            const createBody = {
              name: name,
              level: 'l3',
              parent_id: parseInt(l2Id),
              note: note || null,
            };
            if (spec) createBody.spec_whitelist = [spec];
            if (synonyms) createBody.synonyms = synonyms.split(/[,，]/).map(s => s.trim()).filter(Boolean);

            const createResp = await apiFetch('/api/dict', {
              method: 'POST',
              body: JSON.stringify(createBody),
            });
            if (!createResp.ok) {
              const err = await createResp.json().catch(() => ({}));
              toast('创建失败：' + (err.detail || createResp.statusText), 'err');
              return;
            }
            const created = await createResp.json();
            const newDictId = created.id;

            // 2. 确认关联到当前清单项
            const confirmResp = await apiFetch('/api/match/confirm', {
              method: 'POST',
              body: JSON.stringify({
                operator: 'dev-user',
                reason: '手动添加物料并确认（学习记录）',
                items: [{ boq_item_id: parseInt(currentBoqId), dict_id: newDictId }],
              }),
            });
            if (!confirmResp.ok) {
              const err = await confirmResp.json().catch(() => ({}));
              toast('关联失败：' + (err.detail || confirmResp.statusText), 'err');
              return;
            }

            toast('已添加并确认：' + name + '（学习记录已保存）', 'ok');
            manualModal.style.display = 'none';

            // 从列表中移除该条目
            const item = document.querySelector('.match-item[data-boq-id="' + currentBoqId + '"]');
            if (item) item.remove();

            // 更新待确认数量
            const sub = document.querySelector('.card-sub');
            if (sub) {
              const remaining = document.querySelectorAll('.match-item').length;
              sub.innerHTML = sub.innerHTML.replace(/本期展示 \\d+ 条/, '本期展示 ' + remaining + ' 条');
            }
          } catch (err) {
            toast('操作失败：' + err.message, 'err');
          } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = '添加并确认';
          }
        });
      }
    }
  }

  /* ===================== 表格列宽拖拽 ===================== */
  function bindColResize() {
    const tables = $$('.tbl-resizable');
    if (!tables.length) return;

    const pageKey = 'zj-colw-' + (location.pathname || 'page').replace(/[^a-z0-9]/gi, '_');
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(pageKey) || '{}'); } catch (e) {}

    tables.forEach(table => {
      const cols = $$('colgroup col', table);
      const ths = $$('thead th', table);

      // 恢复保存的列宽
      ths.forEach((th, i) => {
        const name = th.dataset.col || ('col' + i);
        if (saved[name] && cols[i]) {
          cols[i].style.width = saved[name] + 'px';
        }
      });

      // 为每个 th 添加拖拽 handle
      ths.forEach((th, i) => {
        if (i >= ths.length - 1) return; // 最后一列不加 handle
        const resizer = document.createElement('div');
        resizer.className = 'col-resizer';
        resizer.title = '拖拽调整列宽';
        th.appendChild(resizer);

        let startX = 0, startW = 0, col = cols[i];

        resizer.addEventListener('mousedown', e => {
          e.preventDefault();
          e.stopPropagation();
          startX = e.pageX;
          startW = col ? col.offsetWidth : th.offsetWidth;
          resizer.classList.add('active');
          document.body.classList.add('col-resizing');

          const onMove = ev => {
            const dx = ev.pageX - startX;
            const newW = Math.max(40, startW + dx);
            if (col) col.style.width = newW + 'px';
          };
          const onUp = () => {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            resizer.classList.remove('active');
            document.body.classList.remove('col-resizing');
            // 保存列宽
            const name = th.dataset.col || ('col' + i);
            if (col) saved[name] = col.offsetWidth;
            try { localStorage.setItem(pageKey, JSON.stringify(saved)); } catch (e) {}
          };
          document.addEventListener('mousemove', onMove);
          document.addEventListener('mouseup', onUp);
        });
      });
    });
  }

  /* ===================== 物料字典新增/编辑弹窗 ===================== */
  function bindDictModal() {
    const modal = $('#dictModal');
    if (!modal) return;

    const title = $('#dictModalTitle');
    const levelSel = $('#dictLevel');
    const parentField = $('#parentField');
    const parentSel = $('#dictParent');
    const nameInp = $('#dictName');
    const synInp = $('#dictSynonyms');
    const specInp = $('#dictSpecs');
    const noteInp = $('#dictNote');
    const l5Fields = $('#l5Fields');
    const specWhitelistField = $('#specWhitelistField');
    const dictSpec = $('#dictSpec');
    const dictModel = $('#dictModel');
    const dictMaterial = $('#dictMaterial');
    const dictUnit = $('#dictUnit');
    const errTip = $('#dictErr');
    let editId = null;

    function showErr(msg) {
      if (errTip) { errTip.textContent = msg; errTip.classList.remove('hide'); }
    }
    function clearErr() { if (errTip) errTip.classList.add('hide'); }

    function openModal(isEdit, data) {
      editId = isEdit ? (data?.id || null) : null;
      title.textContent = isEdit ? '编辑分类' : '新增分类';
      clearErr();
      if (isEdit && data) {
        levelSel.value = data.level || 'l1';
        nameInp.value = data.name || '';
        synInp.value = (data.synonyms || []).join(',');
        specInp.value = (data.spec_whitelist || []).join(',');
        noteInp.value = data.note || '';
        // l5 字段
        if (dictSpec) dictSpec.value = data.spec || '';
        if (dictModel) dictModel.value = data.model || '';
        if (dictMaterial) dictMaterial.value = data.material || '';
        if (dictUnit) dictUnit.value = data.unit || '';
        levelSel.disabled = true; // 编辑时不允许改层级
        parentField.style.display = 'none';
      } else {
        levelSel.value = 'l1';
        nameInp.value = '';
        synInp.value = '';
        specInp.value = '';
        noteInp.value = '';
        if (dictSpec) dictSpec.value = '';
        if (dictModel) dictModel.value = '';
        if (dictMaterial) dictMaterial.value = '';
        if (dictUnit) dictUnit.value = '';
        levelSel.disabled = false;
        updateParentOptions();
      }
      // 根据层级显示/隐藏 l5 字段
      updateL5Fields();
      modal.classList.remove('hide');
    }

    function updateL5Fields() {
      const isL5 = levelSel.value === 'l5';
      if (l5Fields) l5Fields.style.display = isL5 ? '' : 'none';
      if (specWhitelistField) specWhitelistField.style.display = isL5 ? 'none' : '';
    }

    function closeModal() { modal.classList.add('hide'); editId = null; }

    async function updateParentOptions() {
      const level = levelSel.value;
      if (level === 'l1') {
        parentField.style.display = 'none';
        return;
      }
      parentField.style.display = '';
      // 通用：父级层级 = 当前层级 - 1
      const levelNum = parseInt(level.replace('l', ''));
      const parentLevel = 'l' + (levelNum - 1);
      try {
        const resp = await apiFetch('/api/dict?level=' + parentLevel);
        parentSel.innerHTML = '<option value="">加载中...</option>';
        if (resp.ok) {
          const data = await resp.json();
          const nodes = data.nodes || [];
          const opts = nodes.map(n => {
            const code = n.code ? `<span style="color:#4D7CFE;font-family:monospace;font-size:11px;margin-right:6px">${n.code}</span>` : '';
            return `<option value="${n.id}">${n.code ? '[' + n.code + '] ' : ''}${escapeHtml(n.name)}</option>`;
          });
          parentSel.innerHTML = opts.length ? opts.join('') : '<option value="">（无可用父级）</option>';
        } else {
          // 回退：从页面树节点提取
          const nodes = $$('.tree-node a');
          const opts = [];
          nodes.forEach(a => {
            const node = a.closest('.tree-node');
            const pl = parseInt(node.style.paddingLeft) || 8;
            const depth = Math.floor((pl - 8) / 16);
            const nodeLevel = 'l' + (depth + 1);
            if (nodeLevel === parentLevel) {
              const id = node.dataset.id;
              opts.push('<option value="' + id + '">' + escapeHtml(a.textContent.trim()) + '</option>');
            }
          });
          parentSel.innerHTML = opts.length ? opts.join('') : '<option value="">（无可用父级）</option>';
        }
      } catch (e) {
        parentSel.innerHTML = '<option value="">（加载失败）</option>';
      }
    }

    levelSel.addEventListener('change', () => {
      updateParentOptions();
      updateL5Fields();
    });

    // 新增按钮
    const addBtn = $('#addDictBtn');
    if (addBtn) addBtn.addEventListener('click', () => openModal(false));

    // 编辑按钮
    const editBtn = $('#editDictBtn');
    if (editBtn) {
      editBtn.addEventListener('click', async () => {
        const id = editBtn.dataset.id;
        if (!id) return;
        try {
          const resp = await apiFetch('/api/dict/' + id);
          if (resp.ok) {
            const data = await resp.json();
            openModal(true, data);
          } else {
            toast('加载分类详情失败', 'err');
          }
        } catch (e) {
          toast('加载分类详情失败：' + e.message, 'err');
        }
      });
    }

    // 关闭
    $('#dictModalClose')?.addEventListener('click', closeModal);
    $('#dictCancel')?.addEventListener('click', closeModal);
    modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });

    // 提交
    $('#dictSubmit')?.addEventListener('click', async () => {
      const name = nameInp.value.trim();
      if (!name) { showErr('请输入分类名称'); return; }
      const level = levelSel.value;
      let parent_id = null;
      if (level !== 'l1') {
        parent_id = parseInt(parentSel.value) || null;
        if (!parent_id) { showErr('请选择父级分类'); return; }
      }
      // l5 必须填写规格
      if (level === 'l5') {
        const spec = dictSpec ? dictSpec.value.trim() : '';
        if (!spec) { showErr('五级（规格）必须填写规格'); return; }
      }
      const synonyms = synInp.value.trim() ? synInp.value.split(',').map(s => s.trim()).filter(Boolean) : null;
      const specs = specInp.value.trim() ? specInp.value.split(',').map(s => s.trim()).filter(Boolean) : null;
      const note = noteInp.value.trim() || null;

      const submitBtn = $('#dictSubmit');
      submitBtn.disabled = true;
      submitBtn.textContent = '提交中...';
      clearErr();

      try {
        let resp;
        if (editId) {
          const body = { name, synonyms, spec_whitelist: specs, note };
          // 编辑 l5 时也提交属性字段
          if (level === 'l5') {
            body.spec = dictSpec ? dictSpec.value.trim() : null;
            body.model = dictModel ? dictModel.value.trim() : null;
            body.material = dictMaterial ? dictMaterial.value.trim() : null;
            body.unit = dictUnit ? dictUnit.value.trim() : null;
          }
          resp = await apiFetch('/api/dict/' + editId, {
            method: 'PUT',
            body: JSON.stringify(body),
          });
        } else {
          const body = { name, level, parent_id, synonyms, spec_whitelist: specs, note };
          // l5 提交属性字段
          if (level === 'l5') {
            body.spec = dictSpec ? dictSpec.value.trim() : null;
            body.model = dictModel ? dictModel.value.trim() : null;
            body.material = dictMaterial ? dictMaterial.value.trim() : null;
            body.unit = dictUnit ? dictUnit.value.trim() : null;
          }
          resp = await apiFetch('/api/dict', {
            method: 'POST',
            body: JSON.stringify(body),
          });
        }
        if (resp.ok) {
          const data = await resp.json().catch(() => ({}));
          const codeMsg = data.code ? `（编码：${data.code}）` : '';
          toast(editId ? '分类已更新' : ('分类已创建' + codeMsg), 'ok');
          closeModal();
          setTimeout(() => location.reload(), 800);
        } else {
          const err = await resp.json().catch(() => ({}));
          showErr(err.detail || ('提交失败 (' + resp.status + ')'));
        }
      } catch (e) {
        showErr('提交失败：' + e.message);
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = '确认';
      }
    });

    // 添加规格（简单 prompt 交互）
    $$('.js-add-spec').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.dataset.id;
        const spec = prompt('请输入规格（如：3×240+2×120）：');
        if (!spec) return;
        try {
          const resp = await apiFetch('/api/dict/' + id);
          if (!resp.ok) { toast('加载失败', 'err'); return; }
          const data = await resp.json();
          const specs = (data.spec_whitelist || []).concat([spec]);
          const upd = await apiFetch('/api/dict/' + id, {
            method: 'PUT', body: JSON.stringify({ spec_whitelist: specs }),
          });
          if (upd.ok) { toast('规格已添加', 'ok'); setTimeout(() => location.reload(), 600); }
          else toast('添加失败', 'err');
        } catch (e) { toast('添加失败：' + e.message, 'err'); }
      });
    });

    // 添加同义词
    $$('.js-add-synonym').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.dataset.id;
        const syn = prompt('请输入同义词（如：电力电缆）：');
        if (!syn) return;
        try {
          const resp = await apiFetch('/api/dict/' + id);
          if (!resp.ok) { toast('加载失败', 'err'); return; }
          const data = await resp.json();
          const syns = (data.synonyms || []).concat([syn]);
          const upd = await apiFetch('/api/dict/' + id, {
            method: 'PUT', body: JSON.stringify({ synonyms: syns }),
          });
          if (upd.ok) { toast('同义词已添加', 'ok'); setTimeout(() => location.reload(), 600); }
          else toast('添加失败', 'err');
        } catch (e) { toast('添加失败：' + e.message, 'err'); }
      });
    });
  }

  /* ===================== 初始化 ===================== */
  function init() {
    initTheme();
    bindSeg();
    bindDrop();
    bindDictTree();
    bindImportWizard();
    bindImportFlow();
    bindBatchActions();
    bindMatchFilter();
    bindMatchConfirm();
    bindColResize();
    bindDictModal();
    // M2 深化：加载字段映射模板数据
    if (typeof initMappingData === 'function') initMappingData();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // M2 深化：将模板管理函数暴露到全局作用域（供 HTML onclick 调用）
  window.saveMappingTemplate = saveMappingTemplate;
  window.loadMappingTemplate = loadMappingTemplate;
  window.resetMappingToAuto = resetMappingToAuto;
  window.updateFieldMapping = updateFieldMapping;
})();
