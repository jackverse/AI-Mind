package com.jackverse.secondbrain;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * 抖音创作者中心「只读」接口客户端。
 *
 * 和电脑上的 tools/hub/core/douyin_sync.py 打的是同一套接口、同一个 UA：
 *   GET  /aweme/v1/creator/user/info/                       认号
 *   GET  /web/api/creator/item/list                         作品列表（含全量指标，分页）
 *   POST /janus/douyin/creator/data/overview/dashboard      每日趋势
 *   GET  /janus/douyin/creator/data/overview/dashboard/fans 粉丝概览
 *
 * 只要 Cookie，不碰 a_bogus / x-s 之类的风控签名——让页面自己登录、我们只读。
 * 只做读，不写抖音侧任何数据。
 */
public class DouyinClient {

    public static final String BASE = "https://creator.douyin.com";
    public static final String UA =
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    + "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36";
    private static final String REFERER = BASE + "/creator-micro/home";

    /** 登录态失效（要用户重新扫码）。 */
    public static class LoginException extends Exception {
        public LoginException(String msg) {
            super(msg);
        }
    }

    /** 认账号：handle 优先抖音号（unique_id/short_id），没有就用 user_id。 */
    public static class Identity {
        public String handle = "";
        public String name = "";
        public String userId = "";
        public boolean ok() {
            return !handle.isEmpty();
        }
        public String label() {
            return name.isEmpty() ? handle : name;
        }
    }

    // ------------------------------------------------------------ HTTP
    /**
     * 可变的 Cookie 罐：每次响应都把 Set-Cookie 吸收进来，像浏览器那样滚动续期。
     * 电脑端 core/douyin_sync.py 的 merge_cookies 做的就是这件事——不做的话，
     * 手机上那份 Cookie 会冻结在登录那一刻，寿命用完就掉线。
     */
    public static class CookieJar {
        private String cookie;

        public CookieJar(String cookie) {
            this.cookie = cookie == null ? "" : cookie;
        }

        public String value() {
            return cookie;
        }

        /** 当前登录态的 key（sessionid 等）在不在。 */
        public boolean hasLogin() {
            String c = cookie == null ? "" : cookie;
            return c.contains("sessionid=") || c.contains("sessionid_ss=") || c.contains("sid_guard=");
        }

        void absorb(HttpURLConnection c) {
            Map<String, List<String>> headers;
            try {
                headers = c.getHeaderFields();
            } catch (Exception e) {
                return;
            }
            if (headers == null) return;
            List<String> setCookies = null;
            for (Map.Entry<String, List<String>> e : headers.entrySet()) {
                String k = e.getKey();
                if (k != null && k.equalsIgnoreCase("Set-Cookie")) {
                    setCookies = e.getValue();
                    break;
                }
            }
            if (setCookies == null || setCookies.isEmpty()) return;

            LinkedHashMap<String, String> jar = new LinkedHashMap<>();
            for (String part : (cookie == null ? "" : cookie).split(";")) {
                String p = part.trim();
                int i = p.indexOf('=');
                if (i > 0) jar.put(p.substring(0, i).trim(), p.substring(i + 1).trim());
            }
            boolean changed = false;
            for (String line : setCookies) {
                if (line == null) continue;
                String first = line.split(";", 2)[0];
                int i = first.indexOf('=');
                if (i <= 0) continue;
                String name = first.substring(0, i).trim();
                String val = first.substring(i + 1).trim();
                if (name.isEmpty()) continue;
                if (!val.equals(jar.get(name))) {
                    jar.put(name, val);
                    changed = true;
                }
            }
            if (!changed) return;
            StringBuilder sb = new StringBuilder();
            for (Map.Entry<String, String> e : jar.entrySet()) {
                if (sb.length() > 0) sb.append("; ");
                sb.append(e.getKey()).append('=').append(e.getValue());
            }
            cookie = sb.toString();
        }
    }

