package com.jackverse.secondbrain;

import org.json.JSONArray;
import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Date;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * 手机上跑一次抖音数据同步：认号 → 作品列表 → 每日趋势 → 粉丝概览，
 * 写进本地仓库副本 data/hub/douyin/（结构与电脑上 core/douyin.py 完全一致），
 * 之后走原有的 ☁ 同步推送回 GitHub。
 *
 * 手机上按账号循环同步：每个号用自己的 Cookie 跑一遍，各写各自的
 * data/hub/douyin/&lt;号&gt;.json（结构与电脑上 core/douyin.py 完全一致），
 * 之后走原有的 ☁ 同步推送回 GitHub。换号不用退出旧号，Cookie 各存各的。
 */
public class DouyinSync {

    public interface Log {
        void line(String s);
    }

    public static class Result {
        public String handle = "";
        public String name = "";
        public int works;
        public int days;
        public int profile;
        /** 同步过程中被服务端刷新过的 Cookie（有变化时上层要存回去，登录态才能滚动续期）。 */
        public String cookie = "";
        public final List<String> errors = new ArrayList<>();

        public String summary() {
            String who = name.isEmpty() ? handle : name;
            StringBuilder sb = new StringBuilder(who)
                    .append(" · 作品 ").append(works)
                    .append(" · 趋势 ").append(days).append(" 天");
            if (!errors.isEmpty()) sb.append(" · ").append(errors.size()).append(" 项失败");
            return sb.toString();
        }
    }

    /** 跑一次同步。cookie 来自 WebView 登录；结果里会带回被服务端刷新过的 cookie。 */
    public static Result sync(RepoStore store, String cookie, int days, Log log) throws Exception {
        Log out = log == null ? s -> { } : log;
        DouyinClient.CookieJar jar = new DouyinClient.CookieJar(cookie);
        DouyinClient.Identity id = DouyinClient.identity(jar, 3);
        if (!id.ok()) throw new DouyinClient.LoginException("登录成功但没认出抖音号，请重新登录");

        Result res = new Result();
        res.handle = id.handle;
        res.name = id.name;
        String at = now("yyyy-MM-dd HH:mm");
        String rel = "data/hub/douyin/" + safe(id.handle) + ".json";
        out.line("认出账号：" + res.name + "（" + id.handle + "）");

        JSONObject data = readJson(store, rel);
        ensureArray(data, "works");
        ensureArray(data, "daily");
        ensureArray(data, "imports");

        // 1) 作品列表：接口能给全量，就整段替换（顺带清掉已删/改名的旧条目）
        try {
            List<JSONObject> items = DouyinClient.works(jar);
            if (items.isEmpty()) throw new Exception("接口没返回作品");
            int[] changed = replaceWorks(data, items);
            res.works = changed[0] + changed[1];
            out.line("作品列表：新增 " + changed[0] + " / 更新 " + changed[1]
                    + "（共 " + items.size() + " 条）");
            appendImport(data, "创作者中心 · 作品列表（接口全量）", "works", at, items.size());
        } catch (DouyinClient.LoginException e) {
            throw e;
        } catch (Exception e) {
            res.errors.add("作品：" + msg(e));
            out.line("作品接口失败：" + msg(e));
        }

        // 2) 每日趋势
        try {
            JSONArray metrics = DouyinClient.dashboard(jar, days);
            int n = mergeDashboard(data, metrics);
            res.days = n;
            out.line("每日趋势：" + n + " 天");
            if (n > 0) appendImport(data, "创作者中心 · 账号概览", "daily", at, n);
        } catch (DouyinClient.LoginException e) {
            throw e;
        } catch (Exception e) {
            res.errors.add("概览：" + msg(e));
            out.line("概览失败：" + msg(e));
        }

        // 3) 粉丝概览（失败不致命）
        try {
            JSONArray metrics = DouyinClient.fans(jar, days);
            res.profile = mergeProfile(data, metrics, at);
            if (res.profile > 0) out.line("粉丝概览：" + res.profile + " 项");
        } catch (DouyinClient.LoginException e) {
            throw e;
        } catch (Exception e) {
            out.line("粉丝概览跳过：" + msg(e));
        }

        trimImports(data);
        writeJson(store, rel, data);
        out.line("已写入 " + rel);

        ensureAccount(store, id.handle, id.name);
        // 跑完再取：这一整轮里服务端可能已经下发过新的 sessionid / bd_ticket_guard_*
        res.cookie = jar.value();
        return res;
    }

