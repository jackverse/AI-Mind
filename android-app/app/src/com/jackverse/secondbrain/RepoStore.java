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
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * 手机上的「仓库副本」：只存 data/hub/ 下的账号与作品数据。
 * 首次启动从 APK 里的 seed 复制一份，之后由 GitHub 同步覆盖。
 */
public class RepoStore implements SyncStore {

    private final Context ctx;
    private final File root;

    public RepoStore(Context ctx) {
        this.ctx = ctx;
        this.root = new File(ctx.getFilesDir(), "repo");
    }

    public File root() {
        return root;
    }

    // ------------------------------------------------------------ 种子数据
    public void ensureSeed() {
        if (new File(root, "data").isDirectory()) return;
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
        return rel.startsWith("data/hub/") && rel.endsWith(".json");
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
}
