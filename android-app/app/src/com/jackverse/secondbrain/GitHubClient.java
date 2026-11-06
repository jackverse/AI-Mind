package com.jackverse.secondbrain;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Base64;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/**
 * 直接从 GitHub 仓库拉取数据（不用电脑、不用装 git）。
 *
 * 拉取：GET git/trees/<分支>?recursive=1 → 只挑 data/hub/ 下的 JSON → 逐个 GET git/blobs。
 * 只读：手机端不改远程数据，登录/同步/导入仍在桌面 hub 做。
 *
 * 为什么不用真的 git 协议：手机上没有 git 二进制，JGit 会让 APK 多 4MB 且 github.com 的 HTTPS
 * 在国内经常被重置；api.github.com 实测可用。
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
        if (wanted.isEmpty()) throw new IOException("仓库里没有 data/hub/ 数据");

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

    // ------------------------------------------------------------ 工具
    static boolean wantedPath(String path) {
        if (path == null || !path.startsWith("data/hub/") || !path.endsWith(".json")) {
            return false;
        }
        if (path.contains("/auth.")) return false;
        if (path.endsWith("sync.json") || path.endsWith("mail.json")) return false;
        return true;
    }

    private String get(String path) throws IOException {
        return request("GET", path);
    }

    private String request(String method, String path) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(api + path).openConnection();
        c.setRequestMethod(method);
        c.setConnectTimeout(15000);
        c.setReadTimeout(30000);
        c.setRequestProperty("Accept", "application/vnd.github+json");
        c.setRequestProperty("X-GitHub-Api-Version", "2022-11-28");
        c.setRequestProperty("User-Agent", "ai-mind-android");
        if (!token.isEmpty()) c.setRequestProperty("Authorization", "Bearer " + token);
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
