"""카카오 로컬 API 키워드 검색 (음식점 카테고리 FD6)."""

import re
from typing import Dict, List, Optional

import requests

from .errors import ApiError, safe_exception_name

KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
SERVICE = "카카오 로컬"
TIMEOUT = 15

# 명시적으로 확인한 별칭만 허용한다. 부분 일치나 유사도 매칭은 하지 않는다.
PLACE_ALIASES = {"다산유적지": "정약용유적지"}


def area_from_city(recommended_city: str) -> str:
    """'남양주시 화도읍' -> '화도읍'. 접두어만 남으면 빈 문자열."""
    return recommended_city.replace("남양주시", "", 1).strip()


def build_query(recommended_city: str) -> str:
    area = area_from_city(recommended_city)
    return "남양주 {} 맛집".format(area) if area else "남양주 맛집"


def search_restaurants(query: str, api_key: str, size: int = 15, category: Optional[str] = "FD6") -> List[Dict]:
    """카카오 키워드 검색. category가 없으면 카테고리 파라미터를 생략한다."""
    params = {"query": query, "size": size}
    if category:
        params["category_group_code"] = category
    try:
        resp = requests.get(
            KAKAO_KEYWORD_URL,
            headers={"Authorization": "KakaoAK {}".format(api_key)},
            params=params,
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ApiError(SERVICE, kind=safe_exception_name(exc))
    if resp.status_code != 200:
        # 응답 본문은 저장/출력하지 않는다.
        raise ApiError(SERVICE, status=resp.status_code)
    try:
        documents = resp.json().get("documents", [])
    except (ValueError, AttributeError):
        raise ApiError(SERVICE, kind="응답 JSON 파싱 실패")
    return documents if isinstance(documents, list) else []


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def normalize(doc: Dict) -> Dict:
    return {
        "name": doc.get("place_name", ""),
        "address": doc.get("address_name") or doc.get("road_address_name", ""),
        "category": doc.get("category_name", ""),
        "url": doc.get("place_url", ""),
        "lat": _to_float(doc.get("y")),
        "lng": _to_float(doc.get("x")),
    }


def _food_types(category: str):
    """'음식점 > 한식 > 육류,고기' -> ('한식', '육류,고기')."""
    parts = [p.strip() for p in category.split(">") if p.strip()]
    if parts and parts[0] == "음식점":
        parts = parts[1:]
    broad = parts[0] if parts else category
    detail = parts[-1] if parts else category
    return broad, detail


CAFE_KEYWORDS = ("카페", "커피", "디저트", "제과", "베이커리", "간식", "아이스크림", "떡,한과")


def is_cafe(category: str) -> bool:
    """카페·디저트류(식사 장소로 부적절)인지 카테고리 문자열로 판단."""
    return any(k in category for k in CAFE_KEYWORDS)


def pick_diverse(places: List[Dict], limit: int = 5) -> List[Dict]:
    """음식 종류가 겹치지 않게 최대 limit 개 선택 (검색 정확도 순서 유지).

    1차: 대분류(한식/중식/일식...)가 서로 다른 곳 우선
    2차: 부족하면 세부 분류(냉면/국수/육류...)가 아직 없는 곳으로 채움
    같은 세부 분류는 두 번 고르지 않는다.
    """
    chosen: List[Dict] = []
    seen_broad = set()
    seen_detail = set()
    for place in places:
        broad, detail = _food_types(place.get("category", ""))
        if broad not in seen_broad and detail not in seen_detail:
            chosen.append(place)
            seen_broad.add(broad)
            seen_detail.add(detail)
            if len(chosen) >= limit:
                return chosen
    for place in places:
        if place in chosen:
            continue
        _, detail = _food_types(place.get("category", ""))
        if detail not in seen_detail:
            chosen.append(place)
            seen_detail.add(detail)
            if len(chosen) >= limit:
                break
    return chosen


def find_restaurants(recommended_city: str, api_key: str, errors: List[Dict], log=print) -> List[Dict]:
    """검색 → 정규화 → 다양성 선택. 실패/0건이어도 예외 없이 [] 반환하고 errors 에 기록."""
    query = build_query(recommended_city)
    log("[카카오] 맛집 검색: {}".format(query))
    try:
        docs = search_restaurants(query, api_key)
    except ApiError as exc:
        errors.append({"stage": "kakao", "message": str(exc)})
        log("[카카오] 검색 실패: {} (맛집 없이 계속 진행)".format(exc))
        return []
    if not docs:
        errors.append({"stage": "kakao", "message": "검색 결과 0건 (query: {})".format(query)})
        log("[카카오] 검색 결과 0건 (맛집 없이 계속 진행)")
        return []
    picked = pick_diverse([normalize(d) for d in docs
                           if valid_document(d, recommended_city, errors, "restaurant")])
    log("[카카오] {}건 중 {}곳 선택".format(len(docs), len(picked)))
    return picked


def valid_document(doc: Dict, city: str, errors: List[Dict], stage: str) -> bool:
    """주소 토큰의 시·읍면동을 정확히 비교한다. 확인 불가는 제외한다."""
    reason = None
    if not isinstance(doc, dict) or not str(doc.get("place_name") or "").strip():
        reason = "장소 이름 확인 불가"
    else:
        addresses = [doc.get(k) for k in ("address_name", "road_address_name") if doc.get(k)]
        area = area_from_city(city)
        if not addresses:
            reason = "주소 확인 불가"
        elif not re.fullmatch(r"남양주시 [가-힣]+[읍면동]", city):
            reason = "선택 지역 확인 불가"
        else:
            # 지번 주소를 우선한다. 동이 생략된 도로명 주소는 검증 근거가 아니다.
            tokens = str(addresses[0]).split()
            if "남양주시" not in tokens:
                reason = "남양주시 밖이거나 시 주소 확인 불가"
            else:
                index = tokens.index("남양주시")
                if len(tokens) <= index + 1 or tokens[index + 1] != area:
                    reason = "선택한 읍·면·동 밖이거나 읍·면·동 확인 불가"
    if reason:
        errors.append({"stage": stage, "place": doc.get("place_name", "") if isinstance(doc, dict) else "",
                       "message": reason})
        return False
    return True


def verify_recommendation(recommendation: Dict, api_key: str, errors: List[Dict]) -> Dict:
    city = recommendation["recommended_city"]
    places = []
    for name in recommendation.get("events", []):
        search_name = PLACE_ALIASES.get(name, name)
        try:
            docs = search_restaurants(city + " " + search_name, api_key, category=None)
        except ApiError as exc:
            errors.append({"stage": "place_verification", "place": name, "message": str(exc)})
            continue
        matches = [d for d in docs if isinstance(d, dict) and d.get("place_name") == search_name]
        if not matches:
            errors.append({"stage": "place_verification", "place": name, "message": "카카오에서 장소 이름 확인 불가"})
        for doc in matches:
            if valid_document(doc, city, errors, "place_verification"):
                places.append(normalize(doc))
                break
    return {"recommended_city": city, "weather": recommendation["weather"],
            "reason": "카카오 주소로 확인된 장소만 안내합니다.",
            "events": [p["name"] for p in places], "places": places}