    /** 只认号（登录后立刻验证用）。 */
    public static DouyinClient.Identity identity(String cookie) throws Exception {
        return DouyinClient.identity(new DouyinClient.CookieJar(cookie), 6);
    }

    /** 把账号写进 data/hub/douyin/accounts.json（登录后立刻做，页面顶部导航才看得到）。 */
    public static void ensureAccountEntry(RepoStore store, String handle, String name) {
        ensureAccount(store, handle, name);
    }

    /** 解绑：从 accounts.json 里删掉这个号（作品数据文件保留，重新登录还能接着用）。 */
    public static void removeAccountEntry(RepoStore store, String handle) {
        String rel = "data/hub/douyin/accounts.json";
        JSONObject root = readJson(store, rel);
        JSONArray accounts = root.optJSONArray("accounts");
        if (accounts == null) return;
        JSONArray keep = new JSONArray();
        for (int i = 0; i < accounts.length(); i++) {
            JSONObject a = accounts.optJSONObject(i);
            if (a == null) continue;
            if (handle.equals(a.optString("handle", ""))) continue;
            keep.put(a);
        }
        try {
            root.put("accounts", keep);
        } catch (Exception ignored) {
        }
        writeJson(store, rel, root);
    }

    // ------------------------------------------------------------ 合并逻辑
    /** 全量替换 works，返回 {新增, 更新}。 */
    private static int[] replaceWorks(JSONObject data, List<JSONObject> items) {
        JSONArray oldArr = data.optJSONArray("works");
        List<JSONObject> works = new ArrayList<>();
        for (JSONObject it : items) {
            JSONObject w = DouyinClient.toWork(it);
            if (w != null) works.add(w);
        }
        Collections.sort(works, (a, b) -> b.optString("published_at", "")
                .compareTo(a.optString("published_at", "")));

        Map<String, Boolean> before = new HashMap<>();
        if (oldArr != null) {
            for (int i = 0; i < oldArr.length(); i++) {
                JSONObject w = oldArr.optJSONObject(i);
                if (w != null) before.put(key(w), true);
            }
        }
        int added = 0, updated = 0;
        for (JSONObject w : works) {
            if (before.containsKey(key(w))) updated++;
            else added++;
        }
        JSONArray arr = new JSONArray();
        for (JSONObject w : works) arr.put(w);
        try {
            data.put("works", arr);
        } catch (Exception ignored) {
        }
        return new int[]{added, updated};
    }

    private static String key(JSONObject w) {
        return w.optString("published_at", "") + "\u0001" + w.optString("title", "");
    }

    /** 把 overview/dashboard 的 metrics[].trends[] 并进 daily，返回写到的天数。 */
    private static int mergeDashboard(JSONObject data, JSONArray metrics) {
        JSONArray daily = data.optJSONArray("daily");
        if (daily == null) {
            daily = new JSONArray();
            try {
                data.put("daily", daily);
            } catch (Exception ignored) {
            }
        }
        Map<String, Integer> index = new HashMap<>();
        for (int i = 0; i < daily.length(); i++) {
            JSONObject row = daily.optJSONObject(i);
            if (row != null && !row.optString("date", "").isEmpty()) {
                index.put(row.optString("date"), i);
            }
        }
        int touched = 0;
        java.util.Set<String> days = new java.util.HashSet<>();
        for (int i = 0; i < metrics.length(); i++) {
            JSONObject m = metrics.optJSONObject(i);
            if (m == null) continue;
            String field = DouyinClient.dashKey(firstNonEmpty(
                    m.optString("english_metric_name", ""),
                    m.optString("metric_name", ""),
                    m.optString("key", "")));
            if (field == null) continue;
            JSONArray trends = m.optJSONArray("trends");
            if (trends == null) continue;
            for (int t = 0; t < trends.length(); t++) {
                JSONObject tr = trends.optJSONObject(t);
                if (tr == null) continue;
                String day = DouyinClient.dashDate(firstNonEmpty(
                        str(tr.opt("date_time")), str(tr.opt("date"))));
                if (day.isEmpty()) continue;
                Double val = DouyinClient.dashValue(field, tr.opt("value"));
                if (val == null) continue;
                JSONObject row;
                Integer at = index.get(day);
                if (at == null) {
                    row = newDaily(day);
                    daily.put(row);
                    index.put(day, daily.length() - 1);
                } else {
                    row = daily.optJSONObject(at);
                    if (row == null) {
                        row = newDaily(day);
                        try {
                            daily.put(at, row);
                        } catch (Exception ignored) {
                        }
                    }
                }
                try {
                    row.put(field, val);
                } catch (Exception ignored) {
                }
                days.add(day);
            }
        }
        touched = days.size();
        if (touched > 0) sortByKey(data, "daily", "date", true);
        return touched;
    }

