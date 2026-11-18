package local.skillinventory;

import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.multipart.MaxUploadSizeExceededException;

final class ApiError extends RuntimeException {
    final int status;
    final String code;

    ApiError(int status, String code, String message) {
        super(message);
        this.status = status;
        this.code = code;
    }

    static ApiError invalid(String message) {
        return new ApiError(400, "invalid_input", message);
    }

    static ApiError conflict(String message) {
        return new ApiError(409, "conflict", message);
    }

    static ApiError missing(String message) {
        return new ApiError(404, "not_found", message);
    }
}

@RestControllerAdvice
class ApiErrors {
    @ExceptionHandler(ApiError.class)
    ResponseEntity<Map<String, String>> apiError(ApiError error) {
        return ResponseEntity.status(error.status).body(Map.of("code", error.code, "message", error.getMessage()));
    }

    @ExceptionHandler(MaxUploadSizeExceededException.class)
    ResponseEntity<Map<String, String>> uploadLimit() {
        return ResponseEntity.status(413).body(Map.of("code", "upload_limit", "message", "ZIP 文件超过上传限制"));
    }
}
