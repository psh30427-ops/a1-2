"""Gemini REST 호출 (requests 사용, 키는 x-goog-api-key 헤더로만 전송)."""

import json
import re
from typing import Dict, List, Optional

import requests

from .errors import ApiError, safe_exception_name

GEMINI_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
SERVICE = "Gemini"
TIMEOUT = 60

RECOMMEND_PROMPT = """너는 경기도 남양주시 여행 전문가야.
여행 날짜: {date}

남양주시 안의 읍/면/동 중 이 날짜에 하루 여행하기 좋은 곳 하나를 추천해줘.

중요: 너는 실시간 날씨 예보를 알 수 없다. weather 에는 실시간 예보가 아니라
그 날짜(계절)의 남양주 지역 일반적인 기후 경향을 적고, 문장 안에 "계절 경향"임을 밝혀줘.

아래 JSON 하나만 출력해. 다른 설명은 쓰지 마.
{{
  "recommended_city": "남양주시 OO읍/면/동",
  "weather": "계절 경향 기준 날씨 설명 (실시간 예보 아님)",
  "events": ["행사 또는 즐길거리 1", "최대 3개"],
  "reason": "추천 이유 2~4문장"
}}

규칙:
- recommended_city 는 반드시 "남양주시"로 시작하고 뒤에 읍/면/동 이름 하나를 붙인다.
- events 는 1~3개의 문자열 리스트. 확실하지 않은 축제/행사는 "(예정 여부 확인 필요)"를 붙인다.
- reason 은 2~4문장.
"""

# 재시도(2번째 시도) 때 추천 프롬프트 뒤에 덧붙이는 문구
RETRY_NOTE = """
직전 응답이 형식에 맞지 않았다. 설명 없이 JSON 객체 하나만 출력하고
필수 키 4개(recommended_city, weather, events, reason)를 모두 포함하라.
"""

REPORT_PROMPT = """아래 데이터만 사용해서 한국어 마크다운 여행 리포트를 작성해줘.
데이터에 없는 맛집이나 사실을 지어내지 마.

여행 날짜: {date}
추천 데이터(JSON):
{recommendation}

맛집 데이터(JSON, 카카오 검색 정확도 순, 평점 아님):
{restaurants}

리포트 구성: 아래 ## 제목을 이 순서대로, 글자 그대로만 쓴다. 제목 뒤에 설명을 붙이지 마.
1. ## 추천 지역
   지역 이름과 추천 이유.
2. ## 날씨
   실시간 예보가 아닌 계절 경향임을 명시.
3. ## 행사·즐길거리
4. ## 맛집
   이름, 분류, 주소, 링크. "### 식사"와 "### 카페·디저트" 소제목으로 나눈다
   (분류에 카페/디저트/제과/베이커리 등이 들어가면 카페·디저트). 맛집 데이터가 비어 있으면 "데이터 없음"이라고만 쓴다.
5. ## 하루 일정
   오전 / 오후 / 저녁으로 나눈다 (맛집이 있으면 일정에 활용).
   점심·저녁은 식사 장소로만 잡고, 카페·디저트는 식사 장소로 쓰지 말고 오후 휴식 시간에만 넣는다.

마크다운 본문만 출력해.
"""


def call_gemini(prompt: str, api_key: str, model: str, json_mode: bool = False) -> str:
    """generateContent 호출 후 텍스트를 반환. 실패 시 ApiError (상태 코드만 포함)."""
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    if json_mode:
        body["generationConfig"] = {"responseMimeType": "application/json"}
    try:
        resp = requests.post(
            GEMINI_URL_TEMPLATE.format(model=model),
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=body,
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ApiError(SERVICE, kind=safe_exception_name(exc))
    if resp.status_code != 200:
        raise ApiError(SERVICE, status=resp.status_code)
    try:
        data = resp.json()
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts)
    except (ValueError, KeyError, IndexError, TypeError):
        raise ApiError(SERVICE, kind="응답에 텍스트 없음")
    if not text.strip():
        raise ApiError(SERVICE, kind="응답에 텍스트 없음")
    return text


