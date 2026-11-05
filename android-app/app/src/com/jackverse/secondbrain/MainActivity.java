package com.jackverse.secondbrain;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.ProgressDialog;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/**
 * 第二大脑 Android：半离线。
 * 本地留一份 notes/ + data/hub/ 的副本（首启来自 APK 内置快照），点「☁」直接跟 GitHub 仓库同步。
 */
public class MainActivity extends Activity {

    private static final String HOME_URL =
            "https://appassets.androidplatform.net/assets/web/index.html";

    private WebView web;
    private SharedPreferences prefs;
    private RepoStore store;
    private View splash;
    private boolean syncing = false;
    private long lastBackAt = 0L;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("second-brain", MODE_PRIVATE);
        store = new RepoStore(this);
        store.ensureSeed();
        if ((getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            WebView.setWebContentsDebuggingEnabled(true);
        }
        buildUi();
    }

    // ------------------------------------------------------------------ UI
    private void buildUi() {
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#F4F6FA"));

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setLoadsImagesAutomatically(true);
        s.setSupportMultipleWindows(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        web.setBackgroundColor(Color.parseColor("#F4F6FA"));
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (uri == null || !"appassets.androidplatform.net".equals(uri.getHost())) return null;
                String path = uri.getPath();
                if (path == null) return null;
                if (path.startsWith("/")) path = path.substring(1);
                if (path.startsWith("assets/")) path = path.substring("assets/".length());
                try {
                    String mime = mimeOf(path);
                    Map<String, String> headers = new HashMap<>();
                    headers.put("Cache-Control", "no-store");
                    java.io.InputStream in;
                    try {
                        in = getAssets().open(path);
                    } catch (java.io.IOException first) {
                        // aapt2 在 Windows 上可能把资产路径存成反斜杠
                        in = getAssets().open(path.replace('/', '\\'));
                    }
                    return new WebResourceResponse(mime, isText(mime) ? "utf-8" : null,
                            200, "OK", headers, in);
                } catch (Exception e) {
                    Map<String, String> headers = new HashMap<>();
                    String msg = "not found: " + path + " / " + e;
                    return new WebResourceResponse("text/plain", "utf-8", 404, "Not Found",
                            headers, new java.io.ByteArrayInputStream(msg.getBytes()));
                }
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                hideSplash();
                injectBarButtons();
            }
        });
        web.addJavascriptInterface(new Bridge(), "AndroidRepo");
        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        splash = buildSplash();
        root.addView(splash, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        setContentView(root);
        web.loadUrl(HOME_URL);
    }

    private View buildSplash() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        box.setBackgroundColor(Color.parseColor("#1A202B"));

        TextView logo = new TextView(this);
        logo.setText("◈");
        logo.setTextSize(46);
        logo.setTextColor(Color.parseColor("#3D6EE0"));
        logo.setGravity(Gravity.CENTER);

        TextView name = new TextView(this);
        name.setText("第二大脑");
        name.setTextSize(21);
        name.setTextColor(Color.WHITE);
        name.setGravity(Gravity.CENTER);
        name.setPadding(0, dp(12), 0, 0);

        TextView hint = new TextView(this);
        hint.setText("正在打开本地数据…");
        hint.setTextSize(12);
        hint.setTextColor(Color.parseColor("#8FA2C4"));
        hint.setPadding(0, dp(8), 0, 0);

        box.addView(logo);
        box.addView(name);
        box.addView(hint);
        return box;
    }

    private void hideSplash() {
        if (splash == null || splash.getVisibility() != View.VISIBLE) return;
        splash.animate().alpha(0f).setDuration(180).withEndAction(new Runnable() {
            @Override
            public void run() {
                if (splash != null) {
                    splash.setVisibility(View.GONE);
                    splash = null;
                }
            }
        }).start();
    }

    private void injectBarButtons() {
        String js = "(function(){try{var bar=document.querySelector('.topbar-actions');if(!bar)return;"
                + "function add(id,label,title,fn){if(document.getElementById(id))return;"
                + "var b=document.createElement('button');b.id=id;b.className='icon-btn';b.title=title;"
                + "b.style.fontSize='14px';b.textContent=label;b.onclick=fn;bar.appendChild(b);}"
                + "add('app-sync','☁','同步 GitHub',function(){AndroidRepo.requestSync();});"
                + "add('app-settings','⚙','数据来源 / 同步设置',function(){AndroidRepo.openSettings();});"
                + "}catch(e){}})();";
        web.evaluateJavascript(js, null);
    }

    // -------------------------------------------------------------- 配置
    private String repo() {
        return prefs.getString("repo", "");
    }

    private String branch() {
        return prefs.getString("branch", "main");
    }

    private String token() {
        return prefs.getString("token", "");
    }

    private void showSettings() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(20), dp(6), dp(20), 0);

        final EditText repoInput = field("owner/repo", repo(), InputType.TYPE_TEXT_VARIATION_URI);
        final EditText branchInput = field("main", branch(), InputType.TYPE_CLASS_TEXT);
        final EditText tokenInput = field("ghp_… 或 github_pat_…", token(),
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);

        box.addView(label("仓库（owner/repo）"));
        box.addView(repoInput);
        box.addView(label("分支"));
        box.addView(branchInput);
        box.addView(label("Token（需要 repo 读写权限）"));
        box.addView(tokenInput);
        TextView tip = label("Token 只存在本机 App 私有目录；留空只能读公开仓库。\n同步会先推送本机复习进度，再拉取最新笔记与数据。");
        tip.setTextSize(11);
        tip.setTextColor(Color.parseColor("#8A94A6"));
        box.addView(tip);

        AlertDialog.Builder b = new AlertDialog.Builder(this);
        b.setTitle("GitHub 同步");
        b.setView(box);
        b.setPositiveButton("保存并同步", (dialog, which) -> {
            saveConfig(repoInput, branchInput, tokenInput);
            startSync();
        });
        b.setNeutralButton("只保存", (dialog, which) -> {
            saveConfig(repoInput, branchInput, tokenInput);
            toast("已保存");
        });
        b.setNegativeButton("取消", null);
        b.show();
    }

    private void saveConfig(EditText repoInput, EditText branchInput, EditText tokenInput) {
        prefs.edit()
                .putString("repo", repoInput.getText().toString().trim())
                .putString("branch", branchInput.getText().toString().trim())
                .putString("token", tokenInput.getText().toString().trim())
                .apply();
    }

    private EditText field(String hint, String value, int type) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setText(value);
        e.setSingleLine(true);
        e.setInputType(type);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.bottomMargin = dp(10);
        e.setLayoutParams(lp);
        return e;
    }

    private TextView label(String text) {
        TextView t = new TextView(this);
        t.setText(text);
        t.setTextSize(12);
        t.setTextColor(Color.parseColor("#5B6577"));
        t.setPadding(0, dp(4), 0, dp(2));
        return t;
    }

    // -------------------------------------------------------------- 同步
    private void startSync() {
        if (syncing) {
            toast("正在同步…");
            return;
        }
        if (repo().isEmpty()) {
            toast("先在 ⚙ 里填仓库（owner/repo）");
            showSettings();
            return;
        }
        if (token().isEmpty()) {
            toast("先在 ⚙ 里填 GitHub Token");
            showSettings();
            return;
        }
        syncing = true;
        final ProgressDialog pd = new ProgressDialog(this);
        pd.setTitle("同步 GitHub");
        pd.setMessage("准备中…");
        pd.setCancelable(false);
        pd.show();
        final GitHubClient client = new GitHubClient(repo(), token(), branch());
        new Thread(() -> {
            try {
                client.sync(store, msg -> runOnUiThread(() -> {
                    if (pd.isShowing()) pd.setMessage(msg);
                }));
                prefs.edit().putString("last_sync", now()).putString("last_error", "").apply();
                runOnUiThread(() -> {
                    syncing = false;
                    pd.dismiss();
                    toast("同步完成");
                    web.reload();
                });
            } catch (Exception e) {
                final String msg = e.getMessage() == null ? e.toString() : e.getMessage();
                prefs.edit().putString("last_error", msg).apply();
                runOnUiThread(() -> {
                    syncing = false;
                    pd.dismiss();
                    new AlertDialog.Builder(MainActivity.this)
                            .setTitle("同步失败")
                            .setMessage(msg)
                            .setPositiveButton("打开设置", (d, w) -> showSettings())
                            .setNegativeButton("知道了", null)
                            .show();
                });
            }
        }).start();
    }

    private static String now() {
        return new SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.CHINA).format(new Date());
    }

    private void toast(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show();
    }

    private int dp(int v) {
        return Math.round(getResources().getDisplayMetrics().density * v);
    }

    private static boolean isText(String mime) {        return mime.startsWith("text/") || mime.contains("json") || mime.contains("javascript")
                || mime.contains("svg") || mime.contains("xml") || mime.contains("manifest");
    }

    private static String mimeOf(String path) {
        String p = path.toLowerCase(Locale.ROOT);
        if (p.endsWith(".html")) return "text/html";
        if (p.endsWith(".css")) return "text/css";
        if (p.endsWith(".js")) return "application/javascript";
        if (p.endsWith(".json")) return "application/json";
        if (p.endsWith(".svg")) return "image/svg+xml";
        if (p.endsWith(".webmanifest")) return "application/manifest+json";
        if (p.endsWith(".png")) return "image/png";
        if (p.endsWith(".woff2")) return "font/woff2";
        return "application/octet-stream";
    }

    // -------------------------------------------------------------- Bridge
    private class Bridge {
        @JavascriptInterface
        public String dump() {
            return store.dump();
        }

        @JavascriptInterface
        public String answer(String subject, String qid, boolean ok) {
            return store.answer(subject, qid, ok);
        }

        @JavascriptInterface
        public String status() {
            JSONObject o = new JSONObject();
            try {
                o.put("repo", repo());
                o.put("branch", branch());
                o.put("lastSync", prefs.getString("last_sync", ""));
                o.put("lastError", prefs.getString("last_error", ""));
                o.put("dirty", store.dirty().size());
            } catch (Exception ignored) {
            }
            return o.toString();
        }

        @JavascriptInterface
        public void requestSync() {
            runOnUiThread(MainActivity.this::startSync);
        }

        @JavascriptInterface
        public void openSettings() {
            runOnUiThread(MainActivity.this::showSettings);
        }
    }

    // -------------------------------------------------------------- 生命周期
    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
            return;
        }
        long t = System.currentTimeMillis();
        if (t - lastBackAt < 2000) super.onBackPressed();
        else {
            lastBackAt = t;
            toast("再按一次退出");
        }
    }

    @Override
    protected void onPause() {
        if (web != null) web.onPause();
        super.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (web != null) web.onResume();
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.removeJavascriptInterface("AndroidRepo");
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
