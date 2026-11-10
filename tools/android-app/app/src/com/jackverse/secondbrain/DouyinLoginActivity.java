package com.jackverse.secondbrain;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.WebSettings;
import android.webkit.WebStorage;
import android.webkit.WebView;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

/**
 * 抖音登录页（独立 Activity，不再塞在对话框里）。
 *
 * 为什么单独开一个 Activity：
 *  - 对话框窗口拦不住软键盘：WebView 里的输入框点了没反应，手机号/验证码根本敲不进去；
 *    换成 Activity + windowSoftInputMode=adjustResize 后键盘正常弹出，页面也会跟着缩。
 *  - 全屏能给登录页足够高度，扫码 / 输入都舒服。
 *
 * 拿登录态的两条路：
 *  1) 扫码（最省事）：页面显示二维码，用抖音 App 扫（先在 App 里切到要登的那个号）
 *  2) 粘贴 Cookie：从别处复制一串带 sessionid 的 Cookie 过来
 *
 * 进来先只清本机 Cookie / WebStorage（不点退出，所以别的号不会被踢下线），
 * 读到的 Cookie 通过 setResult 交回 MainActivity 验证并存到该号自己的键上。
 */
public class DouyinLoginActivity extends Activity {

    public static final String EXTRA_EXPECT = "expect_handle";
    public static final String EXTRA_COOKIE = "cookie";

    /**
     * 抖音创作者中心是桌面版页面：整页 1200 CSS px 宽，登录框在右边（x≈855），
     * 手机视口只有 ~412 px，不横滚就只能看到左边那张大图 —— 用户会以为「没有输入框」。
     * 页面加载完自动横滚到登录框，另外留个按钮随时能再对一次位。
     */
    private static final String JS_FOCUS_LOGIN =
            "(function(){try{"
                    + "var el=document.querySelector('input[type=tel]')||document.querySelector('input');"
                    + "var x=0;"
                    + "if(el){var r=el.getBoundingClientRect();x=window.scrollX+r.left-70;}"
                    + "if(x<=1){x=document.documentElement.scrollWidth-window.innerWidth;}"
                    + "window.scrollTo(Math.max(0,x),0);"
                    + "}catch(e){}})()";

