'use strict';

/* =====================================================================
 * 第二大脑 · web —— hub 的浏览器版
 * 数据来自 server.py 的 /api/bundle；没有服务端时退回 data/bundle.json 静态快照。
 * ===================================================================== */

const ALL_PAGES = [
  { key: 'home',   ico: '◎', name: '首页',   sub: '总览' },
  { key: 'douyin', ico: '♪', name: '抖音',   sub: '作品与趋势' },
  { key: 'xhs',    ico: '✦', name: '小红书', sub: '笔记与指标' },
];
// 「我的」只在手机壳里有（要读写 App 私有设置 / 本机同步记录）；浏览器版不显示
if (window.AndroidRepo) ALL_PAGES.push({ key: 'me', ico: '◉', name: '我的', sub: '同步记录 · 设置' });
let PAGES = ALL_PAGES.slice();

const state = {
  data: null,
  route: { key: 'home', params: {} },
  notes: { groupOpen: {}, q: '' },
  tl: { filter: 'all', expanded: {} },
  sel: { douyin: '__all__', xhs: '__all__', bills: '__all__' },
  quiz: null,
  features: { onboarded: true, douyin: true, xhs: true },
};

/* ------------------------------------------------------------ 小工具 */
const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
));
const n0 = (v) => (v == null || Number.isNaN(Number(v))) ? '—' : Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 });
const n1 = (v) => (v == null || Number.isNaN(Number(v))) ? '—' : Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 1 });
const pct = (v, d = 1) => (v == null || Number.isNaN(Number(v))) ? '—' : (Number(v) * 100).toFixed(d) + '%';
const money = (v) => (v == null || Number.isNaN(Number(v))) ? '—' : '¥' + Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const secs = (v) => (v == null || Number.isNaN(Number(v))) ? '—' : (Number(v) >= 60 ? (Number(v) / 60).toFixed(1) + ' 分' : Number(v).toFixed(1) + ' 秒');
const mmdd = (s) => (s || '').slice(5, 10);
const escAttr = (s) => esc(s).replace(/"/g, '&quot;');

function toast(msg, ms = 2200) {
  let el = $('.toast');
  if (!el) {
    el = document.createElement('div');
    el.className = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), ms);
}

function go(key, params = {}) {
  const qs = new URLSearchParams(params).toString();
  location.hash = '#/' + key + (qs ? '?' + qs : '');
}

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, '');
  const [path, qs] = raw.split('?');
  const params = {};
  new URLSearchParams(qs || '').forEach((v, k) => { params[k] = v; });
  return { key: PAGES.some((p) => p.key === path) ? path : 'home', params };
}

/* ------------------------------------------------------------ 功能开关 */
function rebuildPages() {
  PAGES = ALL_PAGES.filter((p) => p.key === 'home' || p.key === 'me'
    || state.features[p.key] !== false);
}

function loadFeatures() {
  try {
    if (window.AndroidRepo && typeof AndroidRepo.features === 'function') {
      const f = JSON.parse(AndroidRepo.features() || '{}');
      state.features = {
        onboarded: !!f.onboarded,
        douyin: f.douyin !== false,
        xhs: f.xhs !== false,
      };
    } else {
      const raw = localStorage.getItem('aimind.features');
      if (raw) state.features = Object.assign(state.features, JSON.parse(raw));
    }
  } catch (e) { /* 读不到就按默认全开 */ }
  rebuildPages();
}

function saveFeature(key, on) {
  state.features[key] = !!on;
  try {
    if (window.AndroidRepo && typeof AndroidRepo.setFeature === 'function') {
      AndroidRepo.setFeature(key, !!on);
    } else {
      localStorage.setItem('aimind.features', JSON.stringify(state.features));
    }
  } catch (e) { /* 设置失败也不挡用 */ }
}

/** 首次启动的模块选择 + 「我的 → 功能拓展」共用同一个弹层。 */
function showFeatureModal(firstRun) {
  const mask = document.createElement('div');
  mask.className = 'feat-mask';
  mask.innerHTML = `
    <div class="feat-card">
      <div class="feat-title">${firstRun ? '先选一下要用的功能' : '功能拓展'}</div>
      <div class="feat-sub">${firstRun
        ? '默认都打开，之后在「我的 → 功能拓展」里随时改。'
        : '关闭只隐藏入口，已经同步的数据不会动。'}</div>
      <label class="feat-row">
        <div><b>抖音</b><div class="feat-desc">账号、作品、趋势、自动同步</div></div>
        <input type="checkbox" id="feat-douyin" ${state.features.douyin ? 'checked' : ''}>
      </label>
      <label class="feat-row">
        <div><b>小红书</b><div class="feat-desc">账号、笔记、近 30 天指标</div></div>
        <input type="checkbox" id="feat-xhs" ${state.features.xhs ? 'checked' : ''}>
      </label>
      <div class="feat-actions"><button class="btn primary" id="feat-done">${firstRun ? '开始使用' : '完成'}</button></div>
    </div>`;
  document.body.appendChild(mask);

  const dy = mask.querySelector('#feat-douyin');
  const xh = mask.querySelector('#feat-xhs');
  dy.addEventListener('change', () => saveFeature('douyin', dy.checked));
  xh.addEventListener('change', () => saveFeature('xhs', xh.checked));

  mask.querySelector('#feat-done').addEventListener('click', () => {
    saveFeature('douyin', dy.checked);
    saveFeature('xhs', xh.checked);
    if (firstRun) {
      state.features.onboarded = true;
      try {
        if (window.AndroidRepo && typeof AndroidRepo.setOnboarded === 'function') AndroidRepo.setOnboarded();
        else localStorage.setItem('aimind.features', JSON.stringify(state.features));
      } catch (e) { /* ignore */ }
    }
    mask.remove();
    rebuildPages();
    if (!PAGES.some((p) => p.key === state.route.key)) location.hash = '#/home';
    renderNav();
    render();
  });
}

/* ------------------------------------------------------------ 数据 */
async function loadData() {
  if (window.HubAndroid) {
    const data = await window.HubAndroid.bundle();
    data.meta.mode = 'android';
    return data;
  }
  const bust = '?t=' + Date.now();
  try {
    const r = await fetch('api/bundle' + bust, { cache: 'no-store' });
    if (!r.ok) throw new Error('no api');
    const data = await r.json();
    data.meta.mode = 'live';
    return data;
  } catch (e) {
    const r = await fetch('data/bundle.json' + bust, { cache: 'no-store' });
    if (!r.ok) throw new Error('没有找到数据：请用 server.py 启动，或先生成静态快照');
    const data = await r.json();
    data.meta.mode = 'static';
    mergeLocalQuiz(data);
    return data;
  }
}

/* 静态模式下刷题进度只存浏览器本地 */
const LS_KEY = 'hubweb.quiz.review';
function localReview() {
  try { return JSON.parse(localStorage.getItem(LS_KEY) || '{}'); } catch (e) { return {}; }
}
function saveLocalReview(obj) {
  try { localStorage.setItem(LS_KEY, JSON.stringify(obj)); } catch (e) { /* 隐私模式忽略 */ }
}
function mergeLocalQuiz(data) {
  const local = localReview();
  (data.quiz?.subjects || []).forEach((s) => {
    s.review = Object.assign({}, s.review || {}, local[s.subject] || {});
  });
}

/* ------------------------------------------------------------ 图表 */
function svgWrap(w, h, inner, cls = 'chart') {
  return `<svg class="${cls}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" role="img">${inner}</svg>`;
}

function chartLine(labels, series, opts = {}) {
  const w = 760, h = opts.height || 250;
  const pad = { l: 48, r: 16, t: 16, b: 30 };
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;
  const all = series.flatMap((s) => s.values).filter((v) => v != null && !Number.isNaN(v));
  if (!all.length) return `<div class="empty">暂无数据</div>`;
  let min = Math.min(...all), max = Math.max(...all);
  if (opts.zero) min = Math.min(0, min);
  if (min === max) { min -= 1; max += 1; }
  const padY = (max - min) * 0.12;
  const nonNeg = all.every((v) => v >= 0);
  min -= padY; max += padY;
  if (nonNeg && opts.zero) min = 0;
  const span = max - min;
  const n = labels.length;
  const X = (i) => pad.l + (n <= 1 ? iw / 2 : (i * iw) / (n - 1));
  const Y = (v) => pad.t + ih - ((v - min) / span) * ih;
  const yFmt = opts.yFmt || ((v) => n0(v));

  let grid = '';
  for (let g = 0; g <= 4; g++) {
    const v = min + (span * g) / 4;
    const y = Y(v);
    grid += `<line class="grid-line" x1="${pad.l}" y1="${y}" x2="${w - pad.r}" y2="${y}"/>
      <text x="${pad.l - 8}" y="${y + 3.5}" text-anchor="end">${esc(yFmt(v))}</text>`;
  }
  let paths = '';
  series.forEach((s, si) => {
    const pts = s.values.map((v, i) => v == null ? null : [X(i), Y(v)]).filter(Boolean);
    if (!pts.length) return;
    const d = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
    const color = s.color || (si === 0 ? 'var(--accent)' : '#9db4e8');
    if (s.fill) {
      paths += `<defs><linearGradient id="grad${si}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${color}" stop-opacity=".22"/>
        <stop offset="100%" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
        <path d="${d} L ${pts[pts.length - 1][0].toFixed(1)} ${pad.t + ih} L ${pts[0][0].toFixed(1)} ${pad.t + ih} Z" fill="url(#grad${si})" stroke="none"/>`;
    }
    paths += `<path d="${d}" fill="none" stroke="${color}" stroke-width="${s.width || 2.2}" ${s.dash ? `stroke-dasharray="${s.dash}"` : ''} stroke-linejoin="round" stroke-linecap="round"/>`;
    if (s.dots !== false && n <= 45) {
      paths += pts.map((p) => `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="2.6" fill="${color}"/>`).join('');
    }
  });
  const step = Math.max(1, Math.ceil(n / 7));
  let xlabels = '';
  labels.forEach((lb, i) => {
    if (i % step && i !== n - 1) return;
    xlabels += `<text x="${X(i)}" y="${h - 9}" text-anchor="middle">${esc(lb)}</text>`;
  });
  return svgWrap(w, h, `${grid}${paths}${xlabels}`);
}

