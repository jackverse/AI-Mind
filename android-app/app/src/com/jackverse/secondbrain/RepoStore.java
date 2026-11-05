package com.jackverse.secondbrain;

import android.content.Context;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * 手机上的「仓库副本」：只存 notes/ 与 data/hub/ 的文本文件。
 * 首次启动从 APK 里的 seed 复制一份，之后由 GitHub 同步覆盖。
 */
public class RepoStore implements SyncStore {

    private final Context ctx;
    private final File root;
    private final File dirtyFile;

    public RepoStore(Context ctx) {
        this.ctx = ctx;
        this.root = new File(ctx.getFilesDir(), "repo");
        this.dirtyFile = new File(ctx.getFilesDir(), "dirty.txt");
    }

    public File root() {
        return root;
    }

    // ------------------------------------------------------------ 种子数据
    public void ensureSeed() {
        if (new File(root, "notes").isDirectory()) return;
        try {
            unzipSeed();
        } catch (IOException ignored) {
            // 没有 seed 也能跑，只是首屏为空
        }
    }

    private void unzipSeed() throws IOException {
        try (java.util.zip.ZipInputStream zin =
                     new java.util.zip.ZipInputStream(ctx.getAssets().open("seed.zip"))) {
            java.util.zip.ZipEntry entry;
            byte[] buf = new byte[8192];
            while ((entry = zin.getNextEntry()) != null) {
                File out = new File(root, entry.getName());
                if (entry.isDirectory()) {
                    //noinspection ResultOfMethodCallIgnored
                    out.mkdirs();
                    continue;
                }
                File parent = out.getParentFile();
                if (parent != null) {
                    //noinspection ResultOfMethodCallIgnored
                    parent.mkdirs();
                }
                try (OutputStream os = new FileOutputStream(out)) {
                    int n;
                    while ((n = zin.read(buf)) > 0) os.write(buf, 0, n);
                }
            }
        }
    }

    // ------------------------------------------------------------ dump 给前端
    public String dump() {
        JSONObject files = new JSONObject();
        walk(root, "", files);
        JSONObject out = new JSONObject();
        try {
            out.put("files", files);
            JSONObject meta = new JSONObject();
            meta.put("root", root.getAbsolutePath());
            out.put("meta", meta);
        } catch (Exception ignored) {
        }
        return out.toString();
    }

    private void walk(File dir, String prefix, JSONObject files) {
        File[] list = dir.listFiles();
        if (list == null) return;
        for (File f : list) {
            String name = f.getName();
            if (name.startsWith(".")) continue;
            String rel = prefix.isEmpty() ? name : prefix + "/" + name;
            if (f.isDirectory()) {
                if ("data/social".equals(rel)) continue;
                walk(f, rel, files);
                continue;
            }
            if (!wanted(rel)) continue;
            try {
                JSONObject o = new JSONObject();
                o.put("t", new String(read(rel), StandardCharsets.UTF_8));
                o.put("m", f.lastModified() / 1000);
                o.put("s", f.length());
                files.put(rel, o);
            } catch (Exception ignored) {
            }
        }
    }

    static boolean wanted(String rel) {
        if (rel.startsWith("notes/")) {
            return rel.endsWith(".md") || rel.endsWith(".json") || rel.endsWith(".jsonl");
        }
        return rel.startsWith("data/hub/") && rel.endsWith(".json");
    }

    // ------------------------------------------------------------ 刷题写回
    public String answer(String subject, String qid, boolean ok) {
        String rel = "notes/kb/" + subject + "/review.json";
        JSONObject review = new JSONObject();
        try {
            byte[] raw = read(rel);
            if (raw != null) review = new JSONObject(new String(raw, StandardCharsets.UTF_8));
        } catch (Exception ignored) {
        }
        JSONObject st = review.optJSONObject(qid);
        if (st == null) st = new JSONObject();
        try {
            String today = LocalDate.now().toString();
            st.put("seen", st.optInt("seen") + 1);
            st.put("last", today);
            if (ok) {
                int streak = st.optInt("streak") + 1;
                st.put("streak", streak);
                if (st.optInt("wrong") > 0 && !st.optBoolean("mastered")) {
                    if (streak >= 2) st.put("mastered", true);
                    else st.put("due", LocalDate.now().plusDays(3).toString());
                }
            } else {
                st.put("wrong", st.optInt("wrong") + 1);
                st.put("streak", 0);
                st.put("mastered", false);
                st.put("due", LocalDate.now().plusDays(1).toString());
            }
            review.put(qid, st);
            write(rel, review.toString(1).getBytes(StandardCharsets.UTF_8));
            markDirty(rel);
        } catch (Exception ignored) {
        }
        JSONObject res = new JSONObject();
        try {
            res.put("ok", true);
            res.put("state", st);
        } catch (Exception ignored) {
        }
        return res.toString();
    }

    // ------------------------------------------------------------ SyncStore
    @Override
    public byte[] read(String path) throws IOException {
        File f = new File(root, path);
        if (!f.isFile()) return null;
        try (InputStream in = new FileInputStream(f)) {
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            byte[] b = new byte[8192];
            int n;
            while ((n = in.read(b)) > 0) buf.write(b, 0, n);
            return buf.toByteArray();
        }
    }

    @Override
    public void write(String path, byte[] data) throws IOException {
        File f = new File(root, path);
        File parent = f.getParentFile();
        if (parent != null && !parent.isDirectory()) {
            //noinspection ResultOfMethodCallIgnored
            parent.mkdirs();
        }
        File tmp = new File(f.getPath() + ".tmp");
        try (OutputStream out = new FileOutputStream(tmp)) {
            out.write(data);
        }
        if (!tmp.renameTo(f)) {
            //noinspection ResultOfMethodCallIgnored
            f.delete();
            //noinspection ResultOfMethodCallIgnored
            tmp.renameTo(f);
        }
    }

    @Override
    public void prune(Set<String> keep) throws IOException {
        List<File> all = new ArrayList<>();
        collect(new File(root, "notes"), all);
        collect(new File(root, "data/hub"), all);
        String base = root.getPath() + File.separator;
        for (File f : all) {
            String rel = f.getPath().substring(base.length()).replace('\\', '/');
            if (!wanted(rel)) continue;
            if (keep.contains(rel)) continue;
            //noinspection ResultOfMethodCallIgnored
            f.delete();
        }
    }

    private void collect(File dir, List<File> out) {
        File[] list = dir.listFiles();
        if (list == null) return;
        for (File f : list) {
            if (f.isDirectory()) collect(f, out);
            else out.add(f);
        }
    }

    @Override
    public Set<String> dirty() {
        Set<String> set = new HashSet<>();
        if (!dirtyFile.isFile()) return set;
        try (InputStream in = new FileInputStream(dirtyFile)) {
            byte[] b = new byte[(int) dirtyFile.length()];
            int n = in.read(b);
            if (n > 0) {
                for (String line : new String(b, 0, n, StandardCharsets.UTF_8).split("\n")) {
                    if (!line.trim().isEmpty()) set.add(line.trim());
                }
            }
        } catch (IOException ignored) {
        }
        return set;
    }

    public void markDirty(String path) {
        Set<String> set = dirty();
        if (set.add(path)) saveDirty(set);
    }

    @Override
    public void clearDirty() throws IOException {
        //noinspection ResultOfMethodCallIgnored
        dirtyFile.delete();
    }

    private void saveDirty(Set<String> set) {
        try (OutputStream out = new FileOutputStream(dirtyFile)) {
            out.write(String.join("\n", set).getBytes(StandardCharsets.UTF_8));
        } catch (IOException ignored) {
        }
    }
}