    private static JSONObject newDaily(String day) {
        JSONObject row = new JSONObject();
        try {
            row.put("date", day);
            row.put("posts", 0.0);
            row.put("plays", 0.0);
            row.put("likes", 0.0);
            row.put("shares", 0.0);
            row.put("comments", 0.0);
            row.put("finish5_rate", JSONObject.NULL);
            row.put("bounce2_rate", JSONObject.NULL);
            row.put("cover_ctr", JSONObject.NULL);
            row.put("avg_duration", JSONObject.NULL);
        } catch (Exception ignored) {
        }
        return row;
    }

    /** 粉丝概览 -> profile（总粉丝 / 净增 / 新增）。 */
    private static int mergeProfile(JSONObject data, JSONArray metrics, String at) {
        Map<String, Integer> got = new LinkedHashMap<>();
        for (int i = 0; i < metrics.length(); i++) {
            JSONObject m = metrics.optJSONObject(i);
            if (m == null) continue;
            String key = (firstNonEmpty(m.optString("english_metric_name", ""),
                    m.optString("metric_name", "")) + "")
                    .trim().toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]+", "_")
                    .replaceAll("^_+|_+$", "");
            Object v = m.has("metric_value") ? m.opt("metric_value") : null;
            if (v == null || v == JSONObject.NULL) {
                JSONArray trends = m.optJSONArray("trends");
                if (trends != null && trends.length() > 0) {
                    JSONObject last = trends.optJSONObject(trends.length() - 1);
                    if (last != null) v = last.opt("value");
                }
            }
            Double val = DouyinClient.dashValue("", v);
            if (val == null) continue;
            if (key.equals("total_fans_cnt") || key.equals("fans_all") || key.equals("total_fans")) {
                got.put("fans", (int) Math.round(val));
            } else if (key.equals("net_fans_cnt") || key.equals("net_follow_fans")) {
                got.put("fans_delta", (int) Math.round(val));
            } else if (key.equals("increase_fans_cnt") || key.equals("new_fans_cnt")
                    || key.equals("follow_fans_cnt")) {
                got.put("fans_new", (int) Math.round(val));
            }
        }
        if (got.isEmpty()) return 0;
        JSONObject prof = data.optJSONObject("profile");
        if (prof == null) prof = new JSONObject();
        try {
            for (Map.Entry<String, Integer> e : got.entrySet()) prof.put(e.getKey(), e.getValue());
            prof.put("updated", at);
            data.put("profile", prof);
        } catch (Exception ignored) {
        }
        return got.size();
    }

    private static void appendImport(JSONObject data, String file, String kind, String at, int rows) {
        JSONArray imports = data.optJSONArray("imports");
        if (imports == null) imports = new JSONArray();
        JSONObject rec = new JSONObject();
        try {
            rec.put("file", file);
            rec.put("kind", kind);
            rec.put("at", at);
            rec.put("rows", rows);
            imports.put(rec);
            data.put("imports", imports);
        } catch (Exception ignored) {
        }
    }

    private static void trimImports(JSONObject data) {
        JSONArray imports = data.optJSONArray("imports");
        if (imports == null || imports.length() <= 40) return;
        JSONArray keep = new JSONArray();
        for (int i = imports.length() - 40; i < imports.length(); i++) keep.put(imports.opt(i));
        try {
            data.put("imports", keep);
        } catch (Exception ignored) {
        }
    }

    private static void sortByKey(JSONObject data, String field, String key, boolean asc) {
        JSONArray arr = data.optJSONArray(field);
        if (arr == null) return;
        List<JSONObject> list = new ArrayList<>();
        for (int i = 0; i < arr.length(); i++) {
            JSONObject o = arr.optJSONObject(i);
            if (o != null) list.add(o);
        }
        Comparator<JSONObject> cmp = (a, b) -> a.optString(key, "").compareTo(b.optString(key, ""));
        Collections.sort(list, asc ? cmp : cmp.reversed());
        JSONArray out = new JSONArray();
        for (JSONObject o : list) out.put(o);
        try {
            data.put(field, out);
        } catch (Exception ignored) {
        }
    }

    // ------------------------------------------------------------ 账号库 / 读写
    private static void ensureAccount(RepoStore store, String handle, String name) {
        String rel = "data/hub/douyin/accounts.json";
        JSONObject root = readJson(store, rel);
        JSONArray accounts = root.optJSONArray("accounts");
        if (accounts == null) accounts = new JSONArray();
        boolean hit = false;
        for (int i = 0; i < accounts.length(); i++) {
            JSONObject a = accounts.optJSONObject(i);
            if (a == null) continue;
            if (handle.equals(a.optString("handle", ""))) {
                hit = true;
                if (!name.isEmpty()) {
                    try {
                        a.put("name", name);
                    } catch (Exception ignored) {
                    }
                }
            }
        }
        if (!hit) {
            JSONObject rec = new JSONObject();
            try {
                rec.put("handle", handle);
                rec.put("name", name);
                rec.put("created", now("yyyy-MM-dd HH:mm"));
                accounts.put(rec);
            } catch (Exception ignored) {
            }
        }
        try {
            root.put("accounts", accounts);
        } catch (Exception ignored) {
        }
        writeJson(store, rel, root);
    }

    private static JSONObject readJson(RepoStore store, String rel) {
        try {
            byte[] raw = store.read(rel);
            if (raw == null || raw.length == 0) return new JSONObject();
            String text = new String(raw, StandardCharsets.UTF_8);
            if (!text.trim().startsWith("{")) return new JSONObject();
            return new JSONObject(text);
        } catch (Exception e) {
            return new JSONObject();
        }
    }

    private static void writeJson(RepoStore store, String rel, JSONObject data) {
        try {
            // 缩进 1 空格：和电脑上 python 写出来的样子一致，diff 不会整文件翻新
            String text = data.toString(1) + "\n";
            byte[] bytes = text.getBytes(StandardCharsets.UTF_8);
            byte[] old = store.read(rel);
            if (old != null && text.equals(new String(old, StandardCharsets.UTF_8))) {
                return;                                     // 一模一样就不写，免得每次同步都造 diff
            }
            store.write(rel, bytes);
            store.markDirty(rel);
        } catch (Exception e) {
            throw new RuntimeException("写 " + rel + " 失败：" + e.getMessage(), e);
        }
    }

    private static void ensureArray(JSONObject o, String key) {
        if (o.optJSONArray(key) != null) return;
        try {
            o.put(key, new JSONArray());
        } catch (Exception ignored) {
        }
    }

    private static String safe(String handle) {
        String s = handle == null ? "" : handle.replaceAll("[^0-9A-Za-z_\\-]", "_");
        return s.isEmpty() ? "unknown" : s;
    }

    private static String str(Object o) {
        return o == null || o == JSONObject.NULL ? "" : String.valueOf(o);
    }

    private static String firstNonEmpty(String... vals) {
        for (String v : vals) if (v != null && !v.isEmpty()) return v;
        return "";
    }

    private static String msg(Exception e) {
        return e.getMessage() == null ? e.toString() : e.getMessage();
    }

    private static String now(String fmt) {
        return new SimpleDateFormat(fmt, Locale.CHINA).format(new Date());
    }
}