function chartBars(labels, values, opts = {}) {
  const w = 760, h = opts.height || 220;
  const pad = { l: 46, r: 14, t: 14, b: 28 };
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;
  const vals = values.map((v) => (v == null ? 0 : v));
  const max = Math.max(1, ...vals);
  const n = vals.length;
  const step = iw / Math.max(1, n);
  const bw = Math.max(2, Math.min(26, step * 0.62));
  let grid = '';
  for (let g = 0; g <= 3; g++) {
    const v = (max * g) / 3;
    const y = pad.t + ih - (v / max) * ih;
    grid += `<line class="grid-line" x1="${pad.l}" y1="${y}" x2="${w - pad.r}" y2="${y}"/>
      <text x="${pad.l - 8}" y="${y + 3.5}" text-anchor="end">${esc((opts.yFmt || n0)(v))}</text>`;
  }
  const bars = vals.map((v, i) => {
    const bh = (v / max) * ih;
    const x = pad.l + i * step + (step - bw) / 2;
    const color = opts.colorAt ? opts.colorAt(i, v) : (opts.color || 'var(--accent)');
    return `<rect class="bar" x="${x.toFixed(1)}" y="${(pad.t + ih - bh).toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(0, bh).toFixed(1)}" rx="2" fill="${color}"><title>${esc(labels[i] || '')}：${esc((opts.yFmt || n0)(v))}</title></rect>`;
  }).join('');
  const lstep = Math.max(1, Math.ceil(n / 7));
  const xlabels = labels.map((lb, i) => (i % lstep && i !== n - 1) ? '' :
    `<text x="${(pad.l + i * step + step / 2).toFixed(1)}" y="${h - 9}" text-anchor="middle">${esc(lb)}</text>`).join('');
  return svgWrap(w, h, `${grid}${bars}${xlabels}`);
}

/* ------------------------------------------------------------ Markdown */
function inlineMd(s, baseDir) {
  let t = esc(s);
  t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
  t = t.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, '<span aria-label="$1">🖼</span>');
  t = t.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, label, href) => {
    const raw = href.replace(/&amp;/g, '&');
    return `<a href="${mdHref(raw, baseDir)}" ${/^https?:/.test(raw) ? 'target="_blank" rel="noopener"' : ''}>${label}</a>`;
  });
  t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  t = t.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  t = t.replace(/~~([^~]+)~~/g, '<del>$1</del>');
  return t;
}

