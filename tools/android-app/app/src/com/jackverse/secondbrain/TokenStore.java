package com.jackverse.secondbrain;

import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * 令牌加密存储：Android Keystore 里的 AES/GCM 密钥，密文（IV + ciphertext）Base64 后进 SharedPreferences。
 * 换手机解不开（密钥不出安全硬件），这是故意的；重新填一次即可。
 */
public final class TokenStore {

    private static final String ALIAS = "sb_token_key";
    private static final String TRANSFORM = "AES/GCM/NoPadding";

    private final SharedPreferences prefs;

    public TokenStore(SharedPreferences prefs) {
        this.prefs = prefs;
    }

    private SecretKey key() throws Exception {
        KeyStore ks = KeyStore.getInstance("AndroidKeyStore");
        ks.load(null);
        if (ks.containsAlias(ALIAS)) return (SecretKey) ks.getKey(ALIAS, null);
        KeyGenerator kg = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        kg.init(new KeyGenParameterSpec.Builder(ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build());
        return kg.generateKey();
    }

    /** 读不到/解不开都返回空串，调用方按「没配置」处理。 */
    public String get(String name) {
        String raw = prefs.getString(name, "");
        if (raw == null || raw.isEmpty()) return "";
        try {
            byte[] all = Base64.decode(raw, Base64.DEFAULT);
            byte[] iv = new byte[12];
            byte[] data = new byte[all.length - 12];
            System.arraycopy(all, 0, iv, 0, 12);
            System.arraycopy(all, 12, data, 0, data.length);
            Cipher c = Cipher.getInstance(TRANSFORM);
            c.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, iv));
            return new String(c.doFinal(data), StandardCharsets.UTF_8);
        } catch (Exception e) {
            return "";
        }
    }

    public boolean has(String name) {
        return !get(name).isEmpty();
    }

    public void put(String name, String value) {
        if (value == null || value.trim().isEmpty()) {
            prefs.edit().remove(name).apply();
            return;
        }
        try {
            Cipher c = Cipher.getInstance(TRANSFORM);
            c.init(Cipher.ENCRYPT_MODE, key());
            byte[] iv = c.getIV();
            byte[] data = c.doFinal(value.trim().getBytes(StandardCharsets.UTF_8));
            byte[] all = new byte[iv.length + data.length];
            System.arraycopy(iv, 0, all, 0, iv.length);
            System.arraycopy(data, 0, all, iv.length, data.length);
            prefs.edit().putString(name, Base64.encodeToString(all, Base64.NO_WRAP)).apply();
        } catch (Exception ignored) {
        }
    }
}
