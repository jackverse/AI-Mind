/* 把手机本地仓库里的 notes/ 与 data/hub/ 现算成与 server.py 相同结构的 bundle。
 * 只在 Android 壳里生效（window.AndroidRepo 由原生注入）；网页端不加载它。
 * 口径对齐 tools/hub/core/{daily,timeline,douyin,xhs,bill,store}.py。
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

  // ------------------------------------------------------------ daily-log
  function parseDaily(text) {
    var month = null, year = null, cols = null, rows = [];
    text.split(/\r?\n/).forEach(function (rawLine) {
      var s = rawLine.trim();
      var mm = /^##\s+(\d{4})-(\d{2})\s*$/.exec(s);
      if (mm) { month = mm[1] + '-' + mm[2]; year = mm[1]; cols = null; return; }
      if (s.indexOf('## ') === 0) { month = null; cols = null; return; }
      if (s.charAt(0) !== '|' || !month) return;
      var cells = s.replace(/^\|/, '').replace(/\|$/, '').split('|').map(clean);
      if (!cols) {
        if (cells[0] === '日期') {
          cols = {};
          cells.forEach(function (c, i) { cols[c] = i; });
        }
        return;
      }
      if (cells.every(function (c) { return !c || /^:?-{2,}:?$/.test(c); })) return;
      if (!/^\d{2}-\d{2}$/.test(cells[0] || '')) return;

      var get = function (key) {
        if (cols[key] != null) return cells[cols[key]] || '';
        for (var name in cols) {
          if (name.indexOf(key) === 0) return cells[cols[name]] || '';
        }
        return '';
      };

      var fitness = get('健身');
      var weight = num(get('体重'));
      var rest = fitness.indexOf('休息') >= 0;
      var planned = /计划|准备|打算/.test(fitness);
      var trained = !!fitness && fitness !== '—' && fitness !== '-' && !rest &&
        /练|打卡|跑|有氧|训练/.test(fitness);
      var part = null;
      if (trained) {
        var parts = [['练腿', '腿'], ['深蹲', '腿'], ['硬拉', '腿'], ['练背', '背'], ['引体', '背'],
          ['划船', '背'], ['练胸', '胸'], ['卧推', '胸'], ['练肩', '肩'], ['推举', '肩'],
          ['练胳膊', '胳膊'], ['手臂', '胳膊'], ['二头', '胳膊'], ['三头', '胳膊'],
          ['有氧', '有氧'], ['跑', '有氧']];
        for (var i = 0; i < parts.length; i++) {
          if (fitness.indexOf(parts[i][0]) >= 0) { part = parts[i][1]; break; }
        }
        if (!part) part = (fitness.indexOf('打卡') >= 0 || fitness.indexOf('部位未辨') >= 0) ? '未记部位' : '其他';
      }
      var status = rest ? 'rest' : (planned ? 'plan' : (trained ? 'train' : 'none'));
      rows.push({
        date: year + '-' + cells[0], md: cells[0], week: get('星期'),
        fitness: fitness, status: status, part: part, weight: weight,
        sleep: get('睡眠'), douyin: get('抖音'), english: get('英语'),
        diet: get('饮食'), project: get('项目'), note: get('备注')
      });
    });
    rows.sort(function (a, b) { return a.date < b.date ? -1 : a.date > b.date ? 1 : 0; });
    return rows;
  }

  function weightSeries(rows) {
    return rows.filter(function (r) { return r.weight != null; })
      .map(function (r) { return { date: r.date, weight: r.weight }; });
  }

  function movingAvg(series, win) {
    win = win || 7;
    return series.map(function (p) {
      var vals = series.filter(function (q) {
        return q.date <= p.date && diffDays(p.date, q.date) >= 0 && diffDays(p.date, q.date) < win;
      }).map(function (q) { return q.weight; });
      return { date: p.date, weight: Math.round((vals.reduce(function (a, b) { return a + b; }, 0) / vals.length) * 100) / 100 };
    });
  }

  function streaks(rows) {
    var best = 0, cur = 0;
    rows.forEach(function (r) {
      if (r.status === 'train') { cur++; if (cur > best) best = cur; }
      else if (r.status === 'rest') cur = 0;
    });
    var tail = 0;
    for (var i = rows.length - 1; i >= 0; i--) {
      if (rows[i].status === 'train') tail++;
      else if (rows[i].status === 'rest') break;
    }
    return { tail: tail, best: best, days: rows.length };
  }

  function recordStreak(rows) {
    if (!rows.length) return 0;
    var n = 1;
    for (var i = rows.length - 1; i > 0; i--) {
      if (diffDays(rows[i].date, rows[i - 1].date) === 1) n++;
      else break;
    }
    return n;
  }

  function partCounts(rows) {
    var c = {};
    rows.forEach(function (r) {
      if (r.status === 'train') {
        var k = r.part || '其他';
        c[k] = (c[k] || 0) + 1;
      }
    });
    return Object.keys(c).map(function (k) { return { part: k, count: c[k] }; })
      .sort(function (a, b) { return b.count - a.count; });
  }

  function calendar(rows, n) {
    var idx = {};
    rows.forEach(function (r) { idx[r.date] = r.status; });
    var out = [], today = todayISO();
    for (var i = n - 1; i >= 0; i--) {
      var d = new Date(); d.setDate(d.getDate() - i);
      var key = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
      out.push({ date: key, status: idx[key] || null });
    }
    return out;
  }

  function fitnessView(rows) {
    var ws = weightSeries(rows);
    var st = streaks(rows);
    var trains = rows.filter(function (r) { return r.status === 'train'; });
    var rests = rows.filter(function (r) { return r.status === 'rest'; });
    var plans = rows.filter(function (r) { return r.status === 'plan'; });
    var today = todayISO();
    var recent7 = trains.filter(function (r) { return diffDays(today, r.date) <= 7; });
    var min = ws.length ? ws.reduce(function (a, b) { return b.weight < a.weight ? b : a; }) : null;
    var delta = ws.length > 1 ? Math.round((ws[0].weight - ws[ws.length - 1].weight) * 10) / 10 : 0;
    return {
      rows: rows,
      summary: {
        days: rows.length, rec_streak: recordStreak(rows),
        train: trains.length, rest: rests.length, plan: plans.length,
        rate: rows.length ? Math.round(trains.length * 100 / rows.length) : 0,
        streak: st.tail, best_streak: st.best, recent7: recent7.length,
        w_first: ws.length ? [ws[0].date, ws[0].weight] : null,
        w_last: ws.length ? [ws[ws.length - 1].date, ws[ws.length - 1].weight] : null,
        w_min: min ? [min.date, min.weight] : null,
        w_delta: delta
      },
      series: ws,
      moving: movingAvg(ws),
      parts: partCounts(rows),
      calendar: calendar(rows, 30)
    };
  }

  // ------------------------------------------------------------- timeline
  var LINK_RE = /\[([^\]]*)\]\(([^)\s]*)\)/g;

  function resolveHref(href) {
    href = (href || '').trim();
    if (!href || href.indexOf('://') >= 0 || href.indexOf('mailto:') === 0) return null;
    if (href.indexOf('notes/') === 0) return href;
    if (href.indexOf('../') === 0 || href.charAt(0) === '/') return null;
    return 'notes/' + href.replace(/^\.?\//, '');
  }

  function talkTag(category) {
    var head = String(category || '').replace(/\s+/g, ' ').split(/[/+＋]/)[0].trim();
    var map = [['宠物', '项目'], ['职业', '职业'], ['生活', '生活'], ['技术', '技术'],
      ['系统', '系统'], ['自媒体', '自媒体'], ['考研', '考研']];
    for (var i = 0; i < map.length; i++) if (head.indexOf(map[i][0]) >= 0) return map[i][1];
    return head.slice(0, 4) || '交流';
  }

  function parseIndex(text) {
    var out = [], cols = null;
    text.split(/\r?\n/).forEach(function (line) {
      var s = line.trim();
      if (s.charAt(0) !== '|') { if (s.indexOf('## ') === 0) cols = null; return; }
      var cells = s.replace(/^\|/, '').replace(/\|$/, '').split('|').map(function (c) { return c.trim(); });
      if (cells.length < 3) return;
      if (cells[0] === '日期') {
        cols = {};
        cells.forEach(function (c, i) { cols[c] = i; });
        return;
      }
      if (!cols || !/^\d{4}-\d{2}-\d{2}$/.test(cells[0])) return;
      var cell = function (k) { var i = cols[k]; return i != null && i < cells.length ? cells[i] : ''; };
      var detail = cell('详情'), path = null, m;
      LINK_RE.lastIndex = 0;
      while ((m = LINK_RE.exec(detail)) !== null) {
        path = resolveHref(m[2]);
        if (path) break;
      }
      var summary = cell('一句话摘要').replace(/\*\*/g, '').replace(/`/g, '').trim();
      out.push({
        date: cells[0], category: cell('主题分类').replace(/\*\*/g, '').trim(),
        summary: summary || detail, path: path
      });
    });
    return out;
  }

  function timelineView(dailyText, indexText) {
    var today = todayISO();
    var days = {}, order = [];
    var bucket = function (d) {
      if (!days[d]) { days[d] = { date: d, week: weekday(d), today: d === today, items: [] }; order.push(d); }
      return days[d];
    };
    var rows = parseDaily(dailyText);
    var ws = weightSeries(rows);
    var firstW = ws.length ? ws[0].weight : null;
    var low = null;
    var cols = [['健身', 'fitness'], ['体重', 'weight'], ['睡眠', 'sleep'], ['抖音', 'douyin'],
      ['英语', 'english'], ['饮食', 'diet'], ['项目', 'project'], ['备注', 'note']];
    rows.forEach(function (r) {
      var b = bucket(r.date);
      cols.forEach(function (pair) {
        var tag = pair[0], key = pair[1], val = r[key], text;
        if (tag === '体重') {
          if (val == null) return;
          var extra = [];
          if (firstW != null && Math.abs(val - firstW) > 1e-9) extra.push('累计 ' + (val - firstW >= 0 ? '+' : '') + (val - firstW).toFixed(1));
          if (low != null && val < low) extra.push('新低');
          low = low == null ? val : Math.min(low, val);
          text = val + ' 斤' + (extra.length ? '（' + extra.join('，') + '）' : '');
        } else {
          text = clean(val);
          if (!text || text === '—' || text === '-' || text === '–') return;
        }
        b.items.push({ kind: 'daily', tag: tag, text: text, path: 'notes/daily-log.md' });
      });
    });
    parseIndex(indexText).forEach(function (t) {
      bucket(t.date).items.push({ kind: 'talk', tag: talkTag(t.category), text: t.summary, path: t.path });
    });
    order.sort().reverse();
    var out = order.map(function (d) { return days[d]; });
    return {
      days: out,
      summary: { days: out.length, count: out.reduce(function (a, d) { return a + d.items.length; }, 0),
        first: out.length ? out[out.length - 1].date : null, last: out.length ? out[0].date : null }
    };
  }

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

  // ---------------------------------------------------------------- bills
  function billsView(ids) {
    var accounts = [];
    PATHS.forEach(function (p) {
      if (!/^data\/hub\/bills\/[^/]+\.json$/.test(p)) return;
      var d = readJSON(p, {});
      if (d.account && d.account.id) accounts.push(d.account);
    });
    accounts.sort(function (a, b) { return (a.name || '').localeCompare(b.name || ''); });
    var selected = ids && ids.length ? accounts.filter(function (a) { return ids.indexOf(a.id) >= 0; }) : accounts;

    var txns = [];
    selected.forEach(function (meta) {
      var d = readJSON('data/hub/bills/' + meta.platform + '-' + meta.ext_id + '.json', {});
      (d.txns || []).forEach(function (t) {
        var rec = Object.assign({}, t);
        rec.account_id = meta.id;
        rec.account_name = meta.name || meta.id;
        rec.category = t.user_category || t.category || '其他';
        txns.push(rec);
      });
    });
    txns.sort(function (a, b) { return (b.time || '').localeCompare(a.time || ''); });

    var today = todayISO();
    var startD = new Date(); startD.setDate(startD.getDate() - 29);
    var start = startD.getFullYear() + '-' + pad(startD.getMonth() + 1) + '-' + pad(startD.getDate());
    var inWindow = txns.filter(function (t) { return t.date && t.date >= start && t.date <= today; });
    var active = inWindow.filter(function (t) { return !t.excluded; });
    var expense = active.filter(function (t) { return t.direction === 'expense'; }).reduce(function (a, t) { return a + t.amount; }, 0);
    var income = active.filter(function (t) { return t.direction === 'income'; }).reduce(function (a, t) { return a + t.amount; }, 0);

    var byDay = {};
    active.forEach(function (t) {
      if (!byDay[t.date]) byDay[t.date] = { date: t.date, expense: 0, income: 0, count: 0 };
      byDay[t.date][t.direction] += t.amount;
      byDay[t.date].count++;
    });
    var days = [];
    for (var d = new Date(startD); d <= new Date(); d.setDate(d.getDate() + 1)) {
      var k = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
      days.push(byDay[k] || { date: k, expense: 0, income: 0, count: 0 });
    }
    var cats = {};
    active.forEach(function (t) {
      if (t.direction !== 'expense') return;
      cats[t.category] = Math.round(((cats[t.category] || 0) + t.amount) * 100) / 100;
    });
    var topCats = Object.keys(cats).map(function (k) { return [k, cats[k]]; }).sort(function (a, b) { return b[1] - a[1]; });
    var merchants = {};
    active.forEach(function (t) {
      if (t.direction !== 'expense') return;
      var name = t.counterparty_name || t.item || '未知';
      if (!merchants[name]) merchants[name] = { name: name, amount: 0, count: 0 };
      merchants[name].amount = Math.round((merchants[name].amount + t.amount) * 100) / 100;
      merchants[name].count++;
    });
    var month = today.slice(0, 7);
    var monthExpense = txns.filter(function (t) { return (t.date || '').indexOf(month) === 0 && !t.excluded && t.direction === 'expense'; })
      .reduce(function (a, t) { return a + t.amount; }, 0);
    return {
      accounts: accounts, txns: inWindow, all_count: txns.length,
      excluded_count: inWindow.length - active.length,
      window: [start, today], days: days,
      expense: Math.round(expense * 100) / 100, income: Math.round(income * 100) / 100,
      count: active.length, avg_day: Math.round(expense / 30 * 100) / 100,
      categories: topCats,
      merchants: Object.keys(merchants).map(function (k) { return merchants[k]; })
        .sort(function (a, b) { return b.amount - a.amount; }).slice(0, 8),
      month_expense: Math.round(monthExpense * 100) / 100, month: month
    };
  }

  // ---------------------------------------------------------------- quiz
  function quizView() {
    var subjects = {};
    PATHS.forEach(function (p) {
      var m = /^notes\/kb\/([^/]+)\/questions\.jsonl$/.exec(p);
      if (!m) return;
      var list = [];
      read(p).split(/\r?\n/).forEach(function (line) {
        line = line.trim();
        if (!line) return;
        try { list.push(JSON.parse(line)); } catch (e) { /* 跳过坏行 */ }
      });
      subjects[m[1]] = { subject: m[1], questions: list };
    });
    return Object.keys(subjects).sort().map(function (name) {
      var s = subjects[name];
      var review = readJSON('notes/kb/' + name + '/review.json', {});
      var seen = s.questions.filter(function (q) { return review[q.id]; }).length;
      var wrong = s.questions.filter(function (q) {
        var st = review[q.id];
        return st && st.wrong > 0 && !st.mastered;
      }).length;
      var mastered = Object.keys(review).filter(function (k) { return review[k].mastered; }).length;
      return {
        subject: name, total: s.questions.length, seen: seen, wrong: wrong, mastered: mastered,
        questions: s.questions.map(function (q) {
          return { id: q.id, chapter: q.chapter || '', type: q.type || 'choice', q: q.q || '',
            options: q.options || {}, answer: q.answer || '', analysis: q.analysis || '' };
        }),
        review: review
      };
    });
  }

  // --------------------------------------------------------------- bundle
  function buildBundle() {
    var notesFiles = [], texts = {}, titles = {};
    PATHS.forEach(function (p) {
      if (p.indexOf('notes/') !== 0 || !/\.md$/.test(p)) return;
      var text = read(p);
      var tm = /^#\s+(.+)$/m.exec(text);
      var title = tm ? tm[1].trim() : p.split('/').pop().replace(/\.md$/, '');
      var inner = p.slice('notes/'.length);
      var dir = inner.indexOf('/') >= 0 ? inner.slice(0, inner.lastIndexOf('/')) : '';
      var meta = F[p] || {};
      texts[p] = text;
      titles[p] = title;
      notesFiles.push({
        path: p, name: p.split('/').pop(), title: title,
        group: dir, mtime: meta.m || 0, size: meta.s || text.length
      });
    });
    notesFiles.sort(function (a, b) {
      if (b.mtime !== a.mtime) return b.mtime - a.mtime;
      return a.path < b.path ? -1 : a.path > b.path ? 1 : 0;
    });

    var quiz = { subjects: quizView() };
    var home = {
      subjects: quiz.subjects.length,
      questions: quiz.subjects.reduce(function (a, s) { return a + s.total; }, 0),
      wrong: quiz.subjects.reduce(function (a, s) { return a + s.wrong; }, 0),
      notes: notesFiles.length,
      recent: notesFiles.slice(0, 6),
      today: todayISO(), week: weekday(todayISO())
    };

    var dailyText = read('notes/daily-log.md');
    var indexText = read('notes/index.md');
    var rows = parseDaily(dailyText);

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

    var billViews = { __all__: billsView(null) };
    billViews.__all__.accounts.forEach(function (a) { billViews[a.id] = billsView([a.id]); });

    return {
      meta: {
        generated_at: new Date().toLocaleString('zh-CN', { hour12: false }),
        machine: 'Android', root: (RAW.meta && RAW.meta.root) || '', mode: 'android'
      },
      home: home,
      notes: { files: notesFiles, texts: texts, titles: titles },
      fitness: fitnessView(rows),
      timeline: timelineView(dailyText, indexText),
      douyin: { accounts: dyAccounts, views: dyViews, profiles: dyProfiles },
      xhs: { accounts: xhsAccounts, views: xhsViews },
      bills: { accounts: billViews.__all__.accounts, views: billViews },
      eudic: { accounts: [], summary: null },
      quiz: quiz
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