function mdHref(href, baseDir) {
  if (/^https?:|^mailto:|^#/.test(href)) return escAttr(href);
  const clean = href.split('#')[0];
  if (/\.md$/i.test(clean)) {
    let p = clean;
    if (!clean.startsWith('notes/')) {
      const segs = (baseDir || 'notes').split('/').filter(Boolean);
      clean.split('/').forEach((s) => {
        if (s === '..') segs.pop();
        else if (s !== '.') segs.push(s);
      });
      p = segs.join('/');
    }
    if (p.startsWith('notes/')) return '#/notes?path=' + encodeURIComponent(p);
  }
  return escAttr(href);
}

function renderMarkdown(text, baseDir) {
  const lines = String(text || '').split(/\r?\n/);
  const out = [];
  let i = 0;

  const isBlockStart = (ln) => /^(#{1,6}\s|```|\s*[-*+]\s+|\s*\d+\.\s+|>\s?|\|)/.test(ln);

  while (i < lines.length) {
    const line = lines[i];

    if (/^```/.test(line)) {
      const lang = line.slice(3).trim();
      const buf = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++;
      out.push(`<pre${lang ? ` data-lang="${escAttr(lang)}"` : ''}><code>${esc(buf.join('\n'))}</code></pre>`);
      continue;
    }

    if (!line.trim()) { i++; continue; }

    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      const lv = h[1].length;
      out.push(`<h${lv}>${inlineMd(h[2], baseDir)}</h${lv}>`);
      i++;
      continue;
    }

    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { out.push('<hr>'); i++; continue; }

    if (/^\s*\|/.test(line) && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1])) {
      const cells = (ln) => ln.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(cells(lines[i++]));
      out.push(`<div class="md-table-wrap${head.length <= 3 ? ' narrow' : ''}"><table><thead><tr>` +
        head.map((c) => `<th>${inlineMd(c, baseDir)}</th>`).join('') + '</tr></thead><tbody>' +
        rows.map((r) => '<tr>' + r.map((c) => `<td>${inlineMd(c, baseDir)}</td>`).join('') + '</tr>').join('') +
        '</tbody></table></div>');
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      const buf = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ''));
      out.push(`<blockquote>${renderMarkdown(buf.join('\n'), baseDir)}</blockquote>`);
      continue;
    }

    if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\.\s+/.test(line);
      const items = [];
      while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
        let it = lines[i++].replace(/^\s*([-*+]|\d+\.)\s+/, '');
        let checkbox = '';
        const cb = it.match(/^\[([ xX])\]\s+(.*)$/);
        if (cb) {
          checkbox = `<input type="checkbox" disabled ${cb[1].toLowerCase() === 'x' ? 'checked' : ''}>`;
          it = cb[2];
        }
        items.push(`<li>${checkbox}${inlineMd(it, baseDir)}</li>`);
      }
      out.push(ordered ? `<ol>${items.join('')}</ol>` : `<ul>${items.join('')}</ul>`);
      continue;
    }

    const buf = [line];
    i++;
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) buf.push(lines[i++]);
    out.push(`<p>${inlineMd(buf.join(' '), baseDir)}</p>`);
  }
  return out.join('\n');
}

/* ------------------------------------------------------------ 框架 */
function renderNav() {
  const nav = $('#nav');
  nav.innerHTML = PAGES.map((p) => `
    <button class="nav-item ${state.route.key === p.key ? 'active' : ''}" data-go="${p.key}">
      <span class="ico">${p.ico}</span><span class="txt">${p.name}</span>
    </button>`).join('');
  const tab = $('#tabbar');
  tab.innerHTML = PAGES.map((p) => `
    <button class="${state.route.key === p.key ? 'active' : ''}" data-go="${p.key}">
      <span class="ico">${p.ico}</span><span>${p.name}</span>
    </button>`).join('');
}

function setChrome(title, sub) {
  $('#page-title').textContent = title;
  $('#page-sub').textContent = sub || '';
  const mode = state.data?.meta?.mode;
  const pill = $('#mode-pill');
  pill.textContent = { live: '实时数据', static: '静态快照', android: '半离线' }[mode] || '读取中';
  pill.className = 'pill ' + (mode === 'static' ? 'static' : 'live');
  const where = mode === 'android' ? 'Android · 本地副本' : (mode === 'live' ? '服务端' : '快照');
  $('#side-foot').innerHTML = `数据更新 ${esc(state.data?.meta?.generated_at || '—')}<br>${esc(state.data?.meta?.machine || '')} · ${where}`;
}

async function render() {
  state.route = parseHash();
  if (window.__meTick) { clearInterval(window.__meTick); window.__meTick = null; }
  const key = state.route.key;
  const page = PAGES.find((p) => p.key === key) || PAGES[0];
  renderNav();
  const view = $('#view');
  const pages = { home: pageHome, douyin: pageDouyin, xhs: pageXhs, me: pageMe };
  const result = (pages[key] || pageHome)();
  setChrome(page.name + (result.crumb ? ' · ' + result.crumb : ''), result.sub || page.sub);
  view.innerHTML = result.html;
  if (result.mount) result.mount();
  window.scrollTo(0, 0);
}

/* ------------------------------------------------------------ 首页 */
function pageHome() {
  const dy = (state.data.douyin?.accounts || []).length;
  const xh = (state.data.xhs?.accounts || []).length;
  const entries = [
    ['douyin', '♪', '抖音', '多账号 / 作品 / 每日趋势 / 自动同步', dy + ' 个账号'],
    ['xhs', '✿', '小红书', '多账号 / 笔记 / 近 30 天指标 / 自动导出', xh + ' 个账号'],
  ];
  if (window.AndroidRepo) entries.push(['me', '◉', '我的', '同步记录 / 设置 / 版本', '']);

  const html = `
    <div class="hero">
      <h2>抖音 / 小红书数据工作台</h2>
      <p>0.x 内测版 · 完全开源免费，可商用可私用</p>
      <div class="chips">
        <div class="chip"><b>${dy}</b>个抖音账号</div>
        <div class="chip"><b>${xh}</b>个小红书账号</div>
      </div>
    </div>

    <div class="grid g3" style="margin-bottom:14px">
      ${entries.map(([k, ico, name, desc, num]) => `
        <div class="entry" data-go="${k}">
          <div class="top"><span class="ico">${ico}</span>${name}</div>
          <div class="desc">${desc}</div>
          <div class="num">${num}</div>
        </div>`).join('')}
    </div>

    <div class="card card-pad">
      <div class="card-title">反馈</div>
      微信 <b>jack9527xz</b> · 邮箱 <b>1060061749@qq.com</b>
      <div class="hint" style="margin-top:6px">用着有问题、想要新功能，都可以加微信或发邮件。</div>
    </div>`;

  return {
    sub: '抖音、小红书账号数据，一个页面看完',
    html,
  };
}

/* ------------------------------------------------------------ 笔记 */
function noteGroups() {
  const files = state.data.notes.files;
  const q = state.notes.q.trim().toLowerCase();
  const shown = q ? files.filter((f) => (f.title + f.path).toLowerCase().includes(q)) : files;
  const groups = new Map();
  shown.forEach((f) => {
    const g = f.group || '根目录';
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(f);
  });
  const order = [...groups.keys()].sort((a, b) => {
    if (a === '根目录') return -1;
    if (b === '根目录') return 1;
    return a.localeCompare(b, 'zh');
  });
  return { groups, order, q, total: shown.length };
}

function pageNotes() {
  const { groups, order, q, total } = noteGroups();
  const { path } = state.route.params;
  const data = state.data.notes;

  if (path && data.texts[path] != null) {
    const meta = data.files.find((f) => f.path === path) || {};
    const baseDir = path.split('/').slice(0, -1).join('/');
    const html = `
      <div class="notes-wrap reading">
        <aside class="note-tree card" id="tree">${treeHtml(groups, order, path, q, total)}</aside>
        <article class="doc card">
          <div class="doc-head">
            <button class="btn back" id="back">← 列表</button>
            <span class="tag">${esc(path)}</span>
            <span class="spacer"></span>
            <span class="hint" style="color:var(--faint);font-size:11.5px">${meta.mtime ? new Date(meta.mtime * 1000).toLocaleString('zh-CN') : ''}</span>
          </div>
          ${renderMarkdown(data.texts[path], baseDir)}
        </article>
      </div>`;
    return {
      crumb: meta.title || path.split('/').pop(),
      sub: meta.group ? meta.group + ' / ' + meta.name : meta.name,
      html,
      mount() {
        $('#back')?.addEventListener('click', () => go('notes'));
        bindTree(path);
        document.querySelectorAll('.doc a[href^="#/notes"]').forEach((a) => {
          a.addEventListener('click', (e) => {
            e.preventDefault();
            const p = decodeURIComponent(a.getAttribute('href').split('path=')[1] || '');
            if (data.texts[p] != null) go('notes', { path: p });
            else toast('这篇笔记不在 notes/ 里：' + p);
          });
        });
      },
    };
  }

  const html = `
    <div class="notes-wrap">
      <aside class="note-tree card" id="tree">${treeHtml(groups, order, null, q, total)}</aside>
      <article class="doc card">
        <div class="empty" style="padding:80px 10px">
          <b>从左边选一篇</b>
          共 ${data.files.length} 篇 Markdown，按目录分组；开头的搜索框可以按标题/路径过滤。
        </div>
      </article>
    </div>`;
  return {
    sub: `${data.files.length} 篇 · ${groups.size} 组`,
    html,
    mount() {
      bindTree(null);
      const search = $('#note-search');
      if (search) {
        search.value = state.notes.q;
        let timer;
        search.addEventListener('input', () => {
          clearTimeout(timer);
          timer = setTimeout(() => {
            state.notes.q = search.value;
            render();
            const el = $('#note-search');
            if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
          }, 160);
        });
      }
    },
  };
}

/* ------------------------------------------------------------ 对话 */
/* 数据来自 notes/conversations/*.md（tools/conversations/export.py 导出）。
   app 只读 md，不含任何大模型调用——能力在电脑上的 agent 那边。 */
function talkSessions() {
  const files = (state.data?.notes?.files || []).filter((f) => f.path.startsWith('notes/conversations/'));
  return files.map((f) => {
    const name = f.name || f.path.split('/').pop();
    const date = (name.match(/^(\d{4}-\d{2}-\d{2})/) || [])[1] || f.title || '';
    const title = (f.title || name).replace(/^\d{4}-\d{2}-\d{2}-/, '').replace(/-[0-9a-f]{8}$/, '');
    return { ...f, date, short: title };
  }).sort((a, b) => (b.path || '').localeCompare(a.path || ''));
}

function splitTurns(md) {
  const lines = String(md || '').split(/\r?\n/);
  const head = [];
  const turns = [];
  let cur = null;
  for (const line of lines) {
    const m = line.match(/^##\s*(我|助手)\s*$/);
    if (m) {
      if (cur) turns.push(cur);
      cur = { role: m[1] === '我' ? 'me' : 'ai', lines: [] };
      continue;
    }
    if (cur) cur.lines.push(line);
    else head.push(line);
  }
  if (cur) turns.push(cur);
  return {
    meta: head.join('\n'),
    turns: turns.map((t) => ({ role: t.role, text: t.lines.join('\n').trim() })).filter((t) => t.text),
  };
}

function pageTalk() {
  const data = state.data.notes;
  const sessions = talkSessions();
  const { path } = state.route.params;

  if (path && data.texts[path] != null) {
    const { meta, turns } = splitTurns(data.texts[path]);
    const head = meta.replace(/^#\s+/, '').trim();
    const html = `
      <div class="talk-wrap narrow">
        <div class="doc-head">
          <button class="btn back" id="back">← 列表</button>
          <span class="tag">${esc(path.split('/').pop())}</span>
        </div>
        <article class="doc card talk-doc">
          <div class="md-head">${renderMarkdown(meta, 'notes/conversations')}</div>
          <div class="bubbles">
            ${turns.map((t) => `
              <div class="bubble ${t.role === 'me' ? 'me' : 'ai'}">
                <div class="who">${t.role === 'me' ? '我' : '助手'}</div>
                <div class="body">${renderMarkdown(t.text, 'notes/conversations')}</div>
              </div>`).join('')}
          </div>
        </article>
      </div>`;
    return {
      crumb: head || path.split('/').pop(),
      sub: `${turns.length} 轮`,
      html,
      mount() { $('#back')?.addEventListener('click', () => go('talk')); },
    };
  }

  if (!sessions.length) {
    return {
      sub: '还没导出',
      html: `<div class="empty card">还没有对话记录。<br>在电脑上跑 <code>python tools/conversations/export.py</code> 就会出现在这里。</div>`,
    };
  }
  const byDate = new Map();
  sessions.forEach((s) => {
    if (!byDate.has(s.date)) byDate.set(s.date, []);
    byDate.get(s.date).push(s);
  });
  const inbox = (data.files || []).filter((f) => f.path.startsWith('notes/inbox/') && !f.path.includes('/done/'));
  const mode = state.data?.meta?.mode;
  const canWrite = mode === 'live';
  const html = `
    <div class="talk-list">
      <div class="talk-compose card">
        <div class="talk-compose-head">给我留一句话</div>
        <textarea id="talk-input" rows="3" placeholder="${canWrite ? '例如：明天提醒我改一下买房页的月供口径' : '现在只在电脑开着 hub-web 服务时能写；App 里可以先看'}"></textarea>
        <div class="talk-compose-foot">
          <span class="hint">存成 <code>notes/inbox/</code>，电脑上开 agent 会话时处理</span>
          <button class="btn primary" id="talk-send" ${canWrite ? '' : 'disabled'}>发送</button>
        </div>
      </div>
      ${inbox.length ? `<div class="talk-day">
        <div class="talk-day-head">待处理 <span class="count">${inbox.length}</span></div>
        ${inbox.map((f) => `<div class="talk-card card pending">
          <div class="talk-title">${esc(f.title || f.name)}</div>
          <div class="talk-sub">${esc(f.path)}</div>
        </div>`).join('')}
      </div>` : ''}
      ${[...byDate.keys()].sort().reverse().map((date) => `
        <div class="talk-day">
          <div class="talk-day-head">${esc(date)} <span class="count">${byDate.get(date).length}</span></div>
          ${byDate.get(date).map((s) => `
            <a class="talk-card card" href="#/talk?path=${encodeURIComponent(s.path)}">
              <div class="talk-title">${esc(s.short)}</div>
              <div class="talk-sub">${esc(s.group || '')} · ${esc((s.name || '').slice(-11, -3))}</div>
            </a>`).join('')}
        </div>`).join('')}
    </div>`;
  return {
    sub: `${sessions.length} 段对话`,
    html,
    mount() {
      const btn = $('#talk-send');
      const input = $('#talk-input');
      if (!btn || !input || !canWrite) return;
      btn.addEventListener('click', async () => {
        const text = input.value.trim();
        if (!text) return toast('先写点什么');
        btn.disabled = true;
        try {
          const resp = await fetch('/api/inbox', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text }),
          });
          const out = await resp.json();
          if (!out.ok) throw new Error(out.error || '写入失败');
          toast('已放进 inbox，电脑上开 agent 时会看到');
          input.value = '';
          state.data = null;
          render();
        } catch (err) {
          toast('没写成功：' + err.message);
          btn.disabled = false;
        }
      });
    },
  };
}

function treeHtml(groups, order, active, q, total) {
  const inner = order.map((g) => {
    const open = q ? true : (state.notes.groupOpen[g] ?? (g === '根目录' || g === 'topics'));
    const items = groups.get(g).map((f) => `
      <a class="tree-item ${active === f.path ? 'active' : ''}" href="#/notes?path=${encodeURIComponent(f.path)}" data-path="${escAttr(f.path)}" title="${escAttr(f.path)}">
        ${esc(f.title)}
      </a>`).join('');
    return `<div class="tree-group ${open ? '' : 'closed'}" data-group="${escAttr(g)}">
      <div class="tree-head"><span class="arrow">▾</span>${esc(g)} <span class="count">${groups.get(g).length}</span></div>
      <div class="tree-items">${items}</div>
    </div>`;
  }).join('');
  return `
    <input type="search" id="note-search" placeholder="搜索标题或路径…" style="width:100%;margin-bottom:10px">
    ${q ? `<div style="font-size:11.5px;color:var(--faint);padding:0 8px 8px">命中 ${total} 篇</div>` : ''}
    ${inner || '<div class="empty">没有匹配的笔记</div>'}`;
}

function bindTree(active) {
  document.querySelectorAll('.tree-head').forEach((el) => {
    el.addEventListener('click', () => {
      const group = el.parentElement;
      const name = group.dataset.group;
      const closed = group.classList.toggle('closed');
      state.notes.groupOpen[name] = !closed;
    });
  });
  document.querySelectorAll('.tree-item').forEach((el) => {
    el.addEventListener('click', (e) => {
      e.preventDefault();
      go('notes', { path: el.dataset.path });
    });
  });
}

/* ------------------------------------------------------------ 健身 */
function pageFitness() {
  const f = state.data.fitness;
  if (f.error) return { html: `<div class="card"><div class="empty">${esc(f.error)}</div></div>` };
  const s = f.summary;
  const series = f.series || [];
  const labels = series.map((p) => mmdd(p.date));
  const weightVals = series.map((p) => p.weight);
  const maVals = (f.moving || []).map((p) => p.weight);
  const parts = f.parts || [];
  const maxPart = Math.max(1, ...parts.map((p) => p.count));
  const cal = f.calendar || [];

  const tiles = [
    ['记录天数', s.days, '连续记录 ' + s.rec_streak + ' 天'],
    ['训练', s.train, '休息 ' + s.rest + ' 天 · 计划 ' + s.plan],
    ['打卡率', s.rate + '%', '近 7 天练 ' + s.recent7 + ' 次'],
    ['连续训练', s.streak + ' 天', '最长 ' + s.best_streak + ' 天'],
    ['当前体重', s.w_last ? n1(s.w_last[1]) + ' 斤' : '—', s.w_last ? s.w_last[0] : ''],
    ['体重变化', s.w_delta ? '-' + Math.abs(s.w_delta).toFixed(1) + ' 斤' : '—', s.w_first ? '起始 ' + n1(s.w_first[1]) : ''],
    ['最低体重', s.w_min ? n1(s.w_min[1]) + ' 斤' : '—', s.w_min ? s.w_min[0] : ''],
    ['训练部位', parts[0] ? parts[0].part : '—', parts[0] ? parts[0].count + ' 次' : ''],
  ];

  const heat = cal.map((c) => {
    const cls = c.status === 'train' ? 'train' : c.status === 'rest' ? 'rest' : c.status === 'plan' ? 'plan' : 'none';
    const label = c.status === 'train' ? '训练' : c.status === 'rest' ? '休息' : c.status === 'plan' ? '计划' : '未记';
    return `<div class="cell ${cls}" title="${esc(c.date)} · ${label}"></div>`;
  }).join('');

  const html = `
    <div class="grid g4" style="margin-bottom:14px">
      ${tiles.map(([k, v, d]) => `<div class="tile"><div class="v">${v}</div><div class="k">${k}</div><div class="d">${esc(d)}</div></div>`).join('')}
    </div>
    <div class="grid g2">
      <div class="card card-pad" style="grid-column:1/-1">
        <div class="card-title">体重曲线 <span class="hint">实线＝体重，虚线＝7 日均线</span></div>
        ${chartLine(labels, [
          { values: weightVals, fill: true, dots: true },
          { values: maVals, dash: '5 4', dots: false, color: '#9db4e8' },
        ], { height: 260, yFmt: (v) => n1(v) })}
      </div>
      <div class="card card-pad">
        <div class="card-title">近 30 天 <span class="hint">绿=训练 · 灰=休息 · 黄=计划</span></div>
        <div class="heat">${heat}</div>
        <div class="legend" style="margin-top:12px">
          <span><i style="background:var(--ok)"></i>训练</span>
          <span><i style="background:#dfe5ef"></i>休息</span>
          <span><i style="background:#f0c96a"></i>计划</span>
          <span><i style="background:#f4f6fa;border:1px solid #edf0f6"></i>未记录</span>
        </div>
      </div>
      <div class="card card-pad">
        <div class="card-title">训练部位 <span class="hint">按日报里的关键词归类</span></div>
        <div class="bars">
          ${parts.map((p) => `<div class="bar-row"><span>${esc(p.part)}</span><div class="bar-track"><div class="bar-fill" style="width:${(p.count / maxPart * 100).toFixed(0)}%"></div></div><span class="n">${p.count}</span></div>`).join('') || '<div class="empty">还没有训练记录</div>'}
        </div>
      </div>
    </div>`;
  return { sub: '从 daily-log.md 派生，不额外维护数据', html };
}

/* ------------------------------------------------------------ 时间线 */
function pageTimeline() {
  const tl = state.data.timeline;
  const days = tl.days || [];
  const flt = state.tl.filter;
  const shown = flt === 'all' ? days : days.filter((d) => d.items.some((i) => i.kind === flt));
  const n = flt === 'all' ? days.reduce((a, d) => a + d.items.length, 0)
    : days.reduce((a, d) => a + d.items.filter((i) => i.kind === flt).length, 0);
  const range = days.length ? `${days[days.length - 1].date} ~ ${days[0].date}` : '';

  const html = `
    <div class="row" style="align-items:center;margin-bottom:14px">
      <div class="seg">
        <button data-flt="all" class="${flt === 'all' ? 'on' : ''}">全部</button>
        <button data-flt="daily" class="${flt === 'daily' ? 'on' : ''}">日常</button>
        <button data-flt="talk" class="${flt === 'talk' ? 'on' : ''}">交流</button>
      </div>
      <span class="hint" style="color:var(--faint);font-size:12px">${shown.length} 天 · ${n} 条 · ${range}</span>
    </div>
    ${shown.map((d) => {
      const items = flt === 'all' ? d.items : d.items.filter((i) => i.kind === flt);
      const open = state.tl.expanded[d.date] || items.length <= 6;
      const vis = open ? items : items.slice(0, 6);
      return `<div class="day ${d.today ? 'today' : ''}">
        <div class="day-date"><div class="d">${d.today ? '今天' : esc(d.date.slice(5))}</div><div class="w">${esc(d.week)} · ${esc(d.date.slice(0, 4))}</div></div>
        <div class="day-card card">
          ${vis.map((i) => `<div class="tl-item">
            <span class="tag ${i.tag === '健身' ? 'train' : ''}">${esc(i.tag)}</span>
            <span class="txt">${i.path ? `<a href="#/notes?path=${encodeURIComponent(i.path)}" data-note="${escAttr(i.path)}">${esc(i.text)}</a>` : esc(i.text)}</span>
          </div>`).join('')}
          ${!open ? `<div class="more" data-more="${d.date}">展开其余 ${items.length - 6} 条 ▾</div>` : ''}
        </div>
      </div>`;
    }).join('') || '<div class="empty">没有记录</div>'}`;

  return {
    sub: '日报 + 交流记录，倒序摊平；点条目直达原笔记',
    html,
    mount() {
      document.querySelectorAll('[data-flt]').forEach((b) => b.addEventListener('click', () => {
        state.tl.filter = b.dataset.flt; render();
      }));
      document.querySelectorAll('[data-more]').forEach((b) => b.addEventListener('click', () => {
        state.tl.expanded[b.dataset.more] = true; render();
      }));
      document.querySelectorAll('.tl-item a[data-note]').forEach((a) => a.addEventListener('click', (e) => {
        e.preventDefault();
        go('notes', { path: a.dataset.note });
      }));
    },
  };
}

/* ------------------------------------------------------------ 账号切换器 */
function accountSelect(kind, accounts, allLabel) {
  const cur = state.sel[kind] || '__all__';
  const opts = [`<option value="__all__" ${cur === '__all__' ? 'selected' : ''}>${allLabel}</option>`]
    .concat(accounts.map((a) => `<option value="${escAttr(a.handle)}" ${cur === a.handle ? 'selected' : ''}>${esc(a.name || a.handle)}（${esc(a.handle)}）</option>`));
  return `<select id="acct-${kind}">${opts.join('')}</select>`;
}

function bindAccount(kind) {
  const el = $('#acct-' + kind);
  if (!el) return;
  el.addEventListener('change', () => { state.sel[kind] = el.value; render(); });
}

/* 顶部账号导航（抖音页用）：每个号一个标签，比下拉更好点、也看得出有几个号。
   flags.status 只有手机端有（handle -> {alive, days}）：把「登录没登录、登了几天」直接印在标签上，
   选哪个号，下面的状态卡和数据就只跟哪个号走。 */
function accountTabs(kind, accounts, allLabel, flags) {
  const cur = state.sel[kind] || '__all__';
  const dead = (flags && flags.dead) || {};
  const status = (flags && flags.status) || null;
  const items = [{ handle: '__all__', name: allLabel, sub: '多号求和', cls: '' }]
    .concat(accounts.map((a) => {
      if (!status) {
        const isDead = !!dead[a.handle];
        return {
          handle: a.handle, name: a.name || a.handle,
          sub: a.handle + (isDead ? ' · 失效' : ''), cls: isDead ? ' bad' : '',
        };
      }
      const st = status[a.handle];
      if (!st) return { handle: a.handle, name: a.name || a.handle, sub: '未登录', cls: ' mute' };
      if (!st.alive) return { handle: a.handle, name: a.name || a.handle, sub: '已失效', cls: ' bad' };
      return {
        handle: a.handle, name: a.name || a.handle,
        sub: '已登录' + (st.days >= 0 ? ' ' + st.days + ' 天' : ''), cls: ' ok',
      };
    }));
  const tabs = items.map((it) => {
    const on = cur === it.handle ? ' on' : '';
    const cls = it.cls || '';
    return `<button type="button" class="acct-tab${on}${cls}" data-h="${escAttr(it.handle)}">`
      + `<span class="n">${esc(it.name)}</span><span class="h${cls}">${esc(it.sub)}</span></button>`;
  }).join('');
  return `<div class="acct-tabs" id="acct-${kind}">${tabs}</div>`;
}

function bindAccountTabs(kind) {
  const box = $('#acct-' + kind);
  if (!box) return;
  box.querySelectorAll('.acct-tab').forEach((el) => {
    el.addEventListener('click', () => {
      state.sel[kind] = el.dataset.h || '__all__';
      render();
    });
  });
}

/* ------------------------------------------------------------ 抖音 */
/**
 * 手机端（Android WebView 桥）才有：每个号的登录态 + 单独同步/重登/解绑。
 * 桌面 hub / 静态快照没有 AndroidRepo，返回 null，页面保持只读。
 */
function dyNative() {
  try {
    if (window.AndroidRepo && typeof AndroidRepo.douyinAccounts === 'function') {
      const raw = AndroidRepo.douyinAccounts();
      const list = JSON.parse(raw || '[]');
      return Array.isArray(list) ? list : null;
    }
  } catch (e) { /* 非 Android 环境 */ }
  return null;
}

/** 账号卡：跟着顶部选中的号走——选单个号只显示这个号，选「全部」才逐个列出；「登录新账号」只放在全部里。 */
function douyinPanel(list, selected) {
  const one = selected && selected !== '__all__';
  const data = one ? list.filter((a) => a.handle === selected) : list;
  const rows = data.map((a) => {
    const cls = a.alive ? 'ok' : (a.local === false ? 'mute' : 'bad');
    const text = a.alive
      ? `已登录${a.days >= 0 ? ' ' + a.days + ' 天' : ''}`
      : (a.local === false ? '本机未登录' : '登录已失效');
    const last = a.last ? ` · 上次 ${esc(a.last)}` : ' · 还没同步过';
    return `
    <div class="dy-row" data-h="${escAttr(a.handle)}">
      <div class="dy-who">
        <span class="n">${esc(a.name || a.handle)}<em>${esc(a.handle)}</em></span>
        <span class="st ${cls}">${text}${last}</span>
      </div>
      <div class="dy-act">
        <button class="btn" data-act="sync" ${a.alive ? '' : 'disabled'}>同步</button>
        <button class="btn" data-act="login">${a.alive ? '重登' : '登录'}</button>
        <button class="btn" data-act="remove">解绑</button>
      </div>
    </div>`;
  }).join('');
  const title = one ? '当前账号' : '账号';
  const hint = one ? '只显示选中的号' : '可单独同步 / 重登 / 解绑';
  // 登录新账号只在「全部账号」里出现一次；单号视图不再重复放
  const foot = one
    ? ''
    : `<div class="dy-foot">
         <button class="btn primary" data-dy="sync-all">同步全部</button>
         <button class="btn" data-dy="login-new">＋ 登录新账号</button>
       </div>`;
  return `
    <div class="card card-pad dy-card" id="dy-panel">
      <div class="card-title">${title} <span class="hint">${hint}</span></div>
      <div class="dy-list">${rows || '<div class="empty">这个号在本机还没登录</div>'}</div>
      ${foot}
    </div>`;
}

function bindDouyinPanel() {
  const box = $('#dy-panel');
  if (!box || !window.AndroidRepo) return;
  box.querySelectorAll('button[data-act]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const row = btn.closest('[data-h]');
      const h = row ? row.dataset.h : '';
      if (!h) return;
      if (btn.dataset.act === 'sync') AndroidRepo.douyinSync(h);
      else if (btn.dataset.act === 'login') AndroidRepo.douyinLogin(h);
      else if (btn.dataset.act === 'remove') AndroidRepo.douyinRemove(h);
    });
  });
  box.querySelectorAll('button[data-dy]').forEach((btn) => {
    btn.addEventListener('click', () => {
      if (btn.dataset.dy === 'sync-all') AndroidRepo.douyinSync('');
      else AndroidRepo.douyinLogin('');
    });
  });
}

function pageDouyin() {
  const dy = state.data.douyin;
  const accounts = dy.accounts || [];
  const native = dyNative();
  const statusMap = {};
  if (native) native.forEach((a) => { statusMap[a.handle] = a; });

  // 标签上的号 = 仓库里有数据的号 + 本机已登录但仓库里还没有的号
  const tabAccounts = accounts.slice();
  if (native) {
    native.forEach((a) => {
      if (!tabAccounts.some((x) => x.handle === a.handle)) tabAccounts.push({ handle: a.handle, name: a.name });
    });
  }
  // 状态卡的数据：本机登录态优先；仓库里有、本机没登的补一条「本机未登录」
  const merged = tabAccounts.map((a) => {
    const n = statusMap[a.handle];
    if (n) return Object.assign({}, n, { local: true });
    return { handle: a.handle, name: a.name || '', alive: false, days: -1, last: '', lastMsg: '', local: false };
  });
  const dead = {};
  if (native) native.forEach((a) => { if (!a.alive) dead[a.handle] = true; });
  // 手机端把每个号的登录天数直接给标签，桌面/静态页没有 status，退回原来的 handle 显示
  const tabsFlags = { dead, status: native ? statusMap : null };

  if (!accounts.length) {
    const tip = '<div class="card card-pad"><div class="empty"><b>还没有抖音数据</b>'
      + (native ? '先登录一个号并点「同步」，这里就会出现作品和播放趋势。'
        : '在桌面 hub 的「抖音」页登录一次并同步，这里就会自动出现。')
      + '</div></div>';
    return {
      sub: native ? `${native.length} 个已登录` : '还没有账号',
      html: (native ? douyinPanel(merged, '__all__') : '') + tip,
      mount() { bindDouyinPanel(); },
    };
  }
  const sel = state.sel.douyin;
  const key = sel && (sel === '__all__' || dy.views[sel]) ? sel : '__all__';
  if (key !== '__all__' && !dy.views[key]) {
    // 本机刚登、这个号还没同步过：只给这个号的空状态，不混别的号的数据
    return {
      sub: '这个号还没同步过',
      html: `${accountTabs('douyin', tabAccounts, '全部账号（融合）', tabsFlags)}
        ${native ? douyinPanel(merged, key) : ''}
        <div class="card card-pad"><div class="empty">这个号本机还没同步过数据 —— 点上面「同步」，抓完就会出现作品和趋势。</div></div>`,
      mount() { bindAccountTabs('douyin'); bindDouyinPanel(); },
    };
  }
  const v = dy.views[key] || {};
  if (v.error) return { html: `<div class="card card-pad"><div class="empty">${esc(v.error)}</div></div>` };
  const works = (v.works || []).slice(0, 40);
  const days = v.days || [];
  const top = (v.top || []).slice(0, 6);
  const trend = v.trend;

  const html = `
    ${accountTabs('douyin', tabAccounts, '全部账号（融合）', tabsFlags)}
    ${native ? douyinPanel(merged, key) : ''}
    <div class="row" style="align-items:center;margin-bottom:14px">
      <span class="pill">${v.count || 0} 条作品 · 更新 ${esc((dy.views[key] || {}).imports?.[0]?.at || '')}</span>
    </div>
    <div class="grid g4" style="margin-bottom:14px">
      <div class="tile accent"><div class="v">${n0(v.total_plays)}</div><div class="k">总播放</div><div class="d">平均 ${n0(v.avg_plays)} / 条</div></div>
      <div class="tile"><div class="v">${n0(v.count)}</div><div class="k">作品数</div><div class="d">最高 ${n0(v.max_plays)}</div></div>
      <div class="tile"><div class="v">${v.finish_weighted != null ? pct(v.finish_weighted) : '—'}</div><div class="k">加权完播率</div><div class="d">5s 完播 ${v.finish5_avg != null ? pct(v.finish5_avg) : '—'}</div></div>
      <div class="tile ok"><div class="v">${pct(v.engage_rate)}</div><div class="k">互动率</div><div class="d">赞 ${n0(v.likes)} · 评 ${n0(v.comments)} · 藏 ${n0(v.collects)}</div></div>
    </div>
    <div class="grid g2" style="margin-bottom:14px">
      <div class="card card-pad" style="grid-column:1/-1">
        <div class="card-title">每日播放 <span class="hint">近 7 天 ${n0(v.plays_last7)} · ${trend == null ? '无环比' : (trend >= 0 ? '+' : '') + pct(trend) + ' vs 前 7 天'}</span></div>
        ${chartBars(days.map((d) => mmdd(d.date)), days.map((d) => d.plays || 0), { height: 230 })}
      </div>
      <div class="card card-pad">
        <div class="card-title">播放 Top ${top.length}</div>
        ${top.map((w, i) => `<div class="recent-row" style="cursor:default">
          <span class="tag ${i === 0 ? 'train' : ''}">${i + 1}</span>
          <span class="name" title="${escAttr(w.title || '')}">${esc(w.title || '(无标题)')}</span>
          <span class="when">${n0(w.plays)} 播放</span>
        </div>`).join('') || '<div class="empty">暂无作品</div>'}
      </div>
      <div class="card card-pad">
        <div class="card-title">账号概况 <span class="hint">粉丝来自同步时的概览</span></div>
        <div class="grid g2" style="grid-template-columns:1fr 1fr">
          <div class="tile"><div class="v">${n0((dy.profiles || {})[key]?.fans)}</div><div class="k">粉丝</div></div>
          <div class="tile"><div class="v">${v.gap_days == null ? '—' : v.gap_days + ' 天'}</div><div class="k">距上次发布</div></div>
          <div class="tile"><div class="v">${n0(v.fans)}</div><div class="k">作品累计涨粉</div></div>
          <div class="tile"><div class="v">${n0(v.profile_visits)}</div><div class="k">主页访问</div></div>
        </div>
      </div>
    </div>
    <div class="card card-pad">
      <div class="card-title">作品明细 <span class="hint">最近 ${works.length} 条，按发布时间倒序</span></div>
      <div class="table-wrap">
        <table class="data">
          <thead><tr><th>标题</th><th class="hide-sm">发布</th><th class="num">播放</th><th class="num hide-sm">完播</th><th class="num hide-sm">5s</th><th class="num">点赞</th><th class="num hide-sm">评论</th><th class="num hide-sm">分享</th><th class="num hide-sm">涨粉</th></tr></thead>
          <tbody>${works.map((w) => `<tr>
            <td class="title" title="${escAttr(w.title || '')}">${esc((w.title || '(无标题)').slice(0, 48))}</td>
            <td class="hide-sm">${esc((w.published_at || '').slice(0, 16))}</td>
            <td class="num">${n0(w.plays)}</td>
            <td class="num hide-sm">${pct(w.finish_rate)}</td>
            <td class="num hide-sm">${pct(w.finish5_rate)}</td>
            <td class="num">${n0(w.likes)}</td>
            <td class="num hide-sm">${n0(w.comments)}</td>
            <td class="num hide-sm">${n0(w.shares)}</td>
            <td class="num hide-sm">${n0(w.fans_delta)}</td>
          </tr>`).join('')}</tbody>
        </table>
      </div>
    </div>`;

  // 标题下那行跟着选中的号走：单个号显示它自己的登录天数，全部才说「几个账号」
  const curSt = key !== '__all__' ? statusMap[key] : null;
  const sub = key === '__all__'
    ? `${accounts.length} 个账号 · 只读同步数据`
    : (curSt
      ? (curSt.alive
        ? `已登录${curSt.days >= 0 ? ' ' + curSt.days + ' 天' : ''}`
        : '登录已失效 · 到 ⚙ 重登这个号')
      : '这个号的数据');
  return {
    sub,
    html,
    mount() {
      bindAccountTabs('douyin');
      bindDouyinPanel();
    },
  };
}

/* ------------------------------------------------------------ 小红书 */
const XHS_LABELS = {
  exposure: '曝光', views: '观看', cover_ctr: '封面点击率', avg_watch: '平均观看时长',
  watch_total: '总观看时长', finish_rate: '完播率', likes: '点赞', comments: '评论',
  collects: '收藏', shares: '分享', fans_net: '净涨粉', fans_new: '新增关注',
  fans_lost: '取消关注', profile_visits: '主页访客', follow_rate: '转粉率',
  posts: '总发布', posts_video: '视频', posts_figure: '图文', danmaku: '弹幕',
};
const XHS_PCT = new Set(['cover_ctr', 'finish_rate', 'follow_rate']);
const XHS_SEC = new Set(['avg_watch', 'watch_total']);

function xhsFmt(k, v) {
  if (v == null) return '—';
  if (XHS_PCT.has(k)) return pct(v);
  if (k === 'watch_total') return v >= 3600 ? (v / 3600).toFixed(1) + ' 小时' : (v / 60).toFixed(0) + ' 分钟';
  if (XHS_SEC.has(k)) return secs(v);
  return n0(v);
}

function pageXhs() {
  const x = state.data.xhs;
  const accounts = x.accounts || [];
  if (!accounts.length) {
    return { html: `<div class="card card-pad"><div class="empty"><b>还没有小红书数据</b>桌面 hub 的「小红书」页登录/导入后，这里就会自动出现。</div></div>` };
  }
  const key = state.sel.xhs && x.views[state.sel.xhs] ? state.sel.xhs : '__all__';
  const v = x.views[key] || {};
  if (v.error) return { html: `<div class="card card-pad"><div class="empty">${esc(v.error)}</div></div>` };
  const days = v.days || [];
  const notes = (v.notes || []).slice(0, 30);
  const summary = v.summary || {};
  const delta = v.delta || {};
  const order = v.metric_order || Object.keys(summary);

  const html = `
    <div class="row" style="align-items:center;margin-bottom:14px">
      ${accountSelect('xhs', accounts, '全部账号（融合）')}
      <span class="pill">${v.count || 0} 条笔记 · 窗口 ${esc((v.window || []).join(' ~ '))}</span>
    </div>
    <div class="grid g4" style="margin-bottom:14px">
      <div class="tile accent"><div class="v">${n0(v.views)}</div><div class="k">总观看</div><div class="d">曝光 ${n0(v.exposure)}</div></div>
      <div class="tile"><div class="v">${n0(v.count)}</div><div class="k">笔记数</div><div class="d">平均 ${n0(v.avg_views)} 观看</div></div>
      <div class="tile"><div class="v">${pct(v.ctr)}</div><div class="k">封面点击率</div><div class="d">按曝光加权</div></div>
      <div class="tile ok"><div class="v">${pct(v.engage_rate)}</div><div class="k">互动率</div><div class="d">赞 ${n0(v.likes)} · 藏 ${n0(v.collects)} · 评 ${n0(v.comments)}</div></div>
    </div>
    <div class="card card-pad" style="margin-bottom:14px">
      <div class="card-title">每日观看 <span class="hint">近 7 天 ${n0(v.views_last7)} · ${v.trend == null ? '无环比' : (v.trend >= 0 ? '+' : '') + pct(v.trend) + ' vs 前 7 天'}</span></div>
      ${chartLine(days.map((d) => mmdd(d.date)), [{ values: days.map((d) => d.views || 0), fill: true }], { height: 220, zero: true })}
    </div>
    <div class="grid g2" style="margin-bottom:14px">
      <div class="card card-pad" style="grid-column:1/-1">
        <div class="card-title">近 30 天指标 <span class="hint">环比是与前一个 30 天窗口相比</span></div>
        <div class="grid g3">
          ${order.map((k) => {
            const dv = delta[k];
            const badge = dv == null ? '' : `<span class="tag ${dv >= 0 ? 'train' : 'bad'}">${dv >= 0 ? '+' : ''}${pct(dv)}</span>`;
            return `<div class="tile" style="padding:11px 13px"><div class="v" style="font-size:18px">${xhsFmt(k, summary[k])}</div>
              <div class="k">${esc(XHS_LABELS[k] || k)} ${badge}</div></div>`;
          }).join('')}
        </div>
        <div style="margin-top:14px;padding-top:12px;border-top:1px solid var(--line-2);font-size:12px;color:var(--muted);line-height:1.9">
          账号：${accounts.map((a) => esc((a.name || '') + '（' + a.handle + '）')).join('、')}<br>
          指标来自小红书后台的「观看 / 互动 / 涨粉 / 发布」导出表，比率型按权重合并；最近发布 ${esc((v.last_publish || '—').slice(0, 16))}${v.gap_days != null ? `（${v.gap_days} 天前）` : ''}
        </div>
      </div>
    </div>
    <div class="card card-pad">
      <div class="card-title">笔记明细 <span class="hint">按发布时间倒序，最多 30 条</span></div>
      <div class="table-wrap">
        <table class="data">
          <thead><tr><th>标题</th><th class="hide-sm">发布</th><th class="num hide-sm">曝光</th><th class="num">观看</th><th class="num hide-sm">点击率</th><th class="num">点赞</th><th class="num hide-sm">收藏</th><th class="num hide-sm">评论</th><th class="num hide-sm">涨粉</th></tr></thead>
          <tbody>${notes.map((n) => `<tr>
            <td class="title" title="${escAttr(n.title || '')}">${esc((n.title || '(无标题)').slice(0, 40))}</td>
            <td class="hide-sm">${esc((n.published_at || '').slice(0, 16))}</td>
            <td class="num hide-sm">${n0(n.exposure)}</td>
            <td class="num">${n0(n.views)}</td>
            <td class="num hide-sm">${pct(n.cover_ctr)}</td>
            <td class="num">${n0(n.likes)}</td>
            <td class="num hide-sm">${n0(n.collects)}</td>
            <td class="num hide-sm">${n0(n.comments)}</td>
            <td class="num hide-sm">${n0(n.fans)}</td>
          </tr>`).join('')}</tbody>
        </table>
      </div>
    </div>`;

  return { sub: `${accounts.length} 个账号 · 只读`, html, mount() { bindAccount('xhs'); } };
}

/* ------------------------------------------------------------ 账单 */
function pageBills() {
  const b = state.data.bills;
  const accounts = b.accounts || [];
  if (!accounts.length) {
    return { html: `<div class="card card-pad"><div class="empty"><b>还没有账单数据</b>桌面 hub 的「账单」页导入后，这里就会自动出现。</div></div>` };
  }
  const key = state.sel.bills && b.views[state.sel.bills] ? state.sel.bills : '__all__';
  const v = b.views[key] || {};
  if (v.error) return { html: `<div class="card card-pad"><div class="empty">${esc(v.error)}</div></div>` };
  const days = v.days || [];
  const txns = (v.txns || []).slice(0, 60);
  const cats = (v.categories || []).slice(0, 8);
  const maxCat = Math.max(1, ...cats.map((c) => c[1]));
  const opts = [`<option value="__all__" ${key === '__all__' ? 'selected' : ''}>全部账户</option>`]
    .concat(accounts.map((a) => `<option value="${escAttr(a.id)}" ${key === a.id ? 'selected' : ''}>${esc(a.name || a.id)}</option>`));

  const html = `
    <div class="row" style="align-items:center;margin-bottom:14px">
      <select id="acct-bills">${opts.join('')}</select>
      <span class="pill">本月 ${esc(v.month || '')} · 近 30 天 ${esc((v.window || []).join(' ~ '))}</span>
    </div>
    <div class="grid g4" style="margin-bottom:14px">
      <div class="tile bad"><div class="v">${money(v.month_expense)}</div><div class="k">本月支出</div></div>
      <div class="tile accent"><div class="v">${money(v.expense)}</div><div class="k">近 30 天支出</div><div class="d">日均 ${money(v.avg_day)}</div></div>
      <div class="tile ok"><div class="v">${money(v.income)}</div><div class="k">近 30 天收入</div></div>
      <div class="tile"><div class="v">${n0(v.count)}</div><div class="k">笔数</div><div class="d">共 ${n0(v.all_count)} 笔 · 排除 ${n0(v.excluded_count)}</div></div>
    </div>
    <div class="grid g2" style="margin-bottom:14px">
      <div class="card card-pad" style="grid-column:1/-1">
        <div class="card-title">每日支出 <span class="hint">近 30 天</span></div>
        ${chartBars(days.map((d) => mmdd(d.date)), days.map((d) => d.expense || 0), { height: 210, yFmt: (v2) => '¥' + n0(v2) })}
      </div>
      <div class="card card-pad">
        <div class="card-title">分类占比</div>
        <div class="bars">
          ${cats.map(([name, amt]) => `<div class="bar-row"><span>${esc(name)}</span><div class="bar-track"><div class="bar-fill" style="width:${(amt / maxCat * 100).toFixed(0)}%"></div></div><span class="n">${money(amt)}</span></div>`).join('') || '<div class="empty">暂无支出</div>'}
        </div>
      </div>
      <div class="card card-pad">
        <div class="card-title">说明</div>
        <div style="font-size:12.5px;color:var(--muted);line-height:1.9">
          <div>· 账户：${accounts.map((a) => esc(a.name || a.id)).join('、')}</div>
          <div>· 网页版只读，改分类/备注/排除请在桌面 hub 操作</div>
          <div>· 统计口径与 hub 一致：排除标记的笔数不计入</div>
        </div>
      </div>
    </div>
    <div class="card card-pad">
      <div class="card-title">明细 <span class="hint">最近 ${txns.length} 笔（共 ${n0((v.txns || []).length)}）</span></div>
      <div class="table-wrap">
        <table class="data">
          <thead><tr><th>时间</th><th>对方</th><th class="hide-sm">商品</th><th>分类</th><th class="hide-sm">账户</th><th class="num">金额</th></tr></thead>
          <tbody>${txns.map((t) => `<tr style="${t.excluded ? 'opacity:.45' : ''}">
            <td>${esc((t.time || t.date || '').slice(0, 16))}</td>
            <td class="title">${esc(t.counterparty_name || t.counterparty || '')}</td>
            <td class="title hide-sm">${esc(t.item || '')}</td>
            <td><span class="tag">${esc(t.category || '其他')}</span></td>
            <td class="hide-sm">${esc(t.account_name || '')}</td>
            <td class="num" style="color:${t.direction === 'income' ? 'var(--ok)' : 'var(--text)'}">${t.direction === 'income' ? '+' : '-'}${money(t.amount)}</td>
          </tr>`).join('')}</tbody>
        </table>
      </div>
    </div>`;

  return { sub: `${accounts.length} 个账户 · 只读`, html,
    mount() { $('#acct-bills')?.addEventListener('change', (e) => { state.sel.bills = e.target.value; render(); }); } };
}

/* ------------------------------------------------------------ 刷题 */
function quizSubjects() {
  return state.data.quiz?.subjects || [];
}

function pageQuiz() {
  const subjects = quizSubjects();
  if (!subjects.length) return { html: `<div class="card"><div class="empty">还没有题库</div></div>` };

  if (state.quiz && state.quiz.finished) return quizResultHtml();

  if (!state.quiz) {
    const html = `
      <div class="card card-pad quiz-shell">
        <div class="card-title">选一组题开始</div>
        <div class="quiz-setup">
          <select id="q-subject">${subjects.map((s) => `<option value="${escAttr(s.subject)}">${esc(s.subject)}（${s.total} 题 · 错 ${s.wrong}）</option>`).join('')}</select>
          <select id="q-mode">
            <option value="all">全部题目</option>
            <option value="wrong">只刷错题</option>
            <option value="due">到期复习</option>
          </select>
          <select id="q-count"><option>10</option><option>20</option><option>30</option><option>50</option></select>
          <button class="btn primary" id="q-start">开始</button>
        </div>
        <div style="margin-top:18px;color:var(--muted);font-size:12.5px;line-height:1.9">
          ${window.HubAndroid
            ? '· 答对答错都会写回手机本地的 <code>notes/kb/&lt;科目&gt;/review.json</code><br>· 点顶部的 ☁ 同步时，会先提交这次进度，再拉取最新笔记与数据'
            : '· 答对答错都会写回 <code>notes/kb/&lt;科目&gt;/review.json</code>，和桌面 hub、study.py 共用进度<br>· 静态快照模式下进度只存在当前浏览器（localStorage），不写仓库'}
        </div>
      </div>
      <div class="card card-pad quiz-shell" style="margin-top:14px">
        <div class="card-title">各科目进度</div>
        ${subjects.map((s) => `<div class="bar-row" style="grid-template-columns:90px 1fr 120px;margin-bottom:10px">
          <span>${esc(s.subject)}</span>
          <div class="bar-track"><div class="bar-fill" style="width:${s.total ? (s.seen / s.total * 100).toFixed(0) : 0}%"></div></div>
          <span class="n">${s.seen}/${s.total} · 错 ${s.wrong}</span>
        </div>`).join('')}
      </div>`;
    return { sub: '选择题即时判分', html, mount() { $('#q-start')?.addEventListener('click', startQuiz); } };
  }

  const q = state.quiz.pool[state.quiz.idx];
  if (!q) return quizResultHtml();
  const answered = state.quiz.answers[q.id];
  const opts = Object.entries(q.options || {});
  const html = `
    <div class="card q-card quiz-shell">
      <div class="q-meta">
        <span class="tag">${esc(state.quiz.subject)}</span>
        <span class="tag">${esc(q.chapter || '未分章')}</span>
        <span class="spacer"></span>
        <span class="quiz-progress">${state.quiz.idx + 1} / ${state.quiz.pool.length} · 对 ${state.quiz.correct}</span>
      </div>
      <div class="progress-line" style="margin-bottom:16px"><i style="width:${((state.quiz.idx) / state.quiz.pool.length * 100).toFixed(1)}%"></i></div>
      <div class="q-text">${esc(q.q)}</div>
      ${opts.map(([k, val]) => {
        let cls = 'opt';
        if (answered) {
          cls += ' locked';
          if (k === q.answer) cls += ' right';
          else if (k === answered.pick) cls += ' wrongpick';
          else cls += ' dim';
        }
        return `<div class="${cls}" data-pick="${escAttr(k)}"><span class="idx">${esc(k)}</span><span>${esc(val)}</span></div>`;
      }).join('')}
      ${answered ? `<div class="analysis">
        <b>${answered.ok ? '答对了' : '答错了'} · 正确答案 ${esc(q.answer)}</b>
        <div style="margin-top:6px;white-space:pre-wrap">${esc(q.analysis || '（这道题没有解析）')}</div>
      </div>` : ''}
      <div class="quiz-foot">
        <button class="btn" id="q-quit">结束</button>
        <span class="spacer"></span>
        ${answered ? `<button class="btn primary" id="q-next">${state.quiz.idx + 1 >= state.quiz.pool.length ? '看结果' : '下一题 →'}</button>` : ''}
      </div>
    </div>`;
  return {
    crumb: state.quiz.subject,
    sub: state.quiz.modeLabel,
    html,
    mount() {
      document.querySelectorAll('.opt').forEach((el) => el.addEventListener('click', () => answerQuiz(el.dataset.pick)));
      $('#q-next')?.addEventListener('click', nextQuiz);
      $('#q-quit')?.addEventListener('click', () => { state.quiz = null; render(); });
    },
  };
}

function startQuiz() {
  const subject = $('#q-subject').value;
  const mode = $('#q-mode').value;
  const count = Number($('#q-count').value);
  const s = quizSubjects().find((x) => x.subject === subject);
  if (!s) return;
  let pool = s.questions.slice();
  const today = new Date().toISOString().slice(0, 10);
  if (mode === 'wrong') {
    pool = pool.filter((q) => {
      const st = s.review[q.id];
      return st && st.wrong > 0 && !st.mastered;
    });
  } else if (mode === 'due') {
    pool = pool.filter((q) => {
      const st = s.review[q.id];
      return st && st.wrong > 0 && !st.mastered && (st.due || '9999') <= today;
    });
  }
  if (!pool.length) { toast(mode === 'all' ? '这个科目没有题' : '没有符合条件的题'); return; }
  pool = pool.sort(() => Math.random() - 0.5).slice(0, Math.min(count, pool.length));
  state.quiz = {
    subject, mode, pool, idx: 0, correct: 0, answers: {}, finished: false,
    modeLabel: { all: '全部题目', wrong: '只刷错题', due: '到期复习' }[mode],
  };
  render();
}

async function answerQuiz(pick) {
  const qz = state.quiz;
  if (!qz || qz.answers[qz.pool[qz.idx].id]) return;
  const q = qz.pool[qz.idx];
  const ok = pick === q.answer;
  qz.answers[q.id] = { pick, ok };
  if (ok) qz.correct++;

  const subject = quizSubjects().find((s) => s.subject === qz.subject);
  if (window.HubAndroid) {
    try {
      const res = JSON.parse(window.AndroidRepo.answer(qz.subject, q.id, ok));
      if (res.ok && subject) {
        subject.review[q.id] = res.state;
        subject.seen = subject.questions.filter((qq) => subject.review[qq.id]).length;
        subject.wrong = subject.questions.filter((qq) => {
          const st = subject.review[qq.id];
          return st && st.wrong > 0 && !st.mastered;
        }).length;
      }
    } catch (e) {
      toast('保存失败：' + e.message);
    }
    render();
    return;
  }
  if (state.data.meta.mode === 'live') {
    try {
      const r = await fetch('api/answer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subject: qz.subject, id: q.id, ok }),
      });
      const res = await r.json();
      if (res.ok && subject) {
        subject.review[q.id] = res.state;
        if (res.subject) { subject.seen = res.subject.seen; subject.wrong = res.subject.wrong; }
      }
    } catch (e) { toast('写回失败，进度可能没保存'); }
  } else {
    const local = localReview();
    local[qz.subject] = local[qz.subject] || {};
    local[qz.subject][q.id] = Object.assign({}, local[qz.subject][q.id] || {}, {
      seen: ((local[qz.subject][q.id] || {}).seen || 0) + 1,
      wrong: ((local[qz.subject][q.id] || {}).wrong || 0) + (ok ? 0 : 1),
      last: new Date().toISOString().slice(0, 10),
    });
    saveLocalReview(local);
    if (subject) subject.review[q.id] = local[qz.subject][q.id];
  }
  render();
}

function nextQuiz() {
  const qz = state.quiz;
  if (qz.idx + 1 >= qz.pool.length) { qz.finished = true; render(); return; }
  qz.idx++;
  render();
}

function quizResultHtml() {
  const qz = state.quiz;
  const total = qz.pool.length;
  const rate = total ? Math.round((qz.correct / total) * 100) : 0;
  const html = `
    <div class="card card-pad quiz-shell">
      <div class="card-title">这一组做完了</div>
      <div class="grid g3">
        <div class="tile ok"><div class="v">${qz.correct}</div><div class="k">答对</div></div>
        <div class="tile bad"><div class="v">${total - qz.correct}</div><div class="k">答错</div></div>
        <div class="tile accent"><div class="v">${rate}%</div><div class="k">正确率</div></div>
      </div>
      <div class="quiz-foot">
        <button class="btn" id="q-again">再选一组</button>
        <span class="spacer"></span>
        <button class="btn primary" id="q-stats">看统计</button>
      </div>
    </div>`;
  return {
    crumb: qz.subject,
    html,
    mount() {
      $('#q-again')?.addEventListener('click', () => { state.quiz = null; render(); });
      $('#q-stats')?.addEventListener('click', () => { state.quiz = null; go('stats'); });
    },
  };
}

/* ------------------------------------------------------------ 统计 */
function pageStats() {
  const subjects = quizSubjects();
  if (!subjects.length) return { html: `<div class="card"><div class="empty">还没有题库</div></div>` };
  const totalQ = subjects.reduce((a, s) => a + s.total, 0);
  const totalSeen = subjects.reduce((a, s) => a + s.seen, 0);
  const totalWrong = subjects.reduce((a, s) => a + s.wrong, 0);
  const totalMastered = subjects.reduce((a, s) => a + (s.mastered || 0), 0);

  const html = `
    <div class="grid g4" style="margin-bottom:14px">
      <div class="tile accent"><div class="v">${totalQ}</div><div class="k">题目总数</div></div>
      <div class="tile"><div class="v">${totalSeen}</div><div class="k">练过</div><div class="d">${totalQ ? Math.round(totalSeen / totalQ * 100) : 0}% 覆盖</div></div>
      <div class="tile ok"><div class="v">${totalMastered}</div><div class="k">已掌握</div></div>
      <div class="tile bad"><div class="v">${totalWrong}</div><div class="k">待攻克错题</div></div>
    </div>
    <div class="card card-pad">
      <div class="card-title">按科目 <span class="hint">练过 = 至少答过一次</span></div>
      <div class="table-wrap">
        <table class="data">
          <thead><tr><th>科目</th><th class="num">题目</th><th class="num">练过</th><th class="num">掌握</th><th class="num">错题</th><th style="width:200px">覆盖</th></tr></thead>
          <tbody>${subjects.map((s) => `<tr>
            <td>${esc(s.subject)}</td>
            <td class="num">${s.total}</td>
            <td class="num">${s.seen}</td>
            <td class="num">${s.mastered || 0}</td>
            <td class="num" style="color:${s.wrong ? 'var(--bad)' : 'inherit'}">${s.wrong}</td>
            <td><div class="progress-line"><i style="width:${s.total ? (s.seen / s.total * 100).toFixed(0) : 0}%"></i></div></td>
          </tr>`).join('')}</tbody>
        </table>
      </div>
    </div>`;
  return { sub: '刷题进度与桌面 hub 共用同一份 review.json', html };
}

/* ------------------------------------------------------------ 我的（手机壳） */
function meJson(raw, dflt) {
  try {
    const v = JSON.parse(raw == null || raw === '' ? 'null' : raw);
    return v == null ? dflt : v;
  } catch (e) { return dflt; }
}
function meStatus() {
  if (!window.AndroidRepo || typeof AndroidRepo.status !== 'function') return {};
  return meJson(AndroidRepo.status(), {}) || {};
}
function meEvents() {
  if (!window.AndroidRepo || typeof AndroidRepo.events !== 'function') return [];
  const v = meJson(AndroidRepo.events(), []);
  return Array.isArray(v) ? v : [];
}
function meToday() {
  const d = new Date();
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}
/** 今天的只显示时分，别的显示 月-日 时:分 */
function meClock(t) {
  const s = String(t || '');
  if (!s) return '';
  return s.slice(0, 10) === meToday() ? s.slice(11, 16) : s.slice(5, 16);
}

function meTiles(st) {
  const dirty = Number(st.dirty || 0);
  const run = !!(st.syncing || st.douyinSyncing);
  const fail = !!st.lastError;
  const last = st.lastSync ? meClock(st.lastSync) : '还没同步';
  return `
    <div class="tile ${fail ? 'bad' : 'accent'}">
      <div class="v">${esc(last)}</div>
      <div class="k">上次同步</div>
      <div class="d">${run ? '正在跑…' : (fail ? '上次没成功' : (st.lastSync ? '本机与仓库已对齐' : '还没同步过'))}</div>
    </div>
    <div class="tile ${dirty ? '' : 'ok'}">
      <div class="v">${dirty ? dirty + ' 个' : '干净'}</div>
      <div class="k">待推送</div>
      <div class="d">${dirty ? '下次 ☁ 一起推' : '没有本地改动'}</div>
    </div>
    <div class="tile">
      <div class="v">${st.versionName ? 'v' + esc(st.versionName) : '—'}</div>
      <div class="k">本机版本</div>
      <div class="d">code ${esc(st.versionCode ?? '—')}</div>
    </div>`;
}

const ME_KIND = { sync: '同步', douyin: '抖音', update: '更新', inbox: '收件箱' };

function meLogHtml(list) {
  if (!list.length) {
    return `<div class="empty me-empty">还没有同步消息。<br>点上面的「立即同步」或右上角 ☁，每次跑完都会留一条在这儿。</div>`;
  }
  let html = '', lastDay = '';
  list.forEach((e) => {
    const day = String(e.t || '').slice(0, 10);
    if (day && day !== lastDay) {
      html += `<div class="me-day">${esc(day === meToday() ? '今天 · ' + day : day)}</div>`;
      lastDay = day;
    }
    const ok = e.ok !== false;
    const kind = ME_KIND[e.kind] || '记录';
    const detail = e.detail ? `<div class="me-ev-detail">${esc(String(e.detail).trim())}</div>` : '';
    html += `
      <div class="me-ev ${ok ? 'ok' : 'bad'}">
        <span class="me-ev-dot"></span>
        <div class="me-ev-main">
          <div class="me-ev-text">${esc(e.text || '')}</div>
          ${detail}
        </div>
        <div class="me-ev-side">
          <span class="me-ev-kind">${kind}</span>
          <span class="me-ev-time">${esc(meClock(e.t))}</span>
        </div>
      </div>`;
  });
  return html;
}

function meRows(st) {
  const dy = Number(st.douyinCount || 0);
  const install = st.canInstall
    ? '<span class="me-row-s ok">已允许安装应用</span>'
    : '<span class="me-row-s bad">未允许 · 更新时系统会拦一下</span>';
  return `
    <div class="me-row" data-me="settings">
      <span class="me-row-ico">⚙</span>
      <div class="me-row-main">
        <div class="me-row-t">同步设置</div>
        <div class="me-row-s">${esc(st.repo || '未配置')} · ${esc(st.branch || 'main')} · Token · ${st.autoUpdate ? '自动检查更新已开' : '自动检查更新已关'}</div>
      </div>
      <span class="me-row-go">›</span>
    </div>
    <div class="me-row" data-me="install">
      <span class="me-row-ico">⤓</span>
      <div class="me-row-main"><div class="me-row-t">安装权限</div>${install}</div>
      <span class="me-row-go">›</span>
    </div>
    <div class="me-row" data-me="douyin">
      <span class="me-row-ico">♪</span>
      <div class="me-row-main">
        <div class="me-row-t">抖音账号</div>
        <div class="me-row-s">${dy} 个号已登录 · 可单独同步 / 重登 / 解绑</div>
      </div>
      <span class="me-row-go">›</span>
    </div>
    <div class="me-row" data-me="features">
      <span class="me-row-ico">▦</span>
      <div class="me-row-main">
        <div class="me-row-t">功能拓展</div>
        <div class="me-row-s">抖音 ${state.features.douyin ? '开' : '关'} · 小红书 ${state.features.xhs ? '开' : '关'} · 关闭不影响历史数据</div>
      </div>
      <span class="me-row-go">›</span>
    </div>
    <div class="me-row" data-me="update">
      <span class="me-row-ico">⬆</span>
      <div class="me-row-main">
        <div class="me-row-t">检查更新</div>
        <div class="me-row-s">当前 v${esc(st.versionName || '—')}${st.lastCheck ? ' · 上次 ' + esc(meClock(st.lastCheck)) : ''}</div>
      </div>
      <span class="me-row-go">›</span>
    </div>`;
}

function meDiag(st) {
  const rows = [];
  if (st.lastError) rows.push(['上次同步失败', st.lastError]);
  if (st.lastApk) rows.push(['上次下载的更新包', st.lastApk]);
  if (st.lastCrash) rows.push(['上次崩溃', st.lastCrash + '（已记 data/hub/crash.log，下次同步带回电脑）']);
  if (!rows.length) return '';
  return `
    <div class="card card-pad me-diag">
      <div class="card-title">诊断 <span class="hint">出问题把这几行发我</span></div>
      ${rows.map(([k, v]) => `<div class="me-diag-row"><b>${esc(k)}</b><span>${esc(v)}</span></div>`).join('')}
    </div>`;
}

/** 只重画数据区（不动输入焦点/滚动位置），给定时器和原生事件用。 */
function mePaint() {
  if (state.route.key !== 'me') return;
  const log = $('#me-log');
  if (!log) return;
  const st = meStatus();
  const tiles = $('#me-tiles');
  if (tiles) tiles.innerHTML = meTiles(st);
  const html = meLogHtml(meEvents());
  if (log._html !== html) { log.innerHTML = html; log._html = html; }
  const run = $('#me-running');
  if (run) {
    const on = !!(st.syncing || st.douyinSyncing);
    run.style.display = on ? 'flex' : 'none';
    const txt = $('#me-running-text');
    if (txt && on) txt.textContent = st.douyinSyncing ? '抖音正在抓取数据…' : '☁ 正在同步 GitHub…';
  }
}

function bindMe() {
  const sync = $('#me-sync');
  if (sync) sync.addEventListener('click', () => {
    AndroidRepo.requestSync();
    toast('已开始同步，顶部胶囊会显示进度');
    setTimeout(mePaint, 700);
  });
  const upd = $('#me-update');
  if (upd) upd.addEventListener('click', () => AndroidRepo.checkUpdate());
  const set = $('#me-settings');
  if (set) set.addEventListener('click', () => AndroidRepo.openSettings());

  const contact = $('#me-contact');
  if (contact) contact.addEventListener('click', () => {
    const box = $('#me-contact-info');
    if (box) box.style.display = box.style.display === 'none' ? 'block' : 'none';
  });

  document.querySelectorAll('[data-me]').forEach((row) => {
    row.addEventListener('click', () => {
      const k = row.dataset.me;
      if (k === 'settings') AndroidRepo.openSettings();
      else if (k === 'install') {
        if (typeof AndroidRepo.openInstallSettings === 'function') AndroidRepo.openInstallSettings();
        else AndroidRepo.openSettings();
      } else if (k === 'douyin') go('douyin');
      else if (k === 'features') showFeatureModal(false);
      else if (k === 'update') AndroidRepo.checkUpdate();
    });
  });

  // 清空记录：弹原生确认框（WebView 里没有 confirm），确认后原生回推重画
  const clear = $('#me-clear');
  if (clear) {
    clear.addEventListener('click', () => {
      if (typeof AndroidRepo.clearEvents === 'function') AndroidRepo.clearEvents();
      else toast('这个版本不支持清空');
    });
  }
  mePaint();
  window.__meTick = setInterval(mePaint, 2500);
}

function pageMe() {
  if (!window.AndroidRepo) {
    return {
      sub: '仅手机 App',
      html: `<div class="card card-pad"><div class="empty"><b>这个页面只存在于手机 App</b>浏览器版没有本机同步记录和安装设置。</div></div>`,
    };
  }
  const st = meStatus();
  return {
    sub: '同步记录 · 设置',
    html: `
      <div class="me-hero">
        <div class="me-hero-top">
          <div class="me-logo">◈</div>
          <div class="me-id">
            <div class="me-name">第二大脑${st.versionName ? `<span class="me-ver">v${esc(st.versionName)}</span>` : ''}</div>
            <div class="me-meta">${esc(st.repo || '未配置')} · ${esc(st.branch || 'main')}</div>
          </div>
          <span class="pill">半离线</span>
        </div>
        <div class="me-actions">
          <button class="btn primary" id="me-sync">☁ 立即同步</button>
          <button class="btn" id="me-update">⬆ 检查更新</button>
          <button class="btn" id="me-settings">⚙ 设置</button>
        </div>
      </div>
      <div class="grid me-tiles" id="me-tiles">${meTiles(st)}</div>
      <div class="me-running" id="me-running" style="display:none"><i class="spinner"></i><span id="me-running-text">正在同步…</span></div>
      <div class="card card-pad">
        <div class="card-title"><span>同步消息 <span class="hint">胶囊飘完就没了，记录都留这</span></span><button class="btn me-clear" id="me-clear">清空</button></div>
        <div class="me-log" id="me-log">${meLogHtml(meEvents())}</div>
      </div>
      <div class="card card-pad">
        <div class="card-title">设置 <span class="hint">点一行就能改</span></div>
        <div class="me-rows">${meRows(st)}</div>
      </div>
      ${meDiag(st)}
      <div class="me-note">数据只存在这台手机的 App 私有目录，同步只经过你自己的 GitHub 仓库。</div>
      <div class="card card-pad">
        <div class="card-title">反馈 <span class="hint">用着有问题、想要新功能都可以说</span></div>
        <button class="btn primary" id="me-contact">联系我们</button>
        <div id="me-contact-info" style="display:none;margin-top:10px;line-height:1.9">
          微信：<b>jack9527xz</b><br>
          邮箱：<b>1060061749@qq.com</b><br>
          <span class="hint">加微信或发邮件，看到会回。</span>
        </div>
      </div>`,
    mount() { bindMe(); },
  };
}

/* ------------------------------------------------------------ 启动 */
function bindGlobal() {
  // 原生每记一条同步消息就调一次；页面停在「我的」时立刻重画，别的不受影响
  window.__hubEventsUpdated = () => { try { mePaint(); } catch (e) { /* 页面还没起来 */ } };
  document.addEventListener('click', (e) => {
    const nav = e.target.closest('[data-go]');
    if (nav) { go(nav.dataset.go); }
  });
  $('#btn-refresh').addEventListener('click', async () => {
    try { state.data = await loadData(); toast('已刷新'); render(); }
    catch (err) { toast('刷新失败：' + err.message); }
  });
  window.addEventListener('hashchange', render);
}

async function boot() {
  loadFeatures();
  bindGlobal();
  renderNav();
  try {
    state.data = await loadData();
  } catch (err) {
    $('#view').innerHTML = `<div class="card card-pad"><div class="empty">
      <b>读不到数据</b>${esc(err.message)}<br><br>
      在仓库根目录运行：<code>python tools/hub-web/server.py --open</code>
    </div></div>`;
    setChrome('出错了', '');
    return;
  }
  if (!location.hash) location.hash = '#/home';
  render();
  // 第一次进 App（安装后第一次启动）先让用户选模块，默认全开
  if (window.AndroidRepo && !state.features.onboarded) showFeatureModal(true);
}

boot();