    private static String request(String url, CookieJar jar, String method, String body)
            throws IOException, LoginException {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(15000);
        c.setReadTimeout(60000);
        c.setInstanceFollowRedirects(true);
        c.setRequestMethod(method);
        c.setRequestProperty("User-Agent", UA);
        c.setRequestProperty("Accept", "application/json, text/plain, */*");
        c.setRequestProperty("Accept-Language", "zh-CN,zh;q=0.9");
        c.setRequestProperty("Referer", REFERER);
        c.setRequestProperty("Cookie", jar == null || jar.value() == null ? "" : jar.value());
        if (body != null) {
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json");
            c.setRequestProperty("Origin", BASE);
            byte[] raw = body.getBytes(StandardCharsets.UTF_8);
            c.setRequestProperty("Content-Length", String.valueOf(raw.length));
            try (OutputStream os = c.getOutputStream()) {
                os.write(raw);
            }
        }
        int code = c.getResponseCode();
        if (jar != null) jar.absorb(c);
        InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
        String text = in == null ? "" : drain(in);
        if (code >= 400) {
            throw new IOException("接口 HTTP " + code + " " + pathOf(url));
        }
        String t = text.trim();
        if (!t.startsWith("{") && !t.startsWith("[")) {
            throw new IOException("接口返回的不是 JSON（" + pathOf(url) + "）");
        }
        return t;
    }

