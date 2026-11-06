'use strict';

/* =====================================================================
 * AI-Mind · web — 抖音 / 小红书数据
 * 数据来自 server.py 的 /api/bundle；没有服务端时退回 data/bundle.json 静态快照。
 * ===================================================================== */

const PAGES = [
  { key: 'douyin', ico: '♪', name: '抖音',   sub: '作品与趋势' },
  { key: 'xhs',    ico: '✦', name: '小红书', sub: '笔记与指标' },
];

const state = {
  data: null,
  route: { key: 'douyin', params: {} },
  sel: { douyin: '__all__', xhs: '__all__' },
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
  return { key: PAGES.some((p) => p.key === path) ? path : 'douyin', params };
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
    return data;
  }
}

/* 静态模式下刷题进度只存浏览器本地 */

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
  $('#side-foot').innerHTML = `数据更新 ${esc(state.data?.meta?.generated_at || '—')}<br>${where}`;
}

async function render() {
  state.route = parseHash();
  const key = state.route.key;
  const page = PAGES.find((p) => p.key === key) || PAGES[0];
  renderNav();
  const view = $('#view');
  const pages = { douyin: pageDouyin, xhs: pageXhs };
  const result = (pages[key] || pageDouyin)();
  setChrome(page.name + (result.crumb ? ' · ' + result.crumb : ''), result.sub || page.sub);
  view.innerHTML = result.html;
  if (result.mount) result.mount();
  window.scrollTo(0, 0);
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

/* ------------------------------------------------------------ 抖音 */
function pageDouyin() {
  const dy = state.data.douyin;
  const accounts = dy.accounts || [];
  if (!accounts.length) {
    return {
      html: `<div class="card card-pad"><div class="empty"><b>还没有抖音账号数据</b>在桌面 hub 的「抖音」页登录一次并同步，这里就会自动出现。</div></div>`,
    };
  }
  const key = state.sel.douyin && dy.views[state.sel.douyin] ? state.sel.douyin : '__all__';
  const v = dy.views[key] || {};
  if (v.error) return { html: `<div class="card card-pad"><div class="empty">${esc(v.error)}</div></div>` };
  const works = (v.works || []).slice(0, 40);
  const days = v.days || [];
  const top = (v.top || []).slice(0, 6);
  const trend = v.trend;

  const html = `
    <div class="row" style="align-items:center;margin-bottom:14px">
      ${accountSelect('douyin', accounts, '全部账号（融合）')}
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

  return { sub: `${accounts.length} 个账号 · 只读同步数据`, html, mount() { bindAccount('douyin'); } };
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
/* ------------------------------------------------------------ 启动 */
function bindGlobal() {
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
  bindGlobal();
  renderNav();
  try {
    state.data = await loadData();
  } catch (err) {
    $('#view').innerHTML = `<div class="card card-pad"><div class="empty">
      <b>读不到数据</b>${esc(err.message)}<br><br>
      在仓库根目录运行：<code>python hub-web/server.py --root &lt;数据仓库&gt; --open</code>
    </div></div>`;
    setChrome('出错了', '');
    return;
  }
  if (!location.hash) location.hash = '#/douyin';
  render();
}

boot();
