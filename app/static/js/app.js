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

  /* ===================== 物料字典树 ===================== */
  function bindDictTree() {
    const tree = $('#dictTree');
    if (!tree) return;
    tree.addEventListener('click', e => {
      const caret = e.target.closest('.tree-caret[data-caret]');
      if (!caret) return;
      const id = caret.dataset.caret;
      const children = tree.querySelector('.tree-children[data-children="' + CSS.escape(id) + '"]');
      if (!children) return;
      const hidden = children.classList.toggle('hide');
      caret.classList.toggle('open', !hidden);
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
    };

    showFileInfo(
      '<div class="stat-line"><span>文件</span><b>' + escapeHtml(data.filename || file.name) + '</b></div>' +
      '<div class="stat-line"><span>工作表</span><b>' + escapeHtml(data.sheet_name || '—') + '</b></div>' +
      '<div class="stat-line"><span>解析行数</span><b class="mono">' + (data.row_count || 0) + '</b></div>'
    );
    renderMapping(data);
    renderPreview(data);

    const next = $('#impNext'); if (next) next.disabled = false;
    const exec = $('#impExecute'); if (exec) { exec.disabled = false; exec.textContent = '执行入库'; }
    toast('解析完成，请继续配置后执行入库', 'ok');
  }

  function renderMapping(data) {
    const box = $('#impMapping');
    const count = $('#impMapCount');
    if (!box) return;
    const unrec = (data.unrecognized_columns || []);
    const warns = (data.warnings || []);
    box.innerHTML =
      '<div class="stat-line"><span class="muted">识别行数</span><b class="mono">' + (data.row_count || 0) + '</b></div>' +
      '<div class="stat-line"><span class="muted">跳过行</span><b class="mono">' + (data.skipped_count || 0) + '</b></div>' +
      '<div class="stat-line"><span class="muted">异常行</span><b class="mono">' + (data.anomaly_count || 0) + '</b></div>' +
      (unrec.length ? '<div class="note mt"><span>ⓘ</span><div>未识别列：' + escapeHtml(unrec.join('、')) + '</div></div>' : '') +
      (warns.length ? '<div class="note mt"><span>⚠</span><div>' + escapeHtml(warns.join('；')) + '</div></div>' : '') +
      '<div class="note mt"><span>ⓘ</span><div>字段映射依据表头别名库自动完成；下方「确认入库」将按所选数据性质写入。</div></div>';
    if (count) count.textContent = (data.row_count || 0) + ' 行';
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
    };
    seg.addEventListener('click', e => {
      const b = e.target.closest('button[data-filter]');
      if (!b || b.disabled) return;
      $$('button', seg).forEach(x => x.classList.remove('on'));
      b.classList.add('on');
      filter(b.dataset.filter || 'all');
    });
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
    bindColResize();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
