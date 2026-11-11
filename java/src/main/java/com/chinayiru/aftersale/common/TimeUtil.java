package com.chinayiru.aftersale.common;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;

public final class TimeUtil {

    public static final ZoneId ZONE = ZoneId.of("Asia/Shanghai");
    public static final ZoneOffset OFFSET = ZoneOffset.ofHours(8);

    private TimeUtil() {
    }

    public static LocalDateTime now() {
        return LocalDateTime.now(ZONE).truncatedTo(ChronoUnit.MILLIS);
    }

    public static OffsetDateTime offset(LocalDateTime value) {
        return value == null ? null : value.atOffset(OFFSET);
    }

    public static LocalDateTime local(OffsetDateTime value) {
        return value == null ? null : value.withOffsetSameInstant(OFFSET).toLocalDateTime();
    }
}