    private static String drain(InputStream in) throws IOException {
        try (InputStream i = in) {
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            byte[] b = new byte[8192];
            int n;
            while ((n = i.read(b)) > 0) buf.write(b, 0, n);
            return new String(buf.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    private static String pathOf(String url) {
        int i = url.indexOf("://");
        int j = url.indexOf('/', i < 0 ? 0 : i + 3);
        return j < 0 ? url : url.substring(j);
    }

    /** 发请求并解析；status_code/BaseResp 非 0 时报错，登录失效抛 LoginException。 */
    private static JSONObject json(String url, CookieJar jar, String method, String body)
            throws IOException, LoginException {
        String text = request(url, jar, method, body);
        JSONObject obj;
        try {
            obj = new JSONObject(text);
        } catch (Exception e) {
            throw new IOException("接口返回了坏 JSON：" + pathOf(url));
        }
        Integer code = null;
        if (obj.has("status_code") && !obj.isNull("status_code")) {
            code = obj.optInt("status_code");
        } else if (obj.optJSONObject("BaseResp") != null
                && !obj.optJSONObject("BaseResp").isNull("StatusCode")) {
            code = obj.optJSONObject("BaseResp").optInt("StatusCode");
        }
        if (code != null && code != 0) {
            String msg = obj.optString("status_msg", "");
            if (msg.isEmpty()) {
                JSONObject base = obj.optJSONObject("BaseResp");
                if (base != null) msg = base.optString("StatusMessage", "");
            }
            if (code == 8 || isLoginError(msg)) throw new LoginException(msg.isEmpty() ? "登录已失效" : msg);
            throw new IOException(msg.isEmpty() ? ("接口报错 status_code=" + code) : msg);
        }
        return obj;
    }

    private static boolean isLoginError(String text) {
        String s = text == null ? "" : text.toLowerCase(Locale.ROOT);
        return s.contains("未登录") || s.contains("登录已") || s.contains("登录失效")
                || s.contains("not login") || s.contains("login required");
    }

    private static String q(String k, String v) {
        try {
            return k + "=" + URLEncoder.encode(v, "UTF-8");
        } catch (Exception e) {
            return k + "=" + v;
        }
    }

    // ------------------------------------------------------------ 认号
    /** 跑一次 user/info，把抖音号认出来；失败重试几次（刚扫码后 Cookie 还没写完）。 */
    public static Identity identity(CookieJar jar, int retries) throws IOException, LoginException {
        Exception last = null;
        for (int i = 0; i < Math.max(1, retries); i++) {
            for (String p : new String[]{"/aweme/v1/creator/user/info/",
                    "/aweme/v1/creator/pc/user/info/"}) {
                try {
                    JSONObject obj = json(BASE + p, jar, "GET", null);
                    Identity id = parseIdentity(obj);
                    if (id.ok()) return id;
                    last = new IOException("登录成功但没认出抖音号");
                } catch (LoginException e) {
                    last = e;
                } catch (IOException e) {
                    last = e;
                }
            }
            if (i + 1 < retries) {
                try {
                    Thread.sleep(2000);
                } catch (InterruptedException ignored) {
                    Thread.currentThread().interrupt();
                }
            }
        }
        if (last instanceof LoginException) throw (LoginException) last;
        throw new IOException(last == null ? "认号失败" : String.valueOf(last.getMessage()));
    }

    private static Identity parseIdentity(JSONObject root) {
        Identity best = new Identity();
        List<Identity> found = new ArrayList<>();
        walkIdentity(root, found);
        for (Identity id : found) {
            // 优先有抖音号（unique/short）的，其次有名字的
            boolean better = best.handle.isEmpty()
                    || (best.name.isEmpty() && !id.name.isEmpty());
            if (better) best = id;
        }
        return best;
    }

    private static void walkIdentity(Object o, List<Identity> out) {
        if (o instanceof JSONObject) {
            JSONObject j = (JSONObject) o;
            String nick = firstStr(j, "nickname", "nick_name", "nickName", "name");
            String uid = firstStr(j, "user_id", "uid", "userId");
            String unique = firstStr(j, "unique_id", "uniqueId", "douyin_unique_id", "douyinUniqueId");
            String shortId = firstStr(j, "short_id", "shortId");
            if (!nick.isEmpty() && !(uid.isEmpty() && unique.isEmpty() && shortId.isEmpty())) {
                Identity id = new Identity();
                id.name = nick;
                id.userId = uid;
                id.handle = !unique.isEmpty() ? unique : (!shortId.isEmpty() ? shortId : uid);
                out.add(id);
            }
            java.util.Iterator<String> keys = j.keys();
            while (keys.hasNext()) {
                String k = keys.next();
                try {
                    walkIdentity(j.opt(k), out);
                } catch (Exception ignored) {
                }
            }
        } else if (o instanceof JSONArray) {
            JSONArray a = (JSONArray) o;
            for (int i = 0; i < a.length(); i++) walkIdentity(a.opt(i), out);
        }
    }

    private static String firstStr(JSONObject j, String... keys) {
        for (String k : keys) {
            String v = j.optString(k, "");
            if (v != null && !v.isEmpty() && !"0".equals(v) && !"null".equals(v)) return v.trim();
        }
        return "";
    }

    // ------------------------------------------------------------ 作品列表
    public static List<JSONObject> works(CookieJar jar) throws IOException, LoginException {
        List<JSONObject> out = new ArrayList<>();
        long cursor = 0;
        for (int page = 0; page < 30; page++) {
            String url = BASE + "/web/api/creator/item/list?"
                    + q("count", "100") + "&" + q("max_cursor", String.valueOf(cursor))
                    + "&" + q("fields", "metrics,review,visibility") + "&" + q("need_long_article", "1");
            JSONObject obj = json(url, jar, "GET", null);
            JSONArray items = obj.optJSONArray("items");
            if (items == null) break;
            for (int i = 0; i < items.length(); i++) {
                JSONObject it = items.optJSONObject(i);
                if (it != null) out.add(it);
            }
            if (!obj.optBoolean("has_more")) break;
            long nxt = obj.optLong("max_cursor", 0);
            if (nxt == 0 || nxt == cursor) break;
            cursor = nxt;
        }
        return out;
    }

    // ------------------------------------------------------------ 概览 / 粉丝
    public static JSONArray dashboard(CookieJar jar, int days) throws IOException, LoginException {
        JSONObject obj = json(BASE + "/janus/douyin/creator/data/overview/dashboard", jar,
                "POST", "{\"recent_days\":" + days + "}");
        JSONArray m = obj.optJSONArray("metrics");
        return m == null ? new JSONArray() : m;
    }

    public static JSONArray fans(CookieJar jar, int days) throws IOException, LoginException {
        JSONObject obj = json(BASE + "/janus/douyin/creator/data/overview/dashboard/fans?"
                + q("recent_days", String.valueOf(days)), jar, "GET", null);
        JSONArray m = obj.optJSONArray("metrics");
        return m == null ? new JSONArray() : m;
    }

    // ------------------------------------------------------------ 解析（对齐 core/douyin.py）
    /** 作品列表一条 -> 本模块 works 的一条；认不出返回 null。 */
    public static JSONObject toWork(JSONObject item) {
        if (item == null) return null;
        JSONObject metrics = item.optJSONObject("metrics");
        JSONObject stats = item.optJSONObject("statistics");
        if (stats == null) stats = item.optJSONObject("stats");

        long created = item.optLong("create_time", item.optLong("publish_time", 0));
        if (created <= 0) created = item.optLong("createTime", 0);
        String title = item.optString("description", "");
        if (title.isEmpty()) title = item.optString("desc", "");
        if (title.isEmpty()) title = item.optString("title", "");
        if (title.isEmpty() && created <= 0) return null;

        JSONObject out = new JSONObject();
        try {
            out.put("aweme_id", item.optString("id", item.optString("aweme_id", "")));
            out.put("title", title.trim());
            String publishedAt = "";
            String date = "";
            if (created > 0) {
                SimpleDateFormat f1 = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.CHINA);
                SimpleDateFormat f2 = new SimpleDateFormat("yyyy-MM-dd", Locale.CHINA);
                Date d = new Date(created * 1000L);
                publishedAt = f1.format(d);
                date = f2.format(d);
            }
            out.put("published_at", publishedAt);
            out.put("date", date);

            int type = item.optInt("type", 0);
            String media = mediaType(type);
            if (media.isEmpty()) {
                JSONArray images = item.optJSONArray("images");
                media = images != null && images.length() > 0 ? "图文" : "视频";
            }
            out.put("media_type", media);

            JSONObject review = item.optJSONObject("review");
            String status = (review == null || review.isNull("status")
                    || review.optInt("status", 2) == 2) ? "公开" : "未公开";
            out.put("status", status);

            Double plays = numOrNull(metrics, stats, "view_count", "play_count", "play_cnt");
            out.put("plays", plays == null ? 0.0 : plays);
            putMaybe(out, "finish_rate", numOrNull(metrics, stats, "completion_rate"));
            putMaybe(out, "finish5_rate", numOrNull(metrics, stats, "completion_rate_5s"));
            putMaybe(out, "cover_ctr", numOrNull(metrics, stats, "cover_click_rate", "cover_click_ratio"));
            putMaybe(out, "bounce2_rate", numOrNull(metrics, stats, "bounce_rate_2s"));
            putMaybe(out, "avg_duration", numOrNull(metrics, stats, "avg_view_second", "average_play_duration"));
            out.put("likes", num(metrics, stats, "like_count", "digg_count", 0.0));
            out.put("shares", num(metrics, stats, "share_count", 0.0));
            out.put("comments", num(metrics, stats, "comment_count", 0.0));
            out.put("collects", num(metrics, stats, "favorite_count", "collect_count", 0.0));
            out.put("profile_visits", num(metrics, stats,
                    "homepage_visit_count", "profile_visit_count", 0.0));
            Double fans = numOrNull(metrics, stats, "fans_delta");
            if (fans == null) {
                fans = num(metrics, stats, "subscribe_count", 0.0)
                        - num(metrics, stats, "unsubscribe_count", 0.0);
            }
            out.put("fans_delta", fans);
        } catch (Exception e) {
            return null;
        }
        return out;
    }

    private static void putMaybe(JSONObject o, String k, Double v) {
        try {
            if (v == null) o.put(k, JSONObject.NULL);
            else o.put(k, v);
        } catch (Exception ignored) {
        }
    }

    private static String mediaType(int type) {
        switch (type) {
            case 1: return "图文";
            case 2: return "1min-视频";
            case 3: return "1-3min视频";
            case 4: return "3-5min视频";
            case 5: return "5min+视频";
            case 8: return "长图文";
            default: return "";
        }
    }

    private static Double rawNum(JSONObject metrics, JSONObject stats, String name) {
        for (JSONObject j : new JSONObject[]{metrics, stats}) {
            if (j == null || !j.has(name)) continue;
            Object v = j.opt(name);
            if (v == null || v == JSONObject.NULL) continue;
            double d = toDouble(v);
            if (!Double.isNaN(d)) return d;
        }
        return null;
    }

    private static Double numOrNull(JSONObject metrics, JSONObject stats, String... names) {
        for (String n : names) {
            Double v = rawNum(metrics, stats, n);
            if (v != null) return v;
        }
        return null;
    }

    private static double num(JSONObject metrics, JSONObject stats, String name, double def) {
        Double v = rawNum(metrics, stats, name);
        return v == null ? def : v;
    }

    private static double num(JSONObject metrics, JSONObject stats, String a, String b, double def) {
        Double v = numOrNull(metrics, stats, a, b);
        return v == null ? def : v;
    }

    static double toDouble(Object v) {
        if (v == null || v == JSONObject.NULL) return Double.NaN;
        if (v instanceof Number) return ((Number) v).doubleValue();
        String s = String.valueOf(v).trim();
        if (s.isEmpty() || s.equals("-") || s.equals("—") || s.equals("/")) return Double.NaN;
        if (s.endsWith("%")) {
            try {
                return Double.parseDouble(s.substring(0, s.length() - 1)) / 100.0;
            } catch (NumberFormatException e) {
                return Double.NaN;
            }
        }
        try {
            return Double.parseDouble(s.replace(",", ""));
        } catch (NumberFormatException e) {
            return Double.NaN;
        }
    }

    // ------------------------------------------------------------ 每日趋势映射
    /** 创作者中心指标名 -> daily 字段（与 core/douyin.py 的 DASH_FIELDS 一致）。 */
    private static final Map<String, String> DASH_FIELDS = new HashMap<>();
    static {
        String[][] rows = {
                {"publish_cnt", "posts"}, {"publish_count", "posts"}, {"item_cnt", "posts"},
                {"aweme_cnt", "posts"}, {"publish_activation", "posts"},
                {"vv", "plays"}, {"play_count", "plays"}, {"play_cnt", "plays"},
                {"total_play", "plays"}, {"total_play_count", "plays"},
                {"like", "likes"}, {"like_count", "likes"}, {"digg_count", "likes"}, {"digg_cnt", "likes"},
                {"share", "shares"}, {"share_count", "shares"}, {"share_cnt", "shares"},
                {"comment", "comments"}, {"comment_count", "comments"}, {"comment_cnt", "comments"},
                {"completion_rate_5s", "finish5_rate"}, {"finish5s", "finish5_rate"},
                {"completion_rate", "finish5_rate"},
                {"bounce_rate_2s", "bounce2_rate"}, {"skip2s", "bounce2_rate"},
                {"cover_click_ratio", "cover_ctr"}, {"cover_click_rate", "cover_ctr"},
                {"average_play_duration", "avg_duration"}, {"play_avg_time", "avg_duration"},
                {"avg_play_time", "avg_duration"}, {"avg_view_second", "avg_duration"},
        };
        for (String[] r : rows) DASH_FIELDS.put(r[0], r[1]);
    }

    public static String dashKey(String name) {
        String s = (name == null ? "" : name.trim().toLowerCase(Locale.ROOT))
                .replaceAll("[^a-z0-9]+", "_")
                .replaceAll("^_+|_+$", "");
        return DASH_FIELDS.get(s);
    }

    public static boolean isRatioField(String field) {
        return "finish5_rate".equals(field) || "bounce2_rate".equals(field) || "cover_ctr".equals(field);
    }

    /** 接口偶尔给 28.64 而不是 0.2864，比率字段超过 1.5 就当百分数。 */
    public static Double dashValue(String field, Object v) {
        double d = toDouble(v);
        if (Double.isNaN(d)) return null;
        if (isRatioField(field) && d > 1.5) d /= 100.0;
        return d;
    }

    /** "20261109" / 秒或毫秒时间戳 / "2026-11-09" -> "2026-11-09"；认不出返回 ""。 */
    public static String dashDate(Object v) {
        if (v == null || v == JSONObject.NULL) return "";
        double d = toDouble(v);
        if (!Double.isNaN(d) && d > 1_000_000_000d) {
            long ms = d > 1_000_000_000_000d ? (long) d : (long) (d * 1000);
            return new SimpleDateFormat("yyyy-MM-dd", Locale.CHINA).format(new Date(ms));
        }
        String s = String.valueOf(v).trim();
        if (s.matches("^\\d{8}$")) {
            return s.substring(0, 4) + "-" + s.substring(4, 6) + "-" + s.substring(6, 8);
        }
        if (s.matches("^\\d{4}[-/.]\\d{1,2}[-/.]\\d{1,2}.*$")) {
            String[] p = s.split("[-/.]");
            return String.format(Locale.ROOT, "%04d-%02d-%02d",
                    Integer.parseInt(p[0]), Integer.parseInt(p[1]), Integer.parseInt(p[2]));
        }
        return "";
    }
}
