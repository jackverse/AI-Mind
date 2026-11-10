package com.jackverse.secondbrain;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;
import android.util.Base64;

/**
 * 自动更新：查版本 → 下载 APK → 校验 sha256。
 *
 * 版本信息读仓库根目录的 version.json（Contents API，私有仓库用 Token）：
 *   {"versionCode": 3, "versionName": "1.2", "apk": "hub-android.apk",
 *    "sha256": "…", "notes": "这次改了什么"}
 * APK 本体放在 GitHub Release 资产里（Contents API 只有 1MB 上限）。
 *
 * 安装交给系统安装器：普通 app 装不了静默安装（要系统签名/root），
 * 所以最后一步一定是用户点「安装」。
 */
public class Updater {

    public static final String API = "https://api.github.com";

    public static class Info {
        public int code;
        public String name = "";
        public String apk = "";
        public String sha256 = "";
        public String notes = "";
        /** APK 字节数（version.json 里带的，用来在下载前告诉用户多大） */
        public long size = 0L;
        /** 这个包是从哪来的：Release vX.Y.Z / 仓库文件（排查更新问题时看这个） */
        public String source = "";
    }

    // ------------------------------------------------------------ HTTP
    private static HttpURLConnection open(String url, String token) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(20000);
        // 手机网慢的时候一个 read 可能卡很久，60s 会把半个包下崩（实测「更新失败：timeout」）
        c.setReadTimeout(120000);
        c.setInstanceFollowRedirects(true);
        c.setRequestProperty("User-Agent", "secondbrain-app");
        c.setRequestProperty("Accept", "application/vnd.github+json");
        if (token != null && !token.trim().isEmpty()) {
            c.setRequestProperty("Authorization", "Bearer " + token.trim());
        }
        return c;
    }

    private static String text(HttpURLConnection c) throws IOException {
        int code = c.getResponseCode();
        if (code != 200) {
            throw new IOException("HTTP " + code + " " + c.getURL().getPath());
        }
        try (InputStream in = c.getInputStream()) {
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            byte[] b = new byte[8192];
            int n;
            while ((n = in.read(b)) > 0) buf.write(b, 0, n);
            return new String(buf.toByteArray(), "UTF-8");
        }
    }

    // ------------------------------------------------------------ 查版本
    /** version.json 按包名分条目：
     *  {"com.jackverse.secondbrain": {"versionCode":3,...},
     *   "com.jackverse.secondbrain.watch": {"versionCode":3,...}} */
    public static Info check(String repo, String branch, String token, String pkg) throws Exception {
        String url = API + "/repos/" + repo + "/contents/version.json?ref=" + branch;
        HttpURLConnection c = open(url, token);
        JSONObject file = new JSONObject(text(c));
        String b64 = file.optString("content", "").replaceAll("\\s", "");
        if (b64.isEmpty()) throw new IOException("version.json 是空的");
        String json = new String(Base64.decode(b64, Base64.DEFAULT), "UTF-8");
        JSONObject all = new JSONObject(json);
        JSONObject v = all.optJSONObject(pkg);
        if (v == null) throw new IOException("version.json 里没有这个包名：" + pkg);
        Info info = new Info();
        info.code = v.optInt("versionCode", 0);
        info.name = v.optString("versionName", "");
        info.apk = v.optString("apk", "hub-android.apk");
        info.sha256 = v.optString("sha256", "");
        // notes 是整份 version.json 的顶层字段（发版时写一次，两个包共用）；
        // 老文件里也可能塞在包条目里，两边都认
        info.notes = all.optString("notes", v.optString("notes", ""));
        info.size = v.optLong("size", 0L);
        return info;
    }

    // ------------------------------------------------------------ 下载
    /**
     * 优先从最新 Release 的资产里拿；没有再退回仓库内文件（&lt;1MB 才行）。
     * 手机网不稳，失败自动重试一次（实测半个包 timeout 过）。
     */
    public static File download(Info info, String repo, String token, File dir,
                                Progress p) throws Exception {
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("建目录失败：" + dir);
        File out = new File(dir, info.apk);

        Exception lastErr = null;
        for (int attempt = 0; attempt < 2; attempt++) {
            try {
                fetch(info, repo, token, out, p);
                lastErr = null;
                break;
            } catch (Exception e) {
                lastErr = e;
                if (attempt == 0) {
                    if (p != null) p.update(0f);
                    try {
                        Thread.sleep(1200);
                    } catch (InterruptedException ignored) {
                    }
                }
            }
        }
        if (lastErr != null) throw lastErr;

        if (!info.sha256.isEmpty()) {
            String got = sha256(out);
            if (!got.equalsIgnoreCase(info.sha256)) {
                //noinspection ResultOfMethodCallIgnored
                out.delete();
                throw new IOException("sha256 不对，已删掉下载的文件\n期望 " + info.sha256 + "\n实际 " + got);
            }
        }
        return out;
    }

    private static void fetch(Info info, String repo, String token, File out, Progress p)
            throws Exception {
        String assetUrl = findAsset(repo, token, info.apk);
        if (assetUrl != null) {
            info.source = "Release v" + info.name;
            HttpURLConnection c = open(assetUrl, token);
            c.setRequestProperty("Accept", "application/octet-stream");
            int code = c.getResponseCode();
            if (code != 200) throw new IOException("下载 HTTP " + code);
            saveStream(c, out, c.getContentLength(), p);
        } else {
            // 没发 Release 就从仓库文件拉：先 apk/，再根目录（Contents API 单文件上限 1MB）
            info.source = "仓库文件";
            String[] paths = { "apk/" + info.apk, info.apk };
            IOException last = null;
            boolean done = false;
            for (String path : paths) {
                try {
                    HttpURLConnection c = open(API + "/repos/" + repo + "/contents/" + path, token);
                    JSONObject file = new JSONObject(text(c));
                    byte[] raw = Base64.decode(file.optString("content", "").replaceAll("\\s", ""),
                            Base64.DEFAULT);
                    try (OutputStream os = new FileOutputStream(out)) {
                        os.write(raw);
                    }
                    if (p != null) p.update(1.0f);
                    done = true;
                    break;
                } catch (Exception e) {
                    last = e instanceof IOException ? (IOException) e : new IOException(e);
                }
            }
            if (!done) {
                throw new IOException("找不到 " + info.apk + "（先把 APK 传进仓库或发到 Release）"
                        + (last == null ? "" : "：" + last.getMessage()));
            }
        }
    }

    /**
     * 找工作区里有没有这个 APK 资产。
     * 先看 releases/latest；没有再看最近 30 个 release —— 因为桌面端发版也会占掉 latest，
     * 只认 latest 的话「刚发完桌面版」就会误判成「没有 APK」而退回仓库文件（那可能是旧的）。
     */
    private static String findAsset(String repo, String token, String name) {
        String fromLatest = apiAsset(API + "/repos/" + repo + "/releases/latest", token, name);
        if (fromLatest != null) return fromLatest;
        try {
            JSONArray list = new JSONArray(text(open(
                    API + "/repos/" + repo + "/releases?per_page=30", token)));
            for (int i = 0; i < list.length(); i++) {
                JSONObject rel = list.getJSONObject(i);
                if (rel.optBoolean("draft")) continue;
                String url = assetIn(rel.optJSONArray("assets"), name);
                if (url != null) return url;
            }
        } catch (Exception ignored) {
            // 没 Release 就走仓库文件
        }
        return null;
    }

    private static String apiAsset(String url, String token, String name) {
        try {
            HttpURLConnection c = open(url, token);
            if (c.getResponseCode() != 200) return null;
            return assetIn(new JSONObject(text(c)).optJSONArray("assets"), name);
        } catch (Exception ignored) {
            return null;
        }
    }

    private static String assetIn(JSONArray assets, String name) {
        if (assets == null) return null;
        for (int i = 0; i < assets.length(); i++) {
            JSONObject a = assets.optJSONObject(i);
            if (a != null && name.equals(a.optString("name"))) {
                return a.optString("url");
            }
        }
        return null;
    }

    private static void saveStream(HttpURLConnection c, File out, int total, Progress p)
            throws IOException {
        File tmp = new File(out.getPath() + ".part");
        try (InputStream in = c.getInputStream();
             OutputStream os = new FileOutputStream(tmp)) {
            byte[] b = new byte[65536];
            int n, done = 0;
            while ((n = in.read(b)) > 0) {
                os.write(b, 0, n);
                done += n;
                if (p != null && total > 0) p.update(Math.min(1f, done / (float) total));
            }
        }
        if (!tmp.renameTo(out)) {
            //noinspection ResultOfMethodCallIgnored
            out.delete();
            if (!tmp.renameTo(out)) throw new IOException("写入 APK 失败");
        }
    }

    public static String sha256(File f) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        try (InputStream in = new java.io.FileInputStream(f)) {
            byte[] b = new byte[65536];
            int n;
            while ((n = in.read(b)) > 0) md.update(b, 0, n);
        }
        StringBuilder sb = new StringBuilder();
        for (byte x : md.digest()) sb.append(String.format("%02x", x));
        return sb.toString();
    }

    public interface Progress {
        void update(float ratio);
    }
}
