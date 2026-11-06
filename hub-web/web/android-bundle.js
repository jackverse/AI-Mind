/* 把手机本地仓库里的 data/hub/ 现算成与 server.py 相同结构的 bundle（只含抖音 / 小红书）。
 * 只在 Android 壳里生效（window.AndroidRepo 由原生注入）；网页端不加载它。
 * 口径对齐 hub/core/{douyin,xhs}.py。
 */
(function () {
  if (!window.AndroidRepo) return;

  var RAW = { files: {}, meta: {} };
  try { RAW = JSON.parse(AndroidRepo.dump()); } catch (e) { /* 首次为空 */ }
  var F = RAW.files || {};
  var PATHS = Object.keys(F);

  var pad = function (n) { return String(n).padStart(2, '0'); };
  var todayISO = function () {
    var d = new Date();
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  };
  var toDate = function (s) { return new Date(String(s).slice(0, 10) + 'T00:00:00'); };
  var diffDays = function (a, b) { return Math.round((toDate(a) - toDate(b)) / 86400000); };
  var clean = function (s) { return String(s == null ? '' : s).replace(/\*\*/g, '').replace(/`/g, '').trim(); };
  var num = function (s) {
    var m = String(s == null ? '' : s).replace(/\*\*/g, '').match(/-?\d+(?:\.\d+)?/);
    return m ? parseFloat(m[0]) : null;
  };
  var isNum = function (v) { return typeof v === 'number' && isFinite(v); };
  var sum = function (arr, key) { return arr.reduce(function (a, x) { return a + (isNum(x[key]) ? x[key] : 0); }, 0); };
  var read = function (p) { return (F[p] && F[p].t) || ''; };
  var readJSON = function (p, dflt) {
    try { return JSON.parse(read(p)); } catch (e) { return dflt === undefined ? {} : dflt; }
  };
  var weekCn = '一二三四五六日';
  var weekday = function (iso) {
    var d = toDate(iso);
    return isNaN(d) ? '' : '周' + weekCn[(d.getDay() + 6) % 7];
  };

  // --------------------------------------------------------------- douyin
  function douyinView(handles) {
    var works = [], daily = [], imports = [];
    handles.forEach(function (h) {
      var d = readJSON('data/hub/douyin/' + h + '.json', {});
      (d.works || []).forEach(function (w) { works.push(Object.assign({}, w, { _handle: h })); });
      (d.daily || []).forEach(function (r) { daily.push(Object.assign({}, r, { _handle: h })); });
      imports = imports.concat(d.imports || []);
    });
    works.sort(function (a, b) { return (b.published_at || '').localeCompare(a.published_at || ''); });
    var plays = works.map(function (w) { return w.plays; }).filter(isNum);
    var total = sum(works, 'plays');
    var series = {};
    daily.forEach(function (row) {
      var d = row.date;
      if (!series[d]) series[d] = { date: d, plays: 0, posts: 0, likes: 0, comments: 0, shares: 0 };
      ['plays', 'posts', 'likes', 'comments', 'shares'].forEach(function (k) {
        series[d][k] += isNum(row[k]) ? row[k] : 0;
      });
    });
    var keys = Object.keys(series).sort();
    if (!keys.length) {
      works.forEach(function (w) {
        var d = w.date;
        if (!d) return;
        if (!series[d]) series[d] = { date: d, plays: 0, posts: 0, likes: 0, comments: 0, shares: 0 };
        series[d].plays += w.plays || 0;
        series[d].posts += 1;
      });
      keys = Object.keys(series).sort();
    }
    var days = [];
    if (keys.length) {
      var start = toDate(keys[0]), end = toDate(keys[keys.length - 1]);
      for (var d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
        var k = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
        days.push(series[k] || { date: k, plays: 0, posts: 0, likes: 0, comments: 0, shares: 0 });
      }
    }
    var pairs = works.filter(function (w) { return isNum(w.finish_rate) && (w.plays || 0) > 0; });
    var finishWeighted = null;
    if (pairs.length) {
      var denom = pairs.reduce(function (a, w) { return a + w.plays; }, 0);
      if (denom) finishWeighted = pairs.reduce(function (a, w) { return a + w.finish_rate * w.plays; }, 0) / denom;
    }
    var likes = sum(works, 'likes'), comments = sum(works, 'comments'),
      shares = sum(works, 'shares'), collects = sum(works, 'collects'),
      fans = sum(works, 'fans_delta'), profileVisits = sum(works, 'profile_visits');
    var media = {};
    works.forEach(function (w) { var k = w.media_type || '未标'; media[k] = (media[k] || 0) + 1; });
    var today = todayISO();
    var last7 = days.filter(function (d) { return diffDays(today, d.date) < 7; });
    var prev7 = days.filter(function (d) { var n = diffDays(today, d.date); return n >= 7 && n < 14; });
    var plays7 = sum(last7, 'plays'), playsPrev7 = sum(prev7, 'plays');
    var sortedPlays = plays.slice().sort(function (a, b) { return a - b; });
    var median = sortedPlays.length ? (sortedPlays.length % 2 ? sortedPlays[(sortedPlays.length - 1) / 2]
      : (sortedPlays[sortedPlays.length / 2 - 1] + sortedPlays[sortedPlays.length / 2]) / 2) : 0;
    var lastPublish = works.length ? works[0].published_at : '';
    return {
      handles: handles.slice(), works: works, days: days,
      imports: imports.sort(function (a, b) { return (a.at || '').localeCompare(b.at || ''); }).slice(-1),
      count: works.length, total_plays: total,
      avg_plays: plays.length ? total / plays.length : 0,
      median_plays: median, max_plays: plays.length ? Math.max.apply(null, plays) : 0,
      likes: likes, comments: comments, shares: shares, collects: collects,
      fans: fans, profile_visits: profileVisits,
      engage_rate: total ? (likes + comments + shares + collects) / total : 0,
      finish_avg: works.filter(function (w) { return isNum(w.finish_rate); }).length
        ? works.filter(function (w) { return isNum(w.finish_rate); }).reduce(function (a, w) { return a + w.finish_rate; }, 0)
          / works.filter(function (w) { return isNum(w.finish_rate); }).length : null,
      finish_weighted: finishWeighted,
      finish5_avg: null, media: media,
      top: works.slice().sort(function (a, b) { return (b.plays || 0) - (a.plays || 0); }).slice(0, 10),
      plays_last7: plays7, plays_prev7: playsPrev7,
      trend: playsPrev7 ? (plays7 - playsPrev7) / playsPrev7 : null,
      last_publish: lastPublish,
      gap_days: lastPublish ? diffDays(today, lastPublish.slice(0, 10)) : null,
      top1_share: plays.length && total ? Math.max.apply(null, plays) / total : null
    };
  }

  // ----------------------------------------------------------------- xhs
  var XHS_PCT = { cover_ctr: 1, finish_rate: 1, follow_rate: 1 };
  var XHS_WEIGHT = { cover_ctr: 'exposure', avg_watch: 'views', finish_rate: 'views', follow_rate: 'profile_visits' };
  var XHS_ORDER = ['exposure', 'views', 'cover_ctr', 'avg_watch', 'watch_total', 'finish_rate',
    'likes', 'comments', 'collects', 'shares', 'fans_net', 'fans_new', 'fans_lost',
    'profile_visits', 'follow_rate', 'posts', 'posts_video', 'posts_figure'];

  function weighted(values, weights) {
    var pairs = [];
    values.forEach(function (v, i) {
      if (isNum(v) && isNum(weights[i]) && weights[i] > 0) pairs.push([v, weights[i]]);
    });
    if (!pairs.length) return null;
    var denom = pairs.reduce(function (a, p) { return a + p[1]; }, 0);
    return denom ? pairs.reduce(function (a, p) { return a + p[0] * p[1]; }, 0) / denom : null;
  }

  function xhsView(handles) {
    var notes = [], daily = {}, per = [], imports = [], delta = {}, window = ['', ''];
    handles.forEach(function (h) {
      var d = readJSON('data/hub/xhs/' + h + '.json', {});
      (d.notes || []).forEach(function (n) { notes.push(Object.assign({}, n, { _handle: h })); });
      Object.keys(d.daily || {}).forEach(function (day) {
        var rec = d.daily[day];
        if (!daily[day]) daily[day] = { date: day };
        Object.keys(rec).forEach(function (k) {
          if (isNum(rec[k])) daily[day][k] = (daily[day][k] || 0) + rec[k];
          else if (daily[day][k] == null) daily[day][k] = rec[k];
        });
      });
      per.push({ h: h, s: d.summary || {}, d: d.summary_delta || {} });
      imports = imports.concat(d.imports || []);
      Object.assign(delta, d.summary_delta || {});
      var win = d.window || ['', ''];
      if (win[0]) {
        window[0] = !window[0] ? win[0] : (win[0] < window[0] ? win[0] : window[0]);
        window[1] = !window[1] ? win[1] : (win[1] > window[1] ? win[1] : window[1]);
      }
    });
    notes.sort(function (a, b) { return (b.published_at || '').localeCompare(a.published_at || ''); });

    var summary = {}, keys = {};
    per.forEach(function (p) { Object.keys(p.s).forEach(function (k) { keys[k] = 1; }); });
    Object.keys(keys).forEach(function (k) {
      var vals = per.map(function (p) { return p.s[k]; });
      var merged;
      if (XHS_PCT[k]) {
        var wk = XHS_WEIGHT[k];
        merged = weighted(vals, per.map(function (p) { return isNum(p.s[wk]) ? p.s[wk] : 0; }));
        if (merged == null) {
          var got = vals.filter(isNum);
          merged = got.length ? got.reduce(function (a, b) { return a + b; }, 0) / got.length : null;
        }
      } else {
        var nums = vals.filter(isNum);
        merged = nums.length ? nums.reduce(function (a, b) { return a + b; }, 0) : null;
      }
      if (merged != null) summary[k] = merged;
    });
    if (handles.length > 1) {
      delta = {};
      Object.keys(summary).forEach(function (k) {
        var got = per.map(function (p) { return p.d[k]; }).filter(isNum);
        delta[k] = got.length ? got.reduce(function (a, b) { return a + b; }, 0) / got.length : null;
      });
    }

    var tot = { exposure: 0, views: 0, likes: 0, comments: 0, collects: 0, shares: 0, fans: 0, danmaku: 0 };
    notes.forEach(function (n) { Object.keys(tot).forEach(function (k) { tot[k] += n[k] || 0; }); });
    var ctr = weighted(notes.map(function (n) { return n.cover_ctr; }), notes.map(function (n) { return n.exposure || 0; }));
    if (ctr == null) ctr = weighted(notes.map(function (n) { return n.cover_ctr; }), notes.map(function () { return 1; }));
    var engage = tot.views ? (tot.likes + tot.comments + tot.collects + tot.shares) / tot.views : 0;

    var series = Object.keys(daily).sort().map(function (d) { return daily[d]; });
    if (!series.length) {
      var buckets = {};
      notes.forEach(function (n) {
        if (!n.date) return;
        if (!buckets[n.date]) buckets[n.date] = { date: n.date };
        ['exposure', 'views', 'likes', 'comments', 'collects', 'shares', 'fans'].forEach(function (k) {
          buckets[n.date][k] = (buckets[n.date][k] || 0) + (n[k] || 0);
        });
        buckets[n.date].posts = (buckets[n.date].posts || 0) + 1;
      });
      series = Object.keys(buckets).sort().map(function (k) { return buckets[k]; });
    }
    var days = [];
    if (series.length) {
      var byDay = {};
      series.forEach(function (d) { byDay[d.date] = d; });
      var start = toDate(series[0].date), end = toDate(series[series.length - 1].date);
      for (var d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
        var k = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
        days.push(byDay[k] || { date: k });
      }
    }
    var today = todayISO();
    var last7 = days.filter(function (d) { return diffDays(today, d.date) >= 0 && diffDays(today, d.date) < 7; });
    var prev7 = days.filter(function (d) { var n = diffDays(today, d.date); return n >= 7 && n < 14; });
    var v7 = sum(last7, 'views'), vp7 = sum(prev7, 'views');
    var media = {};
    notes.forEach(function (n) { var k = n.media_type || '未标'; media[k] = (media[k] || 0) + 1; });
    var lastPublish = notes.length ? notes[0].published_at : '';
    return {
      handles: handles.slice(), notes: notes, days: days, summary: summary,
      delta: delta, summary_metrics: Object.keys(summary).length, window: window,
      imports: imports, count: notes.length,
      exposure: tot.exposure, views: tot.views, likes: tot.likes, comments: tot.comments,
      collects: tot.collects, shares: tot.shares, fans: tot.fans, danmaku: tot.danmaku,
      ctr: ctr, engage_rate: engage, avg_views: notes.length ? tot.views / notes.length : 0,
      top: notes.slice().sort(function (a, b) { return (b.views || 0) - (a.views || 0); }).slice(0, 10),
      media: media, views_last7: v7, views_prev7: vp7,
      trend: vp7 ? (v7 - vp7) / vp7 : null,
      last_publish: lastPublish,
      gap_days: lastPublish ? diffDays(today, lastPublish.slice(0, 10)) : null,
      metric_order: XHS_ORDER.filter(function (k) { return summary[k] != null; })
    };
  }

  // --------------------------------------------------------------- bundle
  function buildBundle() {
    var dyAccounts = readJSON('data/hub/douyin/accounts.json', { accounts: [] }).accounts || [];
    var dyViews = {}, dyProfiles = {};
    dyAccounts.forEach(function (a) {
      if (!a.handle) return;
      dyViews[a.handle] = douyinView([a.handle]);
      var d = readJSON('data/hub/douyin/' + a.handle + '.json', {});
      dyProfiles[a.handle] = d.profile || {};
    });
    if (dyAccounts.length) {
      var handles = dyAccounts.map(function (a) { return a.handle; }).filter(Boolean);
      dyViews.__all__ = douyinView(handles);
      var fans = handles.map(function (h) { return dyProfiles[h] && dyProfiles[h].fans; }).filter(isNum);
      dyProfiles.__all__ = {
        fans: fans.length ? fans.reduce(function (a, b) { return a + b; }, 0) : null,
        fans_new: handles.reduce(function (a, h) { return a + ((dyProfiles[h] || {}).fans_new || 0); }, 0),
        fans_delta: handles.reduce(function (a, h) { return a + ((dyProfiles[h] || {}).fans_delta || 0); }, 0)
      };
    }

    var xhsAccounts = readJSON('data/hub/xhs/accounts.json', { accounts: [] }).accounts || [];
    var xhsViews = {};
    xhsAccounts.forEach(function (a) { if (a.handle) xhsViews[a.handle] = xhsView([a.handle]); });
    if (xhsAccounts.length) {
      xhsViews.__all__ = xhsView(xhsAccounts.map(function (a) { return a.handle; }).filter(Boolean));
    }

    return {
      meta: {
        generated_at: new Date().toLocaleString('zh-CN', { hour12: false }),
        mode: 'android'
      },
      douyin: { accounts: dyAccounts, views: dyViews, profiles: dyProfiles },
      xhs: { accounts: xhsAccounts, views: xhsViews }
    };
  }

  var cached = null;
  window.HubAndroid = {
    bundle: function () {
      if (!cached) cached = buildBundle();
      return cached;
    }
  };
})();
