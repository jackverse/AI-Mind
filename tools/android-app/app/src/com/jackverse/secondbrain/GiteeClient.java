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
import java.util.Base64;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/**
 * 跟 Gitee 私有仓库同步（数据中心的默认实现）。
 *
 * 接口形状跟 GitHubClient 一致：trees 拉目录 → blobs 拉文件；contents 提交改动。
 * Gitee 用 access_token 查询参数鉴权，仓库必须是私有的（由设置页检查 private=true）。
 */
public class GiteeClient {

    public interface Progress {
        void onProgress(String message);
    }

    public static final String API = "https://gitee.com/api/v5";

    private final String repo;
    private final String token;
    private final String branch;

    public GiteeClient(String repo, String token, String branch) {
        this.repo = (repo == null ? "" : repo.trim());
        this.token = token == null ? "" : token.trim();
        this.branch = (branch == null || branch.trim().isEmpty()) ? "master" : branch.trim();
    }

    public String branch() {
        return branch;
    }

    /** 仓库信息：用来检查 private、默认分支、owner。 */
    public JSONObject info() throws Exception {
        return getJson("/repos/" + repo);
    }

    public int pull(SyncStore store, Progress progress) throws Exception {
        progress.onProgress("读取 Gitee 仓库目录…");
        String sha = branch;
        try {
            JSONObject br = getJson("/repos/" + repo + "/branches/" + branch);
            String c = br.optJSONObject("commit") == null ? "" : br.optJSONObject("commit").optString("sha");
            if (!c.isEmpty()) sha = c;
        } catch (Exception ignored) {
            // 拿不到分支 SHA 就直接用分支名试一次
        }
        JSONObject tree = getJson("/repos/" + repo + "/git/trees/" + sha + "?recursive=1");
        JSONArray entries = tree.optJSONArray("tree");
        if (entries == null) throw new IOException("仓库目录为空或分支不存在：" + branch);

        Map<String, String> wanted = new HashMap<>();
        for (int i = 0; i < entries.length(); i++) {
            JSONObject e = entries.getJSONObject(i);
            if (!"blob".equals(e.optString("type"))) continue;
            String path = e.optString("path");
            if (wantedPath(path)) wanted.put(path, e.optString("sha"));
        }
        if (wanted.isEmpty()) throw new IOException("仓库里没有 notes/ 或 data/hub/ 数据");

        int i = 0;
        Set<String> keep = new HashSet<>();
        for (Map.Entry<String, String> en : wanted.entrySet()) {
            JSONObject blob = getJson("/repos/" + repo + "/git/blobs/" + en.getValue());
            byte[] data = Base64.getMimeDecoder().decode(blob.getString("content"));
            store.write(en.getKey(), data);
            keep.add(en.getKey());
            i++;
            if (i % 20 == 0) progress.onProgress("下载 " + i + "/" + wanted.size());
        }
        store.prune(keep);
        progress.onProgress("已拉取 " + wanted.size() + " 个文件");
        return wanted.size();
    }

    public void push(SyncStore store, Progress progress) throws Exception {
        Set<String> dirty = store.dirty();
        if (dirty.isEmpty()) {
            progress.onProgress("没有要推送的改动");
            return;
        }
        for (String path : dirty) {
            byte[] data = store.read(path);
            if (data == null) continue;
            String sha = null;
            try {
                JSONObject cur = getJson("/repos/" + repo + "/contents/" + encodePath(path)
                        + "?ref=" + branch);
                sha = cur.optString("sha");
            } catch (IOException e) {
                String m = e.getMessage() == null ? "" : e.getMessage();
                if (!m.contains("HTTP 404")) throw e;
            }
            JSONObject body = new JSONObject();
            body.put("message", "android: 更新 " + path);
            body.put("content", Base64.getEncoder().encodeToString(data));
            body.put("branch", branch);
            if (sha != null && !sha.isEmpty()) body.put("sha", sha);
            put("/repos/" + repo + "/contents/" + encodePath(path), body.toString());
            progress.onProgress("已推送 " + path);
        }
        store.clearDirty();
    }

    public void sync(SyncStore store, Progress progress) throws Exception {
        push(store, progress);
        pull(store, progress);
    }

    // ------------------------------------------------------------ 工具
    static boolean wantedPath(String path) {
        return GitHubClient.wantedPath(path);
    }

    private static String encodePath(String path) throws Exception {
        StringBuilder sb = new StringBuilder();
        for (String part : path.split("/")) {
            if (sb.length() > 0) sb.append('/');
            sb.append(URLEncoder.encode(part, "UTF-8").replace("+", "%20"));
        }
        return sb.toString();
    }

    private String withToken(String path) {
        if (token.isEmpty()) return path;
        return path + (path.contains("?") ? "&" : "?") + "access_token="
                + URLEncoder.encode(token);
    }

    private String get(String path) throws IOException {
        IOException last = null;
        for (int attempt = 0; attempt < 3; attempt++) {
            try {
                return request("GET", path, null);
            } catch (IOException e) {
                last = e;
                sleep(600L * (attempt + 1));
            }
        }
        throw last;
    }

    private JSONObject getJson(String path) throws IOException {
        IOException last = null;
        for (int attempt = 0; attempt < 2; attempt++) {
            String text = get(path);
            try {
                return new JSONObject(text);
            } catch (org.json.JSONException e) {
                last = new IOException("Gitee 返回的不是完整 JSON（" + path + "）：" + e.getMessage()
                        + "。多半是网络断了半截，重试一次还这样，换 Wi-Fi / 流量再点同步");
                sleep(800);
            }
        }
        throw last;
    }

    private static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        }
    }

    private String put(String path, String body) throws IOException {
        return request("PUT", path, body);
    }

    private String request(String method, String path, String body) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(API + withToken(path)).openConnection();
        c.setRequestMethod(method);
        c.setConnectTimeout(15000);
        c.setReadTimeout(30000);
        c.setRequestProperty("Accept", "application/json");
        c.setRequestProperty("User-Agent", "second-brain-android");
        if (body != null) {
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            try (OutputStream out = c.getOutputStream()) {
                out.write(body.getBytes(StandardCharsets.UTF_8));
            }
        }
        int code = c.getResponseCode();
        InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
        String text = readAll(in);
        if (code >= 400) {
            String hint = code == 401 ? "（令牌无效或过期）"
                    : code == 403 ? "（权限不足，令牌要勾 projects）"
                    : code == 404 ? "（仓库/分支不存在，或令牌没有权限）" : "";
            throw new IOException("HTTP " + code + hint + "：" + shortText(text));
        }
        return text;
    }

    private static String readAll(InputStream in) throws IOException {
        if (in == null) return "";
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        byte[] b = new byte[8192];
        int n;
        while ((n = in.read(b)) > 0) buf.write(b, 0, n);
        return buf.toString("UTF-8");
    }

    private static String shortText(String s) {
        if (s == null) return "";
        s = s.replace('\n', ' ').trim();
        return s.length() > 200 ? s.substring(0, 200) : s;
    }
}
