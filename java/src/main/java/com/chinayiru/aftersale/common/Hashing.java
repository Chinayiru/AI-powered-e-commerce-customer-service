package com.chinayiru.aftersale.common;

import java.util.Locale;

public final class Hashing {

    private Hashing() {
    }

    public static String sha256Hex(String value) {
        return sha256Hex(value.getBytes(java.nio.charset.StandardCharsets.UTF_8));
    }

    public static String sha256Hex(byte[] value) {
        try {
            java.security.MessageDigest digest = java.security.MessageDigest.getInstance("SHA-256");
            return java.util.HexFormat.of().formatHex(digest.digest(value));
        } catch (java.security.NoSuchAlgorithmException ex) {
            throw new IllegalStateException(ex);
        }
    }

    public static String shortHash(String value) {
        String hash = sha256Hex(value);
        return hash.substring(0, Math.min(16, hash.length())).toLowerCase(Locale.ROOT);
    }
}
