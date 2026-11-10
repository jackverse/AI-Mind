package com.jackverse.secondbrain;

/**
 * 仓库地址解析：设置里用户可能贴的是任意一种形状，统一收成 owner/repo。
 *
 * 认得的写法（大小写都不计较）：
 *   owner/repo
 *   https://github.com/owner/repo
 *   http://www.github.com/owner/repo/
 *   https://github.com/owner/repo.git
 *   https://github.com/owner/repo/tree/main/notes   （多余的路径丢掉）
 *   https://api.github.com/repos/owner/repo
 *   git@github.com:owner/repo.git
 *
 * 解析不出来返回空串，调用方保留原值并提示。
 */
public final class Repos {

    /** 默认「数据仓库」：只是占位，第一次用请在 ⚙ 里换成自己的 notes/data 仓库。 */
    public static final String DEFAULT = "jackverse/AI-Mind";

    /** 自动更新固定走公开仓库，跟用户自己的数据仓库分开。 */
    public static final String UPDATE = "jackverse/AI-Mind";

    private Repos() {
    }

    /** 收到 owner/repo；认不出返回 ""。 */
    public static String normalize(String input) {
        if (input == null) return "";
        String s = input.trim();
        if (s.isEmpty()) return "";

        s = s.replaceAll("^[A-Za-z][A-Za-z0-9+.-]*://", "");   // https://
        s = s.replaceAll("^[^@/]*@", "");                        // git@
        s = s.replace(':', '/');                                 // git@github.com:o/r → github.com/o/r
        s = s.replace('\\', '/');
        s = s.replaceAll("[?#].*$", "");                         // ?ref= / #readme
        s = s.replaceAll("^(?i)(www\\.)?(api\\.)?github\\.com/+", "");   // 主机
        s = s.replaceAll("^(?i)repos/+", "");                    // api.github.com/repos/o/r
        s = s.replaceAll("(?i)\\.git$", "");
        s = s.replaceAll("/+$", "");

        String[] parts = s.split("/+");
        if (parts.length < 2) return "";
        String owner = parts[0].trim();
        String name = parts[1].trim();
        if (!isSlug(owner) || !isSlug(name)) return "";
        return owner + "/" + name;
    }

    private static boolean isSlug(String s) {
        return s.matches("[A-Za-z0-9._-]+");
    }

    /** 展示用完整地址。 */
    public static String webUrl(String repo) {
        String r = normalize(repo);
        return r.isEmpty() ? "" : "https://github.com/" + r;
    }
}
