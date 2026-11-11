package com.chinayiru.aftersale.common;

import jakarta.validation.ConstraintViolationException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.FieldError;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import java.util.stream.Collectors;

@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(ApiException.class)
    public ResponseEntity<ErrorResponse> handleApi(ApiException ex) {
        ErrorCode code = ex.getCode();
        ErrorResponse body = new ErrorResponse(code.name(), ex.getMessage(), TraceFilter.currentTraceId(), code.retryable());
        ResponseEntity.BodyBuilder builder = ResponseEntity.status(code.httpStatus());
        if (code.retryable()) {
            int retryAfter = ex.getRetryAfterSeconds() == null ? 1 : ex.getRetryAfterSeconds();
            builder.header(HttpHeaders.RETRY_AFTER, String.valueOf(retryAfter));
        }
        return builder.body(body);
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ErrorResponse> handleValidation(MethodArgumentNotValidException ex) {
        String message = ex.getBindingResult().getFieldErrors().stream()
                .map(this::describe)
                .collect(Collectors.joining("；"));
        if (message.isBlank()) {
            message = "请求参数不合法";
        }
        return invalid(message);
    }

    private String describe(FieldError error) {
        return error.getField() + " " + (error.getDefaultMessage() == null ? "不合法" : error.getDefaultMessage());
    }

    @ExceptionHandler({
            ConstraintViolationException.class,
            HttpMessageNotReadableException.class,
            MissingServletRequestParameterException.class,
            MethodArgumentTypeMismatchException.class,
            HttpRequestMethodNotSupportedException.class,
            IllegalArgumentException.class
    })
    public ResponseEntity<ErrorResponse> handleBadRequest(Exception ex) {
        return invalid("请求参数不合法");
    }

    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<ErrorResponse> handleNoResource(NoResourceFoundException ex) {
        return respond(ErrorCode.TICKET_NOT_FOUND, "资源不存在");
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorResponse> handleUnexpected(Exception ex) {
        log.error("unhandled exception traceId={}", TraceFilter.currentTraceId(), ex);
        return respond(ErrorCode.PERSISTENCE_FAILED, "服务内部错误，请稍后重试");
    }

    private ResponseEntity<ErrorResponse> invalid(String message) {
        return respond(ErrorCode.INVALID_ARGS, message);
    }

    private ResponseEntity<ErrorResponse> respond(ErrorCode code, String message) {
        return ResponseEntity.status(code.httpStatus())
                .body(new ErrorResponse(code.name(), message, TraceFilter.currentTraceId(), code.retryable()));
    }
}