    private WebView web;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private String expectHandle = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // 键盘要能顶起页面，而不是把输入框盖住
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        String extra = getIntent().getStringExtra(EXTRA_EXPECT);
        expectHandle = extra == null ? "" : extra;

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.WHITE);

        TextView title = new TextView(this);
        title.setText(expectHandle.isEmpty() ? "登录抖音（推荐扫码）" : "重新登录 " + expectHandle);
        title.setTextSize(16);
        title.setTextColor(Color.parseColor("#1F2430"));
        title.setGravity(Gravity.CENTER_VERTICAL);
        title.setPadding(dp(16), dp(14), dp(8), dp(2));
        title.setLayoutParams(new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        LinearLayout titleRow = new LinearLayout(this);
        titleRow.setOrientation(LinearLayout.HORIZONTAL);
        titleRow.setGravity(Gravity.CENTER_VERTICAL);
        titleRow.addView(title);
        Button find = new Button(this);
        find.setText("定位登录框");
        find.setAllCaps(false);
        find.setTextSize(11);
        find.setMinHeight(0);
        find.setMinimumHeight(0);
        find.setPadding(dp(6), dp(4), dp(6), dp(4));
        find.setOnClickListener(v -> {
            if (web != null) web.evaluateJavascript(JS_FOCUS_LOGIN, null);
        });
        titleRow.addView(find, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(titleRow);

        TextView hint = new TextView(this);
        hint.setText("本机怎么扫码：点「截图二维码」→ 打开抖音 App → 扫一扫 → 相册 → 选刚存的那张"
                + "（官方支持的路径，不算异常登录）。二维码 1～2 分钟就失效，动作快点。\n"
                + "页面已清干净，登新号不会把别的号挤下线。");
        hint.setTextSize(11);
        hint.setTextColor(Color.parseColor("#8A94A6"));
        hint.setPadding(dp(16), 0, dp(16), dp(8));
        root.addView(hint);

        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setPadding(dp(10), 0, dp(10), dp(6));

        Button paste = smallBtn("粘贴 Cookie");
        paste.setOnClickListener(v -> pasteCookie());
        Button shot = smallBtn("截图二维码");
        shot.setOnClickListener(v -> shotForGallery());
        Button read = smallBtn("我已登录，读取");
        read.setOnClickListener(v -> readCookie());
        Button cancel = smallBtn("取消");
        cancel.setOnClickListener(v -> finish());

        bar.addView(cancel, weight1());
        bar.addView(shot, weight1());
        bar.addView(paste, weight1());
        bar.addView(read, weight1());
        root.addView(bar);

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setUserAgentString(DouyinClient.UA);          // 与电脑端同一个 UA（桌面版有扫码）
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setSupportZoom(true);
        s.setBuiltInZoomControls(true);
        s.setDisplayZoomControls(false);
        web.setBackgroundColor(Color.WHITE);
        web.setFocusable(true);
        web.requestFocus();
        web.setWebViewClient(new android.webkit.WebViewClient() {
            @Override
            public void onPageFinished(WebView v, String url) {
                // 页面是 SPA：登录框要等 JS 渲染完才在右边，隔两次各对一次位
                v.postDelayed(() -> v.evaluateJavascript(JS_FOCUS_LOGIN, null), 1200);
                v.postDelayed(() -> v.evaluateJavascript(JS_FOCUS_LOGIN, null), 4000);
            }
        });
        root.addView(web, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        setContentView(root);
        clearAndLoad();
    }

    /** 只清本机登录页的 Cookie 与 WebStorage，不调退出接口。 */
    private void clearAndLoad() {
        final CookieManager cm = CookieManager.getInstance();
        cm.setAcceptCookie(true);
        try {
            WebStorage.getInstance().deleteAllData();
        } catch (Exception ignored) {
        }
        final boolean[] loaded = { false };
        final Runnable load = () -> {
            if (loaded[0]) return;
            loaded[0] = true;
            cm.flush();
            if (web != null) web.loadUrl(DouyinClient.BASE + "/creator-micro/home");
        };
        cm.removeAllCookies(done -> ui.post(load));
        // 个别 ROM 不回调 cookie 回调，兜个底
        ui.postDelayed(load, 900);
    }

    /**
     * 把当前登录页截一张存进相册。
     *
     * 手机自己在网页上登录抖音时，扫码这一关很别扭：码显示在手机上，没法用这台手机的相机
     * 去扫自己的屏幕。抖音 App 的「扫一扫」支持从相册选图 —— 截图再选图就是官方路径，
     * 不需要任何自动化/模拟点击，所以不会触发风控。
     */
    private void shotForGallery() {
        if (web == null) return;
        if (android.os.Build.VERSION.SDK_INT < 29) {
            toast("系统版本较老：用三指下滑或电源+音量键截屏，再去抖音「扫一扫 → 相册」选图");
            return;
        }
        final android.graphics.Bitmap bmp = android.graphics.Bitmap.createBitmap(
                Math.max(1, web.getWidth()), Math.max(1, web.getHeight()),
                android.graphics.Bitmap.Config.ARGB_8888);
        try {
            android.view.PixelCopy.request(getWindow(), bmp, result -> {
                if (result == android.view.PixelCopy.SUCCESS) saveShot(bmp);
                else toast("截图失败（" + result + "），用三指下滑截屏代替");
            }, ui);
        } catch (Exception e) {
            toast("截图失败：" + e.getMessage());
        }
    }

    private void saveShot(android.graphics.Bitmap bmp) {
        try {
            String name = "douyin-qr-"
                    + new java.text.SimpleDateFormat("MMdd-HHmmss", java.util.Locale.CHINA)
                    .format(new java.util.Date()) + ".png";
            android.content.ContentValues v = new android.content.ContentValues();
            v.put(android.provider.MediaStore.Images.Media.DISPLAY_NAME, name);
            v.put(android.provider.MediaStore.Images.Media.MIME_TYPE, "image/png");
            v.put(android.provider.MediaStore.Images.Media.RELATIVE_PATH,
                    android.os.Environment.DIRECTORY_PICTURES + "/第二大脑");
            android.net.Uri uri = getContentResolver().insert(
                    android.provider.MediaStore.Images.Media.EXTERNAL_CONTENT_URI, v);
            if (uri == null) {
                toast("存相册失败（没拿到 uri）");
                return;
            }
            try (java.io.OutputStream os = getContentResolver().openOutputStream(uri)) {
                bmp.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, os);
            }
            toast("已存到相册 Pictures/第二大脑\n现在打开抖音 → 扫一扫 → 相册 → 选这张");
        } catch (Exception e) {
            toast("存相册失败：" + e.getMessage());
        }
    }

    private void readCookie() {
        CookieManager.getInstance().flush();
        String cookie = CookieManager.getInstance().getCookie(DouyinClient.BASE);
        if (cookie == null || !cookie.contains("sessionid")) {
            toast("还没登录成功（没看到 sessionid）：等页面加载完，或改用扫码");
            return;
        }
        finishWithCookie(cookie);
    }

    /** 从剪贴板拿一串 Cookie（含 sessionid= 就行），方便从别的浏览器 / 电脑搬过来。 */
    private void pasteCookie() {
        ClipboardManager cb = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        ClipData clip = cb == null ? null : cb.getPrimaryClip();
        String text = null;
        if (clip != null && clip.getItemCount() > 0) {
            CharSequence cs = clip.getItemAt(0).coerceToText(this);
            text = cs == null ? null : cs.toString();
        }
        if (TextUtils.isEmpty(text) || !text.contains("sessionid")) {
            toast("剪贴板里没有带 sessionid 的 Cookie");
            return;
        }
        finishWithCookie(text.trim());
    }

    private void finishWithCookie(String cookie) {
        Intent out = new Intent();
        out.putExtra(EXTRA_COOKIE, cookie);
        out.putExtra(EXTRA_EXPECT, expectHandle);
        setResult(RESULT_OK, out);
        finish();
    }

    private Button smallBtn(String text) {
        Button b = new Button(this);
        b.setText(text);
        b.setAllCaps(false);
        b.setTextSize(12);
        b.setMinHeight(0);
        b.setMinimumHeight(0);
        b.setPadding(dp(4), dp(6), dp(4), dp(6));
        return b;
    }

    private LinearLayout.LayoutParams weight1() {
        return new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
    }

    private int dp(int v) {
        return Math.round(getResources().getDisplayMetrics().density * v);
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }

    @Override
    public void onBackPressed() {
        setResult(RESULT_CANCELED);
        finish();
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.stopLoading();
            web.setVisibility(View.GONE);
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
