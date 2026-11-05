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
 * 直接跟 GitHub 仓库同步（不用电脑、不用装 git）。
 *
 * 拉取：GET git/trees/<分支>?recursive=1 → 只挑 notes/ 与 data/hub/ 下的文本文件 → 逐个 GET git/blobs。
 * 推送：本机改动（review.json）通过 contents API 提交成一次 commit。
 *
 * 为什么不用真的 git 协议：手机上没有 git 二进制，JGit 会让 APK 多 4MB 且 github.com 的 HTTPS
 * 在国内经常被重置；api.github.com 实测可用，效果一样是「拉最新 commit / 提交新 commit」。
 */
public class GitHubClient {

    public interface Progress {
        void onProgress(String message);
    }

    private final String repo;
    private final String token;
    private final String branch;
    private final String api = "https://api.github.com";

    public GitHubClient(String repo, String token, String branch) {
        this.repo = (repo == null ? "" : repo.trim());
        this.token = token == null ? "" : token.trim();
        this.branch = (branch == null || branch.trim().isEmpty()) ? "main" : branch.trim();
    }

    public String branch() {
        return branch;
    }

    // ------------------------------------------------------------ 同步入口
    public int pull(SyncStore store, Progress progress) throws Exception {
        progress.onProgress("读取仓库目录…");
        JSONObject tree = new JSONObject(get("/repos/" + repo + "/git/trees/" + branch + "?recursive=1"));
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
            JSONObject blob = new JSONObject(get("/repos/" + repo + "/git/blobs/" + en.getValue()));
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
                JSONObject cur = new JSONObject(get("/repos/" + repo + "/contents/" + encodePath(path)
                        + "?ref=" + branch));
                sha = cur.optString("sha");
            } catch (IOException notFound) {
                // 新文件
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

    /** 先推本地改动，再拉远程（避免 pull 覆盖没上传的复习进度）。 */
    public void sync(SyncStore store, Progress progress) throws Exception {
        push(store, progress);
        pull(store, progress);
    }

    // ------------------------------------------------------------ 工具
    static boolean wantedPath(String path) {
        if (path == null) return false;
        if (path.startsWith("notes/")) {
            return path.endsWith(".md") || path.endsWith(".json") || path.endsWith(".jsonl");
        }
        if (path.startsWith("data/hub/") && path.endsWith(".json")) {
            if (path.contains("/auth.")) return false;
            if (path.endsWith("sync.json") || path.endsWith("mail.json")) return false;
            return true;
        }
        return false;
    }

    private static String encodePath(String path) throws Exception {
        StringBuilder sb = new StringBuilder();
        for (String part : path.split("/")) {
            if (sb.length() > 0) sb.append('/');
            sb.append(URLEncoder.encode(part, "UTF-8").replace("+", "%20"));
        }
        return sb.toString();
    }

    private String get(String path) throws IOException {
        return request("GET", path, null);
    }

    private String put(String path, String body) throws IOException {
        return request("PUT", path, body);
    }

    private String request(String method, String path, String body) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(api + path).openConnection();
        c.setRequestMethod(method);
        c.setConnectTimeout(15000);
        c.setReadTimeout(30000);
        c.setRequestProperty("Accept", "application/vnd.github+json");
        c.setRequestProperty("X-GitHub-Api-Version", "2022-11-28");
        c.setRequestProperty("User-Agent", "second-brain-android");
        if (!token.isEmpty()) c.setRequestProperty("Authorization", "Bearer " + token);
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
            String hint = code == 401 ? "（Token 无效或过期）"
                    : code == 403 ? "（权限不足或触发限流）"
                    : code == 404 ? "（仓库/分支不存在，或 Token 没有 repo 权限）" : "";
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
