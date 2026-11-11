package com.jackverse.secondbrain;

import android.app.Activity;
import android.content.Intent;
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
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
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
    private TokenStore tokens;
    private View splash;
    private boolean syncing = false;
    private boolean douyinSyncing = false;
    private long lastBackAt = 0L;
    /** 抖音登录页（独立 Activity）的请求码 */
    private static final int REQ_DOUYIN_LOGIN = 1001;

    // 顶部同步胶囊（灵动岛式）：git 更新/抖音抓取都跑后台线程，这里只飘一条提示，不弹框、不推内容
    private LinearLayout topBar;
    private ProgressBar topBarBar;
    private View topBarDot;
    private TextView topBarText;
    private final android.os.Handler uiHandler =
            new android.os.Handler(android.os.Looper.getMainLooper());
    private Runnable topBarHide;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("second-brain", MODE_PRIVATE);
        tokens = new TokenStore(prefs);
        store = new RepoStore(this);
        store.ensureSeed();
        installCrashHandler();
        if ((getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            WebView.setWebContentsDebuggingEnabled(true);
        }
        buildUi();
    }

    // ------------------------------------------------------------------ 崩溃日志
    /**
     * 闪退自查：把未捕获异常写到仓库副本 data/hub/crash.log，并标脏——
     * 下次点 ☁ 同步就随 commit 推回电脑，不用连 adb 也能知道为什么退的。
     */
    private void installCrashHandler() {
        final Thread.UncaughtExceptionHandler prev = Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler((t, e) -> {
            writeCrash(e, "线程 " + t.getName());
            if (prev != null) prev.uncaughtException(t, e);
        });
    }

    private void writeCrash(Throwable e, String where) {
        try {
            java.io.StringWriter sw = new java.io.StringWriter();
            e.printStackTrace(new java.io.PrintWriter(sw));
            String head = "=== " + now() + " · v" + myVersionName() + "(" + myVersionCode() + ")"
                    + " · " + android.os.Build.MANUFACTURER + " " + android.os.Build.MODEL
                    + " · Android " + android.os.Build.VERSION.RELEASE
                    + " · " + where + "\n";
            String text = head + sw + "\n";
            if (text.length() > 12000) text = text.substring(0, 12000);

            String rel = "data/hub/crash.log";
            String old = "";
            byte[] raw = store.read(rel);
            if (raw != null) old = new String(raw, java.nio.charset.StandardCharsets.UTF_8);
            String all = old + text;
            if (all.length() > 40000) all = all.substring(all.length() - 40000);
            store.write(rel, all.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            store.markDirty(rel);
            prefs.edit().putString("last_crash", now()).apply();
        } catch (Throwable ignored) {
            // 崩溃时再崩就真没救了，吞掉
        }
    }

    // ------------------------------------------------------------------ 分享接收
    /** 别的 app「分享到这」：文字直接进收件箱；文件读成文本再进（超过 2MB 拒绝）。 */
    private void intake(android.content.Intent intent) {
        if (intent == null) return;
        String action = intent.getAction();
        if (!android.content.Intent.ACTION_SEND.equals(action)
                && !android.content.Intent.ACTION_VIEW.equals(action)) {
            return;
        }
        String text = intent.getStringExtra(android.content.Intent.EXTRA_TEXT);
        String subject = intent.getStringExtra(android.content.Intent.EXTRA_SUBJECT);
        if (text == null) {
            android.net.Uri uri = intent.getData();
            if (uri == null && intent.getClipData() != null && intent.getClipData().getItemCount() > 0) {
                uri = intent.getClipData().getItemAt(0).getUri();
            }
            if (uri != null) text = readUri(uri);
        }
        if (text == null || text.trim().isEmpty()) {
            toast("没读到内容");
            return;
        }
        String body = (subject != null && !subject.trim().isEmpty() && !text.startsWith(subject))
                ? subject.trim() + "\n\n" + text : text;
        try {
            JSONObject out = new JSONObject(store.saveInbox(body, "分享"));
            toast(out.optBoolean("ok") ? "已收进收件箱" : ("没存上：" + out.optString("error")));
            if (web != null) web.reload();
        } catch (Exception e) {
            toast("没存上：" + e);
        }
    }

    private String readUri(android.net.Uri uri) {
        try (java.io.InputStream in = getContentResolver().openInputStream(uri)) {
            if (in == null) return null;
            java.io.ByteArrayOutputStream buf = new java.io.ByteArrayOutputStream();
            byte[] b = new byte[8192];
            int n, total = 0;
            while ((n = in.read(b)) > 0) {
                total += n;
                if (total > 2 * 1024 * 1024) return null;   // 超 2MB 不接，免得塞爆仓库
                buf.write(b, 0, n);
            }
            return new String(buf.toByteArray(), java.nio.charset.StandardCharsets.UTF_8);
        } catch (Exception e) {
            return null;
        }
    }

    @Override
    protected void onNewIntent(android.content.Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        intake(intent);
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

        // 顶部同步胶囊：浮在网页最上方（splash 之下、网页之上），宽度跟着文字走，不推动内容
        topBar = buildTopBar();
        FrameLayout.LayoutParams tlp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        tlp.gravity = Gravity.TOP | Gravity.CENTER_HORIZONTAL;
        tlp.topMargin = dp(6);
        topBar.setVisibility(View.GONE);
        root.addView(topBar, tlp);

        splash = buildSplash();
        root.addView(splash, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        setContentView(root);
        web.loadUrl(HOME_URL);
        intake(getIntent());      // 从别的 app「分享到第二大脑」进来的内容
        // 启动后静默查一次更新（有新版才弹窗）
        new android.os.Handler(getMainLooper()).postDelayed(() -> checkUpdate(true), 2500);
        // 顺手把「允许安装应用」提前要到：等到真有更新才去设置页，就来不及了
        new android.os.Handler(getMainLooper()).postDelayed(this::ensureInstallPermission, 1200);
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

    // ------------------------------------------------------------------ 顶部同步胶囊（灵动岛）
    /**
     * 一颗小小的悬浮胶囊，贴在屏幕最上方：同步 / 抖音抓取时出现，只做提示，不挡操作、不推内容。
     * 宽度跟着文字走、圆角、带投影，看起来像灵动岛；正文照常滚动，胶囊只是浮在上面。
     */
    private LinearLayout buildTopBar() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.HORIZONTAL);
        box.setGravity(Gravity.CENTER_VERTICAL);
        box.setBackground(pillBg("#F01A202B", "#33FFFFFF"));
        box.setPadding(dp(13), dp(7), dp(15), dp(7));
        box.setElevation(dp(10));

        topBarBar = new ProgressBar(this, null, android.R.attr.progressBarStyleSmall);
        topBarBar.setIndeterminate(true);
        topBarBar.setIndeterminateTintList(
                android.content.res.ColorStateList.valueOf(Color.parseColor("#5B8FF9")));
        LinearLayout.LayoutParams blp = new LinearLayout.LayoutParams(dp(15), dp(15));
        blp.rightMargin = dp(8);
        box.addView(topBarBar, blp);

        // 完成时的小圆点：绿=成功、红=失败；跑的时候藏起来，让位给转圈
        topBarDot = new View(this);
        LinearLayout.LayoutParams dlp = new LinearLayout.LayoutParams(dp(8), dp(8));
        dlp.rightMargin = dp(8);
        topBarDot.setBackground(dotBg("#3ED17A"));
        topBarDot.setVisibility(View.GONE);
        box.addView(topBarDot, dlp);

        topBarText = new TextView(this);
        topBarText.setTextSize(11.5f);
        topBarText.setTextColor(Color.WHITE);
        topBarText.setSingleLine(true);
        topBarText.setEllipsize(android.text.TextUtils.TruncateAt.END);
        topBarText.setMaxWidth((int) (getResources().getDisplayMetrics().widthPixels * 0.62f));
        box.addView(topBarText, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        box.setOnClickListener(v -> hideTopBar());
        return box;
    }

    private android.graphics.drawable.GradientDrawable pillBg(String color, String stroke) {
        android.graphics.drawable.GradientDrawable d = new android.graphics.drawable.GradientDrawable();
        d.setColor(Color.parseColor(color));
        d.setCornerRadius(dp(22));
        if (stroke != null) d.setStroke(dp(1), Color.parseColor(stroke));
        return d;
    }

    private android.graphics.drawable.GradientDrawable dotBg(String color) {
        android.graphics.drawable.GradientDrawable d = new android.graphics.drawable.GradientDrawable();
        d.setShape(android.graphics.drawable.GradientDrawable.OVAL);
        d.setColor(Color.parseColor(color));
        d.setCornerRadius(dp(4));
        return d;
    }

    /** 开始一个后台任务：胶囊从顶部滑下来，转圈 + 文字。 */
    private void topStart(final String text) {
        uiHandler.post(() -> {
            if (topBar == null) return;
            if (topBarHide != null) {
                uiHandler.removeCallbacks(topBarHide);
                topBarHide = null;
            }
            topBarBar.setVisibility(View.VISIBLE);
            topBarDot.setVisibility(View.GONE);
            topBarText.setText(text);
            topBar.setOnClickListener(v -> hideTopBar());
            topBar.setVisibility(View.VISIBLE);
            // 已经露着就别再从头动画，只把内容换掉，免得抖动
            if (topBar.getAlpha() >= 1f && topBar.getTranslationY() == 0f) return;
            topBar.setAlpha(0f);
            topBar.setTranslationY(-dp(18));
            topBar.setScaleX(0.92f);
            topBar.setScaleY(0.92f);
            topBar.animate().alpha(1f).translationY(0f).scaleX(1f).scaleY(1f)
                    .setDuration(220)
                    .setInterpolator(new android.view.animation.DecelerateInterpolator())
                    .start();
        });
    }

    /** 只换文字（进度回调来自后台线程）。 */
    private void topText(final String text) {
        uiHandler.post(() -> {
            if (topBarText != null) topBarText.setText(text);
        });
    }

    /**
     * 收尾：ok=true 绿点、5 秒后自己收；ok=false 红点、留到用户点掉。
     * 点一下 = 收起 + 可选的 onTap（比如刷新页面）；不自动 reload，免得把正在看的内容抽走。
     */
    private void topDone(final String text, final boolean ok, final Runnable onTap) {
        uiHandler.post(() -> {
            if (topBar == null) return;
            if (topBarHide != null) {
                uiHandler.removeCallbacks(topBarHide);
                topBarHide = null;
            }
            topBarBar.setVisibility(View.GONE);
            topBarDot.setBackground(dotBg(ok ? "#3ED17A" : "#FF5A5F"));
            topBarDot.setVisibility(View.VISIBLE);
            topBarText.setText(text);
            topBar.setOnClickListener(v -> {
                hideTopBar();
                // 默认点一下 = 去「我的」页看这条消息的完整版（胶囊几秒就收，记录不会丢）
                if (onTap != null) onTap.run();
                else openMePage();
            });
            topBar.setVisibility(View.VISIBLE);
            topBar.animate().alpha(1f).translationY(0f).scaleX(1f).scaleY(1f)
                    .setDuration(160).start();
            if (ok) {
                topBarHide = this::hideTopBar;
                uiHandler.postDelayed(topBarHide, 5000);
            }
        });
    }

    /** 收起胶囊：往上缩回去，不打断任何后台任务。 */
    private void hideTopBar() {
        uiHandler.post(() -> {
            if (topBarHide != null) {
                uiHandler.removeCallbacks(topBarHide);
                topBarHide = null;
            }
            if (topBar == null || topBar.getVisibility() != View.VISIBLE) return;
            topBar.animate().alpha(0f).translationY(-dp(14)).scaleX(0.94f).scaleY(0.94f)
                    .setDuration(160)
                    .setInterpolator(new android.view.animation.AccelerateInterpolator())
                    .withEndAction(() -> {
                        if (topBar != null) topBar.setVisibility(View.GONE);
                    }).start();
        });
    }

    // ------------------------------------------------------------------ 同步消息记录（「我的」页）
    /**
     * 顶部胶囊只飘几秒，点一下也就收了——所以每条结果都在本机留一份，
     * 「我的」页按时间倒序列出来，随时能翻。只记结果，不记中间过程。
     */
    private static final String EVENT_KEY = "event_log";
    private static final int EVENT_MAX = 80;

    private void logEvent(String kind, boolean ok, String text) {
        logEvent(kind, ok, text, "");
    }

    private void logEvent(String kind, boolean ok, String text, String detail) {
        try {
            JSONArray old = new JSONArray(prefs.getString(EVENT_KEY, "[]"));
            JSONObject o = new JSONObject();
            o.put("t", now());
            o.put("ts", System.currentTimeMillis());
            o.put("kind", kind);
            o.put("ok", ok);
            o.put("text", text == null ? "" : text);
            if (detail != null && !detail.trim().isEmpty()) o.put("detail", detail.trim());
            JSONArray out = new JSONArray();
            out.put(o);
            for (int i = 0; i < old.length() && out.length() < EVENT_MAX; i++) out.put(old.get(i));
            prefs.edit().putString(EVENT_KEY, out.toString()).apply();
        } catch (Exception ignored) {
        }
        // 页面正停在「我的」时让它立刻重画，不用等轮询
        uiHandler.post(() -> {
            if (web != null) {
                web.evaluateJavascript("window.__hubEventsUpdated&&window.__hubEventsUpdated()", null);
            }
        });
    }

    /** 胶囊点一下：那条消息的完整版在「我的」页，直接带过去看。 */
    private void openMePage() {
        if (web == null) return;
        web.evaluateJavascript("(function(){try{location.hash='#/me';}catch(e){}})();", null);
    }

    private void injectBarButtons() {
        String js = "(function(){try{var bar=document.querySelector('.topbar-actions');if(!bar)return;"
                + "function add(id,label,title,fn){if(document.getElementById(id))return;"
                + "var b=document.createElement('button');b.id=id;b.className='icon-btn';b.title=title;"
                + "b.style.fontSize='14px';b.textContent=label;b.onclick=fn;bar.appendChild(b);}"
                + "add('app-sync','☁','同步 Gitee',function(){AndroidRepo.requestSync();});"
                + "add('app-update','⬆','检查更新',function(){AndroidRepo.checkUpdate();});"
                + "}catch(e){}})();";
        web.evaluateJavascript(js, null);
    }

    // -------------------------------------------------------------- 配置
    /** 数据仓库：Gitee 私有仓库，owner/repo。 */
    private String repo() {
        return Repos.normalize(prefs.getString("gitee_repo", ""));
    }

    private String branch() {
        return prefs.getString("gitee_branch", "master");
    }

    /** 令牌只以 Keystore 密文落盘，运行时才解出来。 */
    private String token() {
        return tokens.get("gitee_token");
    }

    private void showSettings() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(20), dp(6), dp(20), 0);

        // 版本号放在最上面：出问题时一眼知道装的是哪一版
        TextView verLine = label("第二大脑 v" + myVersionName() + "（versionCode " + myVersionCode() + "）");
        verLine.setTextSize(11);
        verLine.setTextColor(Color.parseColor("#8A94A6"));
        box.addView(verLine);
        String lastCrash = prefs.getString("last_crash", "");
        if (!lastCrash.isEmpty()) {
            TextView crashLine = label("上次崩溃 " + lastCrash + "，已记到 data/hub/crash.log（下次同步带回电脑）");
            crashLine.setTextSize(10);
            crashLine.setTextColor(Color.parseColor("#C0392B"));
            box.addView(crashLine);
        }
        String lastApk = prefs.getString("last_apk", "");
        if (!lastApk.isEmpty()) {
            TextView apkLine = label("上次下载的更新包：" + lastApk);
            apkLine.setTextSize(10);
            apkLine.setTextColor(Color.parseColor("#8A94A6"));
            box.addView(apkLine);
        }

        final EditText repoInput = field("https://gitee.com/你的用户名/仓库名",
                Repos.webUrl(repo()), InputType.TYPE_TEXT_VARIATION_URI);
        final EditText branchInput = field("master", branch(), InputType.TYPE_CLASS_TEXT);
        final String oldToken = token();
        final EditText tokenInput = field("Gitee 私人令牌（必填）",
                oldToken.isEmpty() ? "" : "••••••••",
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        final android.widget.CheckBox autoUp = new android.widget.CheckBox(this);
        autoUp.setText("自动检查更新（发现新版先给你看更新内容，点了才下载）");
        autoUp.setTextSize(13);
        autoUp.setChecked(autoUpdate());
        autoUp.setPadding(0, dp(8), 0, dp(4));

        LinearLayout guide = new LinearLayout(this);
        guide.setOrientation(LinearLayout.HORIZONTAL);
        android.widget.Button regBtn = miniBtn("注册 Gitee");
        regBtn.setOnClickListener(v -> openUrl("https://gitee.com/signup"));
        android.widget.Button repoBtn = miniBtn("新建私有仓库");
        repoBtn.setOnClickListener(v -> openUrl("https://gitee.com/projects/new"));
        android.widget.Button tokenBtn = miniBtn("怎么拿令牌");
        tokenBtn.setOnClickListener(v -> showTokenGuide());
        guide.addView(regBtn);
        guide.addView(repoBtn);
        guide.addView(tokenBtn);
        box.addView(guide);

        box.addView(label("数据中心（必须是 Gitee 私有仓库，抖音数据存这里）"));
        box.addView(repoInput);
        box.addView(label("分支（新建仓库一般是 master）"));
        box.addView(branchInput);
        box.addView(label("私人令牌（只存加密后的密文）"));
        box.addView(tokenInput);
        android.widget.Button probeBtn = new android.widget.Button(this);
        probeBtn.setAllCaps(false);
        probeBtn.setText("检查仓库 / 令牌 / 分支");
        probeBtn.setOnClickListener(v -> probeConfig(repoInput, branchInput, tokenInput));
        box.addView(probeBtn);
        box.addView(autoUp);
        TextView tip = label("令牌用 Android Keystore 加密后才落盘，页面上只显示圆点。\n仓库必须是私有的：公开仓库等于把抖音数据给别人看。\n同步在后台跑，顶部灵动岛显示进度，不挡操作。");
        tip.setTextSize(11);
        tip.setTextColor(Color.parseColor("#8A94A6"));
        box.addView(tip);

        // ---------------------------------------------------------- 安装权限
        box.addView(label("安装权限（自动更新要用）"));
        TextView permState = label(canInstallApks()
                ? "已允许安装应用 ✓"
                : "未允许 —— 更新时系统会拦，需要点一次开关");
        permState.setTextSize(11);
        permState.setTextColor(Color.parseColor(canInstallApks() ? "#2E7D32" : "#C0392B"));
        box.addView(permState);
        android.widget.Button permBtn = new android.widget.Button(this);
        permBtn.setAllCaps(false);
        permBtn.setText(canInstallApks() ? "去查看/关闭" : "去打开");
        permBtn.setOnClickListener(v -> openInstallSettings());
        box.addView(permBtn);

        // ---------------------------------------------------------- 抖音（多账号）
        // 账号面板等对话框建好再加（面板上的按钮要把这个弹窗关掉）
        box.addView(label("抖音（手机自己抓，只读创作者中心）"));

        AlertDialog.Builder b = new AlertDialog.Builder(this);
        b.setTitle("我的数据仓库");
        android.widget.ScrollView scroll = new android.widget.ScrollView(this);
        scroll.addView(box);
        b.setView(scroll);
        b.setPositiveButton("保存并同步", (dialog, which) -> {
            if (saveConfig(repoInput, branchInput, tokenInput, autoUp)) startSync();
        });
        b.setNeutralButton("只保存", (dialog, which) -> {
            if (saveConfig(repoInput, branchInput, tokenInput, autoUp)) toast("已保存");
        });
        b.setNegativeButton("取消", null);
        final AlertDialog dlg = b.create();
        box.addView(douyinAccountsPanel(dlg::dismiss));
        dlg.show();
    }

    private void openUrl(String url) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        } catch (Exception e) {
            toast("打不开浏览器：" + url);
        }
    }

    private void showTokenGuide() {
        new AlertDialog.Builder(this)
                .setTitle("怎么拿 Gitee 令牌")
                .setMessage("1. 注册 / 登录 Gitee（用手机号即可）\n"
                        + "2. 新建一个仓库，可见性选「私有」\n"
                        + "3. 头像 → 设置 → 私人令牌 → 生成新令牌\n"
                        + "4. 勾选 projects 权限，生成后复制那串字符\n"
                        + "5. 回到这里填仓库地址（owner/repo）和令牌，点「保存并同步」\n\n"
                        + "令牌只用来读写你自己的私有仓库；App 里只存加密后的密文。")
                .setPositiveButton("去令牌页", (d, w) -> openUrl("https://gitee.com/profile/personal_access_tokens"))
                .setNegativeButton("知道了", null)
                .show();
    }

    /**
     * 现场体检：仓库 / 分支 / 根目录三个接口各打一次，
     * 哪一步 404 一眼看出来（私有仓库没权限时也常回 404）。
     */
    private void probeConfig(EditText repoInput, EditText branchInput, EditText tokenInput) {
        String raw = repoInput.getText().toString().trim();
        final String r = Repos.normalize(raw);
        if (r.isEmpty()) {
            toast("先填 Gitee 仓库地址：owner/repo");
            return;
        }
        String b = branchInput.getText().toString().trim();
        final String br = b.isEmpty() ? "master" : b;
        String t = tokenInput.getText().toString().trim();
        final String tok = t.startsWith("•") ? token() : t;

        final ProgressDialog pd = new ProgressDialog(this);
        pd.setMessage("正在检查 " + r + " …");
        pd.setCancelable(false);
        pd.show();

        new Thread(() -> {
            final StringBuilder sb = new StringBuilder();
            sb.append("仓库：").append(r).append("\n")
                    .append("分支：").append(br).append("\n")
                    .append("Token：").append(tok.isEmpty() ? "（空，只能读公开仓库）" : maskToken(tok))
                    .append("\n\n");
            int c1 = probe("/repos/" + r, tok);
            int c2 = probe("/repos/" + r + "/branches/" + br, tok);
            int c3 = probe("/repos/" + r + "/contents/?ref=" + br, tok);
            sb.append(probeLine("① 仓库能不能访问", c1)).append("\n")
                    .append(probeLine("② 分支是否存在", c2)).append("\n")
                    .append(probeLine("③ 根目录能不能读", c3)).append("\n\n")
                    .append(probeHint(c1, c2, c3));
            runOnUiThread(() -> {
                pd.dismiss();
                new AlertDialog.Builder(MainActivity.this)
                        .setTitle("配置检查")
                        .setMessage(sb.toString())
                        .setPositiveButton("知道了", null)
                        .show();
            });
        }).start();
    }

    private int probe(String path, String token) {
        java.net.HttpURLConnection c = null;
        try {
            String url = GiteeClient.API + path;
            if (!token.isEmpty()) {
                url += (path.contains("?") ? "&" : "?") + "access_token="
                        + java.net.URLEncoder.encode(token, "UTF-8");
            }
            c = (java.net.HttpURLConnection) new java.net.URL(url).openConnection();
            c.setConnectTimeout(15000);
            c.setReadTimeout(20000);
            c.setRequestProperty("User-Agent", "secondbrain-app");
            c.setRequestProperty("Accept", "application/json");
            return c.getResponseCode();
        } catch (Exception e) {
            return -1;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private static String probeLine(String label, int code) {
        return (code == 200 ? "✓ " : "✗ ") + label + "："
                + (code < 0 ? "连不上" : "HTTP " + code);
    }

    private static String probeHint(int c1, int c2, int c3) {
        if (c1 == 200 && c2 == 200 && c3 == 200) {
            return "三项都通：这个 Gitee 私有仓库可以当数据中心了。";
        }
        if (c1 == 404) {
            return "第①步就 404：仓库名写错了，或令牌对这个私有仓库没权限"
                    + "（Gitee 对无权限的私有仓库也常回 404）。";
        }
        if (c2 == 404) return "第②步 404：分支名不对，Gitee 新建仓库一般是 master。";
        if (c3 == 404) return "第③步 404：仓库和分支都在，但根目录读不到 —— 仓库是不是空的？先建一个 README 初始化。";
        if (c1 == 401 || c2 == 401 || c3 == 401) return "令牌无效或已被撤销：重新生成一个勾了 projects 的令牌。";
        if (c1 == 403 || c2 == 403 || c3 == 403) return "HTTP 403：权限不足（令牌要勾 projects）或被限流。";
        if (c1 < 0 || c2 < 0 || c3 < 0) return "连不上 gitee.com：网络把它拦了，换 Wi-Fi/流量再试。";
        return "按上面的 HTTP 码排查。";
    }

    private static String maskToken(String t) {
        if (t.length() <= 8) return "****（" + t.length() + " 字符）";
        return t.substring(0, 4) + "…" + t.substring(t.length() - 4) + "（" + t.length() + " 字符）";
    }

    // -------------------------------------------------------------- 抖音账号面板
    /** ⚙ 里的抖音账号面板：每个号一行（状态 + 同步 / 重登 / 解绑），下面一行登录·全部·验证。 */
    private View douyinAccountsPanel(final Runnable close) {
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);

        final java.util.List<String> handles = douyinHandles();
        if (handles.isEmpty()) {
            TextView empty = label("还没登录任何抖音号——点下面「登录新账号」，一次登一个，互不影响");
            empty.setTextSize(11);
            empty.setTextColor(Color.parseColor("#8A94A6"));
            col.addView(empty);
        }
        for (final String h : handles) {
            String name = prefs.getString(dyKey(h, "name"), "");
            String cookie = prefs.getString(dyKey(h, "cookie"), "");
            String loginAt = prefs.getString(dyKey(h, "login_at"), "");
            String last = prefs.getString(dyKey(h, "last"), "");
            String lastMsg = prefs.getString(dyKey(h, "last_msg"), "");

            TextView head = label((name.isEmpty() ? h : name) + "（" + h + "）"
                    + (cookie.isEmpty() ? " · 登录已失效" : ""));
            head.setTextSize(12);
            head.setTextColor(Color.parseColor(cookie.isEmpty() ? "#C0392B" : "#1F2430"));
            head.setPadding(0, dp(8), 0, 0);
            col.addView(head);

            StringBuilder meta = new StringBuilder();
            long days = daysSince(loginAt);
            if (days >= 0) meta.append("登录 ").append(days).append(" 天");
            if (last.isEmpty()) {
                if (meta.length() > 0) meta.append(" · ");
                meta.append("还没同步过");
            } else {
                if (meta.length() > 0) meta.append(" · ");
                meta.append("上次 ").append(last);
                if (!lastMsg.isEmpty()) meta.append("（").append(lastMsg).append("）");
            }
            TextView info = label(meta.toString());
            info.setTextSize(10);
            info.setTextColor(Color.parseColor(cookie.isEmpty() ? "#C0392B" : "#8A94A6"));
            col.addView(info);

            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            android.widget.Button sync = miniBtn("同步这个号");
            sync.setEnabled(!cookie.isEmpty());
            sync.setOnClickListener(v -> {
                close.run();
                startDouyinSync(h);
            });
            android.widget.Button again = miniBtn("重登");
            again.setOnClickListener(v -> {
                close.run();
                showDouyinLogin(h);
            });
            android.widget.Button del = miniBtn("解绑");
            del.setOnClickListener(v -> {
                close.run();
                confirmDeleteDouyin(h);
            });
            row.addView(sync, new LinearLayout.LayoutParams(0,
                    ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
            row.addView(again, new LinearLayout.LayoutParams(0,
                    ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
            row.addView(del, new LinearLayout.LayoutParams(0,
                    ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
            col.addView(row);
        }

        LinearLayout row2 = new LinearLayout(this);
        row2.setOrientation(LinearLayout.HORIZONTAL);
        android.widget.Button add = miniBtn("登录新账号");
        add.setOnClickListener(v -> {
            close.run();
            showDouyinLogin(null);
        });
        android.widget.Button all = miniBtn("同步全部");
        all.setOnClickListener(v -> {
            close.run();
            startDouyinSync();
        });
        android.widget.Button check = miniBtn("验证登录态");
        check.setOnClickListener(v -> {
            close.run();
            verifyDouyinAccounts();
        });
        row2.addView(add, new LinearLayout.LayoutParams(0,
                ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        row2.addView(all, new LinearLayout.LayoutParams(0,
                ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        row2.addView(check, new LinearLayout.LayoutParams(0,
                ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        col.addView(row2);

        TextView tip = label("每个号的 Cookie 分开存；登录新号时只清浏览器里的旧 Cookie、不发退出请求，"
                + "所以几个号可以同时在线。同步完自动 ☁ 推回仓库，手机和电脑的抖音页顶部都能看到每个号的标签。");
        tip.setTextSize(10);
        tip.setTextColor(Color.parseColor("#8A94A6"));
        tip.setPadding(0, dp(6), 0, 0);
        col.addView(tip);
        return col;
    }

    private android.widget.Button miniBtn(String text) {
        android.widget.Button btn = new android.widget.Button(this);
        btn.setText(text);
        btn.setAllCaps(false);
        btn.setTextSize(11);
        btn.setMinHeight(0);
        btn.setMinimumHeight(0);
        btn.setPadding(dp(2), dp(4), dp(2), dp(4));
        return btn;
    }

    /** 保存 Gitee 数据仓库设置；地址认不出 / 没令牌时不落盘（返回 false）。 */
    private boolean saveConfig(EditText repoInput, EditText branchInput, EditText tokenInput,
                               android.widget.CheckBox autoUp) {
        String raw = repoInput.getText().toString().trim();
        String repo = Repos.normalize(raw);
        if (repo.isEmpty()) {
            toast("仓库地址认不出来，示例：\nhttps://gitee.com/你的用户名/仓库名\n或 用户名/仓库名");
            return false;
        }
        String b = branchInput.getText().toString().trim();
        if (b.isEmpty()) b = "master";
        String t = tokenInput.getText().toString().trim();
        if (t.startsWith("•")) t = token();
        if (t.isEmpty()) {
            toast("先填 Gitee 私人令牌（点「怎么拿令牌」看步骤）");
            return false;
        }
        tokens.put("gitee_token", t);
        prefs.edit()
                .putString("gitee_repo", repo)
                .putString("gitee_branch", b)
                .putBoolean("auto_update", autoUp == null || autoUp.isChecked())
                .apply();
        verifyPrivate(repo, t, b);
        return true;
    }

    /** 数据中心必须是私有仓库：保存后后台查一次，公开仓库直接提醒。 */
    private void verifyPrivate(String repo, String token, String branch) {
        new Thread(() -> {
            try {
                org.json.JSONObject info = new GiteeClient(repo, token, branch).info();
                if (!info.optBoolean("private", false)) {
                    runOnUiThread(() -> toast("这个仓库不是私有的！请到 Gitee 把仓库改成私有，否则抖音数据会公开"));
                }
            } catch (Exception e) {
                runOnUiThread(() -> toast("仓库检查失败：" + e.getMessage()));
            }
        }).start();
    }

    // -------------------------------------------------------------- 安装权限（未知来源）
    private boolean installPermPrompted = false;

    /** Android 8+ 才需要「允许安装未知应用」；更早的版本默认就允许。 */
    private boolean canInstallApks() {
        if (android.os.Build.VERSION.SDK_INT < android.os.Build.VERSION_CODES.O) return true;
        return getPackageManager().canRequestPackageInstalls();
    }

    /**
     * 提前把「允许安装应用」要到手：普通 App 没有权限自己拨这个开关（系统安全限制），
     * 只能把用户带到那个设置页点一次。所以策略是——启动时就问一次，
     * 而不是等真有更新、点下载了才发现装不上。
     */
    private void ensureInstallPermission() {
        if (canInstallApks()) return;
        if (prefs.getBoolean("install_perm_muted", false)) return;
        installPermPrompted = true;
        new AlertDialog.Builder(this)
                .setTitle("先允许安装应用（只需一次）")
                .setMessage("以后有新版本，App 会自动下好、自动拉起安装器；"
                        + "但系统要求先允许「第二大脑」安装应用，否则每次都得手动去设置里开。\n\n"
                        + "下一步会跳到系统设置页，把「允许安装未知应用」打开再返回即可。")
                .setPositiveButton("去打开", (d, w) -> openInstallSettings())
                .setNeutralButton("不再提醒", (d, w) ->
                        prefs.edit().putBoolean("install_perm_muted", true).apply())
                .setNegativeButton("以后再说", (d, w) ->
                        prefs.edit().putBoolean("install_perm_asked", true).apply())
                .show();
    }

    /** 跳到本应用的「安装未知应用」开关页；各家 ROM 路径不同，逐级兜底。 */
    private void openInstallSettings() {
        String pkg = "package:" + getPackageName();
        Intent[] tries = {
                new Intent(android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse(pkg)),
                new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse(pkg)),
                new Intent(android.provider.Settings.ACTION_SECURITY_SETTINGS),
                new Intent(android.provider.Settings.ACTION_SETTINGS)
        };
        for (Intent i : tries) {
            try {
                startActivity(i);
                return;
            } catch (Exception ignored) {
                // 这一档这家 ROM 不认，试下一档
            }
        }
        toast("打不开设置页，请手动到「设置 → 应用 → 第二大脑 → 安装未知应用」打开");
    }

    // -------------------------------------------------------------- 抖音（多账号）
    // 每个号一套独立记录：cookie / name / login_at / last 全按号分开存，互不覆盖。
    private static final String DY_LIST = "douyin.handles";     // 逗号分隔，保持登录顺序

    private static String dyKey(String handle, String field) {
        return "douyin." + field + "." + handle;
    }

    /** 已登录的抖音号（老的「只存一个号」配置会先迁移过来）。 */
    private java.util.List<String> douyinHandles() {
        migrateDouyinPrefs();
        java.util.List<String> out = new java.util.ArrayList<>();
        for (String s : prefs.getString(DY_LIST, "").split(",")) {
            String h = s.trim();
            if (!h.isEmpty() && !out.contains(h)) out.add(h);
        }
        return out;
    }

    /** v1.16 及以前只存一个号（douyin_cookie / douyin_handle …），搬到按号分开的键上。 */
    private void migrateDouyinPrefs() {
        if (prefs.getBoolean("douyin.migrated", false)) return;
        String old = prefs.getString("douyin_handle", "");
        SharedPreferences.Editor e = prefs.edit().putBoolean("douyin.migrated", true);
        if (!old.isEmpty()) {
            String cookie = prefs.getString("douyin_cookie", "");
            if (!cookie.isEmpty() && prefs.getString(dyKey(old, "cookie"), "").isEmpty()) {
                e.putString(dyKey(old, "cookie"), cookie);
            }
            e.putString(dyKey(old, "name"), prefs.getString("douyin_name", ""));
            e.putString(dyKey(old, "login_at"), prefs.getString("douyin_login_at", ""));
            e.putString(dyKey(old, "last"), prefs.getString("douyin_last", ""));
            e.putString(dyKey(old, "last_msg"), prefs.getString("douyin_last_msg", ""));
            String list = prefs.getString(DY_LIST, "");
            java.util.List<String> cur = new java.util.ArrayList<>();
            for (String s : list.split(",")) if (!s.trim().isEmpty()) cur.add(s.trim());
            if (!cur.contains(old)) {
                cur.add(old);
                e.putString(DY_LIST, joinHandles(cur));
            }
        }
        e.apply();
    }

    private static String joinHandles(java.util.List<String> hs) {
        StringBuilder sb = new StringBuilder();
        for (String h : hs) {
            if (sb.length() > 0) sb.append(",");
            sb.append(h);
        }
        return sb.toString();
    }

    /** 登录成功：把号加到列表里，Cookie / 名字 / 登录时间各自存到自己的键上。 */
    private void saveDouyinAccount(String handle, String name, String cookie) {
        java.util.List<String> list = douyinHandles();
        if (!list.contains(handle)) list.add(handle);
        prefs.edit()
                .putString(DY_LIST, joinHandles(list))
                .putString(dyKey(handle, "cookie"), cookie)
                .putString(dyKey(handle, "name"), name == null ? "" : name)
                .putString(dyKey(handle, "login_at"), now())
                .apply();
    }

    /** 解绑一个号：清本机登录态 + 仓库账号条目，作品数据文件留着（重新登回来还在）。 */
    private void confirmDeleteDouyin(final String handle) {
        final String name = prefs.getString(dyKey(handle, "name"), "");
        new AlertDialog.Builder(this)
                .setTitle("解绑这个抖音号？")
                .setMessage((name.isEmpty() ? handle : name) + "（" + handle + "）\n\n"
                        + "只清本机的登录态和 accounts.json 里的条目；作品数据文件保留，"
                        + "以后重新登录还能接着用。")
                .setPositiveButton("解绑", (d, w) -> {
                    java.util.List<String> list = douyinHandles();
                    list.remove(handle);
                    prefs.edit()
                            .putString(DY_LIST, joinHandles(list))
                            .remove(dyKey(handle, "cookie"))
                            .remove(dyKey(handle, "name"))
                            .remove(dyKey(handle, "login_at"))
                            .remove(dyKey(handle, "last"))
                            .remove(dyKey(handle, "last_msg"))
                            .apply();
                    try {
                        DouyinSync.removeAccountEntry(store, handle);
                    } catch (Exception e) {
                        toast("账号条目没写成：" + e.getMessage());
                    }
                    toast("已解绑 " + (name.isEmpty() ? handle : name));
                    if (!token().isEmpty()) startSync();   // 把 accounts.json 的变化推回仓库
                })
                .setNegativeButton("取消", null)
                .show();
    }

    /** 逐个号只认一次号，看谁的登录态还活着（只读接口，不写数据、不推送）。 */
    private void verifyDouyinAccounts() {
        final java.util.List<String> handles = douyinHandles();
        if (handles.isEmpty()) {
            toast("先登录一个抖音号");
            return;
        }
        topStart("抖音 · 验证 " + handles.size() + " 个号的登录态…");
        new Thread(() -> {
            final StringBuilder alive = new StringBuilder();
            final StringBuilder dead = new StringBuilder();
            int aliveN = 0, deadN = 0;
            for (String h : handles) {
                final String cookie = prefs.getString(dyKey(h, "cookie"), "");
                final String who = prefs.getString(dyKey(h, "name"), h);
                if (cookie.isEmpty()) {
                    deadN++;
                    dead.append("· ").append(who).append("（").append(h).append("）没有登录态\n");
                    continue;
                }
                try {
                    alive.append("· ").append(DouyinSync.identity(cookie).label()).append("\n");
                    aliveN++;
                } catch (Exception e) {
                    deadN++;
                    String m = e.getMessage() == null ? "失效" : e.getMessage();
                    dead.append("· ").append(who).append("（").append(h).append("）")
                            .append(m).append("\n");
                }
            }
            final int an = aliveN, dn = deadN;
            uiHandler.post(() -> {
                StringBuilder msg = new StringBuilder();
                if (alive.length() > 0) msg.append("还活着：\n").append(alive);
                if (dead.length() > 0) {
                    if (msg.length() > 0) msg.append("\n");
                    msg.append("要重登：\n").append(dead);
                }
                logEvent("douyin", dn == 0, dn == 0
                        ? "✓ 抖音登录态：" + an + " 个号都在线"
                        : "✗ 抖音登录态：" + dn + " 个号要重登", msg.toString());
                new AlertDialog.Builder(this)
                        .setTitle("抖音登录态")
                        .setMessage(msg.toString())
                        .setPositiveButton("知道了", null)
                        .show();
                topDone("抖音登录态验证完成", dn == 0, null);
            });
        }).start();
    }

    /** "yyyy-MM-dd HH:mm" 到今天过了几天；解析不了返回 -1。 */
    private static long daysSince(String at) {
        try {
            java.text.SimpleDateFormat f =
                    new java.text.SimpleDateFormat("yyyy-MM-dd HH:mm", java.util.Locale.CHINA);
            java.util.Date d = f.parse(at);
            if (d == null) return -1;
            return (System.currentTimeMillis() - d.getTime()) / (24L * 3600L * 1000L);
        } catch (Exception e) {
            return -1;
        }
    }

    /**
     * 登录一个抖音号（expectHandle 非空＝重登某个号）。
     *
     * 多账号能同时在线靠这一条：进来先只清本机 Cookie（不点退出），
     * 所以已经存好的号不会被踢下线——清 Cookie 的逻辑在 DouyinLoginActivity 里。
     * 单独开 Activity 还顺手解决了「登录页里键盘唤不出来」的问题。
     */
    private void showDouyinLogin(final String expectHandle) {
        Intent i = new Intent(this, DouyinLoginActivity.class);
        i.putExtra(DouyinLoginActivity.EXTRA_EXPECT, expectHandle == null ? "" : expectHandle);
        try {
            startActivityForResult(i, REQ_DOUYIN_LOGIN);
        } catch (Exception e) {
            // 兜底：清单里漏声明 / 系统拦了，至少给个提示并记日志（不静默退到桌面）
            writeCrash(e, "startActivity(DouyinLoginActivity)");
            toast("打不开登录页：" + e.getClass().getSimpleName() + "（已记 data/hub/crash.log）");
        }
    }

    /** 登录页回来：验一下 Cookie 认不认得出抖音号，认得出就存到这个号自己的键上。 */
    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQ_DOUYIN_LOGIN || resultCode != RESULT_OK || data == null) return;
        final String cookie = data.getStringExtra(DouyinLoginActivity.EXTRA_COOKIE);
        final String expect = data.getStringExtra(DouyinLoginActivity.EXTRA_EXPECT);
        if (cookie == null || !cookie.contains("sessionid")) return;
        toast("正在验证登录态…");
        new Thread(() -> {
            try {
                DouyinClient.Identity id = DouyinSync.identity(cookie);
                saveDouyinAccount(id.handle, id.name, cookie);
                try {
                    DouyinSync.ensureAccountEntry(store, id.handle, id.name);
                } catch (Exception ignored) {
                    // accounts.json 写不进去也不影响 cookie 已存好
                }
                final boolean other = expect != null && !expect.isEmpty()
                        && !expect.equals(id.handle);
                final boolean existed = !other && douyinHandles().contains(id.handle);
                runOnUiThread(() -> {
                    if (other) {
                        toast("重登时认出来的是另一个号：" + id.label() + "，已按新号单独保存");
                    } else if (existed && (expect == null || expect.isEmpty())) {
                        toast("这是已保存过的号：" + id.label() + "，登录态已刷新；要加新号请登另一个手机号");
                    } else {
                        toast("已登录：" + id.label() + "，先同步这个号…");
                    }
                    startDouyinSync(id.handle);
                });
            } catch (Exception e) {
                final String msg = e.getMessage() == null ? e.toString() : e.getMessage();
                runOnUiThread(() -> toast("还认不到账号（" + msg + "），回登录页等 5 秒再点一次"));
            }
        }).start();
    }

    /** 同步全部已登录的抖音号；每个号用自己的 Cookie，各写各的数据文件。 */
    private void startDouyinSync() {
        startDouyinSync(null);
    }

    /** only 非空时只同步那一个号（刚登录完用）。 */
    private void startDouyinSync(final String only) {
        final java.util.List<String> all = douyinHandles();
        final java.util.List<String> targets = new java.util.ArrayList<>();
        for (String h : all) {
            if (only == null || only.equals(h)) targets.add(h);
        }
        if (targets.isEmpty()) {
            toast(only == null ? "先点「登录新账号」" : "这个号还没登录过");
            showDouyinLogin(null);
            return;
        }
        if (douyinSyncing) {
            toast("抖音正在同步…");
            return;
        }
        douyinSyncing = true;
        topStart("抖音 · 准备同步 " + targets.size() + " 个号…");
        new Thread(() -> {
            final boolean[] loginFail = { false };
            final String[] loginFailWho = { null };
            int okCount = 0, failCount = 0;
            final StringBuilder detail = new StringBuilder();
            for (String h : targets) {
                final String cookie = prefs.getString(dyKey(h, "cookie"), "");
                final String who = prefs.getString(dyKey(h, "name"), h);
                if (cookie.isEmpty()) {
                    failCount++;
                    detail.append("· ").append(h).append("：没有登录态\n");
                    continue;
                }
                try {
                    topText("抖音 · " + who + " · 认号中…");
                    DouyinSync.Result r = DouyinSync.sync(store, cookie, 30,
                            msg -> topText("抖音 · " + who + " · " + msg));
                    SharedPreferences.Editor e = prefs.edit()
                            .putString(dyKey(h, "last"), now())
                            .putString(dyKey(h, "last_msg"), r.summary())
                            // 服务端这一轮可能下发了新的 sessionid / bd_ticket_guard_*，
                            // 存回这个号自己的键上，登录态才会像浏览器一样滚动续期
                            .putString(dyKey(h, "cookie"), r.cookie.isEmpty() ? cookie : r.cookie);
                    if (!r.name.isEmpty()) e.putString(dyKey(h, "name"), r.name);
                    e.apply();
                    okCount++;
                    detail.append("· ").append(r.summary()).append("\n");
                } catch (DouyinClient.LoginException le) {
                    loginFail[0] = true;
                    loginFailWho[0] = h;
                    failCount++;
                    // 只清这个号的 cookie，别的号不受影响
                    prefs.edit().remove(dyKey(h, "cookie")).apply();
                    detail.append("· ").append(who).append("（").append(h).append("）：登录已失效\n");
                } catch (Exception ex) {
                    failCount++;
                    String m = ex.getMessage() == null ? ex.toString() : ex.getMessage();
                    detail.append("· ").append(who).append("：").append(m).append("\n");
                }
            }
            final int ok = okCount, fail = failCount;
            final String summary = "抖音 " + ok + " 个号成功 / " + fail + " 个号失败";
            logEvent("douyin", fail == 0, (fail == 0 ? "✓ " : "✗ ") + summary, detail.toString());
            uiHandler.post(() -> {
                douyinSyncing = false;
                if (token().isEmpty()) {
                    // 没填 Token：数据已经落在本机，直接刷新页面把新数字显示出来
                    if (ok > 0 && web != null) web.reload();
                    topDone("✓ " + summary + " · 已刷新", ok > 0, null);
                } else {
                    // 数据变了：接着推回 GitHub（推完会拉一遍并自动刷新页面）
                    topText(summary + "，正在推送到 GitHub…");
                    startSync();
                }
                if (fail > 0) {
                    new AlertDialog.Builder(MainActivity.this)
                            .setTitle("有 " + fail + " 个抖音号没同步成")
                            .setMessage(detail.toString())
                            .setPositiveButton(loginFail[0] ? "重登这个号" : "知道了", (d, w) -> {
                                if (loginFail[0]) showDouyinLogin(loginFailWho[0]);
                            })
                            .setNegativeButton("取消", null)
                            .show();
                }
            });
        }).start();
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
        if (repo().isEmpty() || token().isEmpty()) {
            toast("先配置 Gitee 私有仓库和令牌");
            showSettings();
            return;
        }
        syncing = true;
        topStart("☁ 准备同步…");
        final GiteeClient client = new GiteeClient(repo(), token(), branch());
        new Thread(() -> {
            try {
                // 数据中心必须是私有的：公开仓库等于把抖音数据给别人看
                org.json.JSONObject info = client.info();
                if (!info.optBoolean("private", false)) {
                    throw new java.io.IOException("仓库不是私有的：请到 Gitee 把仓库改成私有");
                }
                client.sync(store, msg -> topText("☁ " + msg));
                prefs.edit().putString("last_sync", now()).putString("last_error", "").apply();
                logEvent("sync", true, "✓ Gitee 已同步 · 已刷新页面");
                uiHandler.post(() -> {
                    syncing = false;
                    if (web != null) web.reload();
                    topDone("✓ Gitee 已同步 · 已刷新页面", true, null);
                });
            } catch (Exception e) {
                final String msg = e.getMessage() == null ? e.toString() : e.getMessage();
                prefs.edit().putString("last_error", msg).apply();
                logEvent("sync", false, "✗ 同步失败：" + msg);
                uiHandler.post(() -> {
                    syncing = false;
                    topDone("✗ 同步失败：" + msg + "（点一下收起）", false, null);
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

    // -------------------------------------------------------------- 自动更新
    private boolean updateBusy = false;
    private static final long CHECK_GAP_MS = 6L * 3600L * 1000L;   // 前台顺带补查的间隔

    /** 自动检查更新（默认开）：启动/回前台时静默查一次，有新版只弹「更新内容」，点了才下载。 */
    private boolean autoUpdate() {
        return prefs.getBoolean("auto_update", true);
    }

    private File apkDir() {
        File dir = getExternalFilesDir("apk");
        return dir != null ? dir : new File(getFilesDir(), "apk");
    }

    private int myVersionCode() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionCode;
        } catch (Exception e) {
            return 0;
        }
    }

    private String myVersionName() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "?";
        }
    }

    /** silent=true 时不打扰（启动/前台时静默查；有新版先给更新内容，点了才下载）。 */
    private void checkUpdate(boolean silent) {
        if (silent && !autoUpdate()) return;          // 关了自动检查就只在点 ⬆ 时查
        if (updateBusy) {
            if (!silent) toast("正在检查更新…");
            return;
        }
        updateBusy = true;
        final int mine = myVersionCode();
        new Thread(() -> {
            try {
                final Updater.Info info = Updater.check(Repos.UPDATE, "main", null, getPackageName());
                prefs.edit().putLong("last_update_check", System.currentTimeMillis())
                        .putString("last_check_at", now()).apply();
                runOnUiThread(() -> {
                    updateBusy = false;
                    if (info.code <= mine) {
                        if (!silent) {
                            toast("已是最新版本 v" + myVersionName());
                            logEvent("update", true, "已是最新版本 v" + myVersionName());
                        }
                        return;
                    }
                    if (silent) {
                        // 同一个版本别每次启动都弹：12 小时内提示过一次就安静
                        String key = "update_prompted_" + info.code;
                        long last = prefs.getLong(key, 0L);
                        if (System.currentTimeMillis() - last < 12L * 3600L * 1000L) return;
                        prefs.edit().putLong(key, System.currentTimeMillis()).apply();
                    }
                    logEvent("update", true, "发现新版 v" + info.name + "（当前 v" + myVersionName() + "），等你确认再下载");
                    // 不管手动还是自动查，都先给更新内容，点了才下载（不偷偷下）
                    askUpdate(info);
                });
            } catch (Exception e) {
                final String msg = e.getMessage() == null ? e.toString() : e.getMessage();
                runOnUiThread(() -> {
                    updateBusy = false;
                    if (!silent) {
                        toast("检查更新失败：" + msg);
                        logEvent("update", false, "检查更新失败：" + msg);
                    }
                });
            }
        }).start();
    }

    /**
     * 更新预览：先把「这次改了什么」摆出来，用户点「下载并安装」才真的下。
     * 内容来自 version.json 的 notes（发版时 tools\release.ps1 会把它同时写进 GitHub Release 正文）。
     */
    private void askUpdate(final Updater.Info info) {
        String head = "当前 v" + myVersionName() + " → 将升级到 v" + info.name
                + (info.size > 0 ? "（" + mb(info.size) + "）" : "");
        String notes = info.notes == null || info.notes.trim().isEmpty()
                ? "（这次没写更新说明，可以点「查看完整说明」去 Release 页面看）"
                : info.notes;

        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(20), dp(4), dp(20), 0);

        TextView t1 = label(head);
        t1.setTextSize(13);
        t1.setTextColor(Color.parseColor("#1F2430"));
        box.addView(t1);

        TextView t2 = label("更新内容");
        t2.setTextSize(12);
        t2.setTextColor(Color.parseColor("#3D6EE0"));
        t2.setPadding(0, dp(10), 0, dp(2));
        box.addView(t2);

        TextView t3 = label(notes);
        t3.setTextSize(12);
        t3.setTextColor(Color.parseColor("#5B6577"));
        t3.setTextIsSelectable(true);
        box.addView(t3);

        TextView t4 = label("下载用顶部灵动岛显示进度，不挡你操作；下完点胶囊就能装。数据都在本地和 Gitee 私有仓库，不会丢。");
        t4.setTextSize(10);
        t4.setTextColor(Color.parseColor("#8A94A6"));
        t4.setPadding(0, dp(10), 0, 0);
        box.addView(t4);

        ScrollView scroll = new ScrollView(this);
        scroll.addView(box);
        // 说明短就整段显示，太长就限高滚动，别把按钮顶出屏幕
        final int cap = (int) (getResources().getDisplayMetrics().heightPixels * 0.45);
        scroll.post(() -> {
            if (scroll.getChildCount() == 0) return;
            int ch = scroll.getChildAt(0).getHeight();
            if (ch > cap) {
                ViewGroup.LayoutParams lp = scroll.getLayoutParams();
                if (lp != null) {
                    lp.height = cap;
                    scroll.setLayoutParams(lp);
                }
            }
        });

        new AlertDialog.Builder(this)
                .setTitle("第二大脑 v" + info.name + " 有新版本")
                .setView(scroll)
                .setPositiveButton("下载并安装", (d, w) -> downloadAndInstall(info))
                .setNeutralButton("查看完整说明", (d, w) -> openReleasePage(info))
                .setNegativeButton("以后再说", null)
                .show();
    }

    private static String mb(long bytes) {
        return String.format(java.util.Locale.CHINA, "%.1f MB", bytes / 1024.0 / 1024.0);
    }

    /** 打开这次版本的 Release 页面（正文就是发版时的更新说明）。Gitee 优先。 */
    private void openReleasePage(Updater.Info info) {
        String[] names = {"Gitee（国内直连）", "GitHub（备用）"};
        String gitee = "https://gitee.com/" + Updater.GITEE + "/releases/tag/v" + info.name;
        String github = "https://github.com/" + Updater.GITHUB + "/releases/tag/v" + info.name;
        new AlertDialog.Builder(this)
                .setTitle("查看更新说明")
                .setItems(names, (d, which) -> openUrl(which == 0 ? gitee : github))
                .show();
    }

    private void downloadAndInstall(final Updater.Info info) {
        final String label = "第二大脑 v" + info.name;
        topStart("正在下载 " + label + " · 0%");
        new Thread(() -> {
            try {
                File apk = Updater.download(info, Repos.UPDATE, null, apkDir(), ratio ->
                        topText("正在下载 " + label + " · " + (int) (ratio * 100) + "%"));
                logEvent("update", true, "✓ " + label + " 下载完成（"
                        + (info.source == null ? "—" : info.source) + "），等你点安装");
                uiHandler.post(() -> topDoneSticky("✓ " + label + " 下载完成，点这里安装",
                        () -> confirmInstall(info, apk)));
            } catch (Exception e) {
                final String msg = e.getMessage() == null ? e.toString() : e.getMessage();
                logEvent("update", false, "下载更新包失败：" + msg);
                uiHandler.post(() -> topDone("✗ 下载失败：" + msg + "（点一下收起）", false, null));
            }
        }).start();
    }

    /** 下载完成用：绿点常驻，不自动收，等用户点一下去安装。 */
    private void topDoneSticky(final String text, final Runnable onTap) {
        uiHandler.post(() -> {
            if (topBar == null) return;
            if (topBarHide != null) {
                uiHandler.removeCallbacks(topBarHide);
                topBarHide = null;
            }
            topBarBar.setVisibility(View.GONE);
            topBarDot.setBackground(dotBg("#3ED17A"));
            topBarDot.setVisibility(View.VISIBLE);
            topBarText.setText(text);
            topBar.setOnClickListener(v -> {
                hideTopBar();
                if (onTap != null) onTap.run();
            });
            topBar.setVisibility(View.VISIBLE);
            topBar.animate().alpha(1f).translationY(0f).scaleX(1f).scaleY(1f)
                    .setDuration(160).start();
        });
    }

    /**
     * 下载完先核对「文件里真实的版本」，对不上就不装。
     * 这样万一哪天下载链路拿错包，手机上能一眼看出来，而不是装完还是旧版。
     */
    private void confirmInstall(final Updater.Info info, final File apk) {
        String pkg = "";
        int code = -1;
        String name = "";
        try {
            android.content.pm.PackageInfo pi = getPackageManager()
                    .getPackageArchiveInfo(apk.getAbsolutePath(), 0);
            if (pi != null) {
                pkg = pi.packageName;
                code = pi.versionCode;
                name = pi.versionName;
            }
        } catch (Exception ignored) {
        }
        long size = apk.length();
        String sha = info.sha256.isEmpty() ? "—"
                : info.sha256.substring(0, Math.min(12, info.sha256.length())) + "…";

        String body = "文件：" + apk.getName() + "（" + mb(size) + "）\n"
                + "包里实际版本：" + (code > 0 ? name + "（" + code + "）" : "读不出来") + "\n"
                + "要升到的版本：" + info.name + "（" + info.code + "）\n"
                + "来源：" + (info.source.isEmpty() ? "—" : info.source) + "\n"
                + "sha256：" + sha;
        prefs.edit().putString("last_apk",
                (code > 0 ? name + "(" + code + ")" : "?") + " · " + info.source + " · " + now()).apply();

        boolean good = code > 0 && pkg.equals(getPackageName()) && code == info.code;
        if (!good) {
            //noinspection ResultOfMethodCallIgnored
            apk.delete();
            new AlertDialog.Builder(this)
                    .setTitle("下载到的包不对，没装")
                    .setMessage(body + "\n\n包里版本和目标版本对不上（或包名不对），已经删掉这个文件，请再点一次 ⬆ 重试。")
                    .setPositiveButton("知道了", null)
                    .show();
            return;
        }
        logEvent("update", true, "更新包已下好 v" + name + "（" + code + "），等你在系统安装器点安装");
        new AlertDialog.Builder(this)
                .setTitle("确认安装 v" + name)
                .setMessage(body)
                .setPositiveButton("安装", (d, w) -> installApk(apk))
                .setNegativeButton("取消", null)
                .show();
    }

    private void installApk(File apk) {
        if (!canInstallApks()) {
            // 正常情况启动时就已经引导过了，走到这里说明用户当时点了「以后再说」
            installPermPrompted = true;
            // 记住这个包，用户去设置里开完权限回来直接接着装，不用再点一次 ⬆
            prefs.edit().putString("pending_apk", apk.getAbsolutePath()).apply();
            new AlertDialog.Builder(this)
                    .setTitle("还差一步：允许安装应用")
                    .setMessage("包已经下好了，只差系统那边允许「第二大脑」安装应用。\n"
                            + "打开开关后返回，会自动继续安装。")
                    .setPositiveButton("去打开", (d, w) -> openInstallSettings())
                    .setNegativeButton("取消", null)
                    .show();
            return;
        }
        Uri uri = Uri.parse("content://" + getPackageName() + ApkProvider.SUFFIX + "/" + apk.getName());
        Intent i = new Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, ApkProvider.MIME)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            prefs.edit().remove("pending_apk").apply();
            startActivity(i);
        } catch (Exception e) {
            toast("打不开安装器：" + e);
        }
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

        /** 手表/手机把一段话存进 notes/inbox/，下次同步推到仓库。 */
        @JavascriptInterface
        public String saveInbox(String text, String from) {
            return store.saveInbox(text, from);
        }

        @JavascriptInterface
        public String status() {
            JSONObject o = new JSONObject();
            try {
                o.put("repo", repo());
                o.put("branch", branch());
                o.put("provider", "gitee");
                o.put("tokenSet", !token().isEmpty());
                o.put("lastSync", prefs.getString("last_sync", ""));
                o.put("lastError", prefs.getString("last_error", ""));
                o.put("dirty", store.dirty().size());
                o.put("versionName", myVersionName());
                o.put("versionCode", myVersionCode());
                o.put("autoUpdate", autoUpdate());
                o.put("canInstall", canInstallApks());
                o.put("syncing", syncing);
                o.put("douyinSyncing", douyinSyncing);
                o.put("lastCheck", prefs.getString("last_check_at", ""));
                o.put("lastApk", prefs.getString("last_apk", ""));
                o.put("lastCrash", prefs.getString("last_crash", ""));
                o.put("douyinCount", douyinHandles().size());
            } catch (Exception ignored) {
            }
            return o.toString();
        }

        /** 「我的」页的同步消息记录（本机 prefs 里的 JSON 数组，最新在最前）。 */
        @JavascriptInterface
        public String events() {
            return prefs.getString(EVENT_KEY, "[]");
        }

        @JavascriptInterface
        public void clearEvents() {
            runOnUiThread(() -> new AlertDialog.Builder(MainActivity.this)
                    .setTitle("清空同步消息？")
                    .setMessage("只清这台手机上的记录，不影响仓库和别的地方。以后每次同步还会继续记。")
                    .setPositiveButton("清空", (d, w) -> {
                        prefs.edit().remove(EVENT_KEY).apply();
                        if (web != null) {
                            web.evaluateJavascript(
                                    "window.__hubEventsUpdated&&window.__hubEventsUpdated()", null);
                        }
                    })
                    .setNegativeButton("取消", null)
                    .show());
        }

        @JavascriptInterface
        public void requestSync() {
            runOnUiThread(MainActivity.this::startSync);
        }

        @JavascriptInterface
        public void openSettings() {
            runOnUiThread(MainActivity.this::showSettings);
        }

        /** 直接跳到系统的「安装未知应用」开关（「我的」页那一行用）。 */
        @JavascriptInterface
        public void openInstallSettings() {
            runOnUiThread(MainActivity.this::openInstallSettings);
        }

        @JavascriptInterface
        public void checkUpdate() {
            runOnUiThread(() -> MainActivity.this.checkUpdate(false));
        }

        @JavascriptInterface
        public String version() {
            return myVersionName() + " (" + myVersionCode() + ")";
        }

        // ---------------------------------------------------------- 功能开关
        /** 首次启动标记 + 抖音/小红书开关（默认都开）。 */
        @JavascriptInterface
        public String features() {
            JSONObject o = new JSONObject();
            try {
                // 只有「新安装」才弹首次选择；升级上来的老用户不打扰
                boolean fresh = false;
                try {
                    android.content.pm.PackageInfo pi =
                            getPackageManager().getPackageInfo(getPackageName(), 0);
                    fresh = pi.firstInstallTime == pi.lastUpdateTime;
                } catch (Exception ignored) {
                }
                o.put("onboarded", prefs.getBoolean("features.onboarded", !fresh));
                o.put("douyin", prefs.getBoolean("features.douyin", true));
                o.put("xhs", prefs.getBoolean("features.xhs", true));
            } catch (Exception ignored) {
            }
            return o.toString();
        }

        @JavascriptInterface
        public void setFeature(String key, boolean on) {
            if (!"douyin".equals(key) && !"xhs".equals(key)) return;
            prefs.edit().putBoolean("features." + key, on).apply();
        }

        @JavascriptInterface
        public void setOnboarded() {
            prefs.edit().putBoolean("features.onboarded", true).apply();
        }

        // ---------------------------------------------------------- 抖音（页面里直接管账号）
        /** 每个号的登录态给页面：[{handle,name,alive,days,loginAt,last,lastMsg}]。 */
        @JavascriptInterface
        public String douyinAccounts() {
            org.json.JSONArray arr = new org.json.JSONArray();
            for (String h : douyinHandles()) {
                org.json.JSONObject o = new org.json.JSONObject();
                try {
                    String loginAt = prefs.getString(dyKey(h, "login_at"), "");
                    o.put("handle", h);
                    o.put("name", prefs.getString(dyKey(h, "name"), ""));
                    o.put("alive", !prefs.getString(dyKey(h, "cookie"), "").isEmpty());
                    o.put("loginAt", loginAt);
                    o.put("days", daysSince(loginAt));
                    o.put("last", prefs.getString(dyKey(h, "last"), ""));
                    o.put("lastMsg", prefs.getString(dyKey(h, "last_msg"), ""));
                } catch (Exception ignored) {
                }
                arr.put(o);
            }
            return arr.toString();
        }

        /** handle 为空＝同步全部。 */
        @JavascriptInterface
        public void douyinSync(String handle) {
            final String h = handle == null ? "" : handle.trim();
            runOnUiThread(() -> startDouyinSync(h.isEmpty() ? null : h));
        }

        /** handle 为空＝登录新号。 */
        @JavascriptInterface
        public void douyinLogin(String handle) {
            final String h = handle == null ? "" : handle.trim();
            runOnUiThread(() -> showDouyinLogin(h.isEmpty() ? null : h));
        }

        @JavascriptInterface
        public void douyinRemove(String handle) {
            final String h = handle == null ? "" : handle.trim();
            if (h.isEmpty()) return;
            runOnUiThread(() -> confirmDeleteDouyin(h));
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
        // 从「安装未知应用」设置页回来：拿到权限就报一声，并把手上下好没装的包接着装上
        if (installPermPrompted && canInstallApks()) {
            installPermPrompted = false;
            prefs.edit().putBoolean("install_perm_asked", true).apply();
            toast("✓ 已允许安装应用，以后更新只需点一次「安装」");
            String pending = prefs.getString("pending_apk", "");
            if (!pending.isEmpty()) {
                File f = new File(pending);
                if (f.isFile()) {
                    installApk(f);
                } else {
                    prefs.edit().remove("pending_apk").apply();
                }
            }
        }
        long last = prefs.getLong("last_update_check", 0L);
        if (last > 0 && System.currentTimeMillis() - last > CHECK_GAP_MS) {
            checkUpdate(true);
        }
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