_FENCE_RE = re.compile(r"```[a-zA-Z]*\s*\n?(.*?)```", re.DOTALL)


def strip_code_fence(text: str) -> str:
    """```json ... ``` 같은 코드블록이 있으면 안쪽만 꺼낸다."""
    match = _FENCE_RE.search(text)
    return (match.group(1) if match else text).strip()


class RecommendationError(ValueError):
    pass


def parse_recommendation(text: str) -> Dict:
    """JSON 파싱 + 스키마 검증. 실패 시 RecommendationError."""
    cleaned = strip_code_fence(text)
    try:
        data = json.loads(cleaned)
    except ValueError:
        # 앞뒤에 설명 문장이 붙은 경우 첫 { ~ 마지막 } 구간만 다시 시도
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise RecommendationError("JSON 파싱 실패")
        try:
            data = json.loads(cleaned[start:end + 1])
        except ValueError:
            raise RecommendationError("JSON 파싱 실패")
    if not isinstance(data, dict):
        raise RecommendationError("JSON 객체가 아님")

    city = data.get("recommended_city")
    if not isinstance(city, str) or not city.strip().startswith("남양주시"):
        raise RecommendationError("recommended_city 가 '남양주시'로 시작하지 않음")
    weather = data.get("weather")
    if not isinstance(weather, str) or not weather.strip():
        raise RecommendationError("weather 누락")
    events = data.get("events")
    if (not isinstance(events, list) or not 1 <= len(events) <= 3
            or not all(isinstance(e, str) and e.strip() for e in events)):
        raise RecommendationError("events 는 1~3개 문자열 리스트여야 함")
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise RecommendationError("reason 누락")

    return {
        "recommended_city": city.strip(),
        "weather": weather.strip(),
        "events": [e.strip() for e in events],
        "reason": reason.strip(),
    }


def get_recommendation(date_str: str, api_key: str, model: str,
                       errors: List[Dict], log=print) -> Optional[Dict]:
    """추천 요청. 파싱/검증 실패 시 1회 재시도. 최종 실패 시 None (errors 에 기록)."""
    base_prompt = RECOMMEND_PROMPT.format(date=date_str)
    for attempt in (1, 2):
        prompt = base_prompt if attempt == 1 else base_prompt + RETRY_NOTE
        log("[Gemini] 지역 추천 요청 (시도 {}/2, 모델 {})".format(attempt, model))
        try:
            text = call_gemini(prompt, api_key, model, json_mode=True)
        except ApiError as exc:
            errors.append({"stage": "gemini_recommend", "message": str(exc)})
            log("[Gemini] 요청 실패: {}".format(exc))
            return None
        try:
            rec = parse_recommendation(text)
        except RecommendationError as exc:
            errors.append({"stage": "gemini_recommend",
                           "message": "시도 {}: {}".format(attempt, exc)})
            log("[Gemini] 응답 검증 실패: {}".format(exc))
            continue
        log("[Gemini] 추천 지역: {}".format(rec["recommended_city"]))
        return rec
    return None


def write_report(date_str: str, recommendation: Dict, restaurants: List[Dict],
                 api_key: str, model: str) -> str:
    """최종 마크다운 리포트 생성. 실패 시 ApiError."""
    prompt = REPORT_PROMPT.format(
        date=date_str,
        recommendation=json.dumps(recommendation, ensure_ascii=False, indent=2),
        restaurants=json.dumps(restaurants, ensure_ascii=False, indent=2),
    )
    text = call_gemini(prompt, api_key, model)
    match = re.fullmatch(r"\s*```(?:markdown|md)?\s*\n(.*)```\s*", text, re.DOTALL)
    return (match.group(1) if match else text).strip() + "\n"
