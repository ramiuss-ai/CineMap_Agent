"""소스별 API 오류. UI에서 상황별 안내를 나누기 위해 구분한다."""


class SourceError(Exception):
    """외부 API 호출 실패의 공통 부모."""


class AuthError(SourceError):
    """API 키가 없거나 잘못됨 (401/403)."""


class RateLimitError(SourceError):
    """호출 한도 초과 (429, 402). 재시도 대기 시간을 담을 수 있다."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class UpstreamError(SourceError):
    """그 외 HTTP 오류, 타임아웃, 잘못된 응답."""
