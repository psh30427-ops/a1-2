"""외부 API 오류 표현.

오류 메시지에는 서비스 이름과 HTTP 상태 코드(또는 예외 종류)만 남긴다.
응답 본문, 요청 URL, 헤더(키 포함)는 절대 담지 않는다.
"""

from typing import Optional


class ApiError(Exception):
    def __init__(self, service: str, status: Optional[int] = None, kind: Optional[str] = None):
        self.service = service
        self.status = status
        self.kind = kind
        if status is not None:
            detail = "HTTP {}".format(status)
        else:
            detail = kind or "알 수 없는 오류"
        super().__init__("{} {}".format(service, detail))


def safe_exception_name(exc: BaseException) -> str:
    """예외 메시지(URL 등이 섞일 수 있음) 대신 예외 클래스 이름만 돌려준다."""
    return type(exc).__name__
