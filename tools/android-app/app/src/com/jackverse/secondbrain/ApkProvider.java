package com.jackverse.secondbrain;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;

import java.io.File;
import java.io.FileNotFoundException;

/**
 * 极简 FileProvider：只把手上下载好的 APK 交给系统安装器。
 *
 * 不用 androidx 的 FileProvider —— 这个工程是纯 javac + android.jar 编的，
 * 没有任何 support/AndroidX 依赖，引了就运行期 ClassNotFound。
 *
 * authority = <包名>.fileprovider（手机、手表包名不同，天然不冲突）
 * 只允许读 getExternalFilesDir("apk") 与 filesDir/apk 下的 .apk，别的路径一律 404。
 */
public class ApkProvider extends ContentProvider {

    public static final String SUFFIX = ".fileprovider";
    public static final String MIME = "application/vnd.android.package-archive";

    @Override
    public boolean onCreate() {
        return true;
    }

    private File resolve(Uri uri) {
        String name = uri.getLastPathSegment();
        if (name == null || !name.toLowerCase(java.util.Locale.ROOT).endsWith(".apk")) return null;
        if (name.contains("..") || name.contains("/") || name.contains("\\")) return null;
        File ext = getContext().getExternalFilesDir("apk");
        File candidate = new File(ext, name);
        if (candidate.isFile()) return candidate;
        candidate = new File(new File(getContext().getFilesDir(), "apk"), name);
        return candidate.isFile() ? candidate : null;
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        File f = resolve(uri);
        if (f == null) throw new FileNotFoundException("不是已下载的 apk：" + uri);
        return ParcelFileDescriptor.open(f, ParcelFileDescriptor.MODE_READ_ONLY);
    }

    @Override
    public String getType(Uri uri) {
        return MIME;
    }

    @Override
    public Cursor query(Uri uri, String[] projection, String selection,
                        String[] selectionArgs, String sortOrder) {
        return null;
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        return null;
    }

    @Override
    public int delete(Uri uri, String selection, String[] selectionArgs) {
        return 0;
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) {
        return 0;
    }
}
