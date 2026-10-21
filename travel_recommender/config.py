"""API 키 / 설정 로딩. 키 값은 절대 출력하지 않는다."""

import os
from typing import Dict, List

from dotenv import load_dotenv

REQUIRED_KEYS = ("GEMINI_API_KEY", "KAKAO_REST_API_KEY")
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"


def load_keys() -> Dict[str, str]:
    """환경변수(우선) 또는 .env 에서 키를 읽는다. 없으면 빈 문자열."""
    load_dotenv(override=False)
    return {name: os.environ.get(name, "").strip() for name in REQUIRED_KEYS}


def missing_keys(keys: Dict[str, str]) -> List[str]:
    return [name for name in REQUIRED_KEYS if not keys.get(name)]


def gemini_model() -> str:
    return os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL


MISSING_KEY_GUIDE = """[오류] 필요한 API 키가 설정되지 않았습니다: {names}

설정 방법 (둘 중 하나):
  1) .env 파일: cp .env.example .env 후 값을 채우세요.
  2) 터미널 환경변수:
       export GEMINI_API_KEY=...
       export KAKAO_REST_API_KEY=...

자세한 내용은 README.md 의 '키 설정' 항목을 참고하세요."""
