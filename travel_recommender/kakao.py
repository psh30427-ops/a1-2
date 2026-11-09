"""카카오 로컬 API 키워드 검색 (음식점 카테고리 FD6)."""

import re
from typing import Dict, List

import requests

from .errors import ApiError, safe_exception_name

KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
SERVICE = "카카오 로컬"
TIMEOUT = 15


def area_from_city(recommended_city: str) -> str:
    """'남양주시 화도읍' -> '화도읍'. 접두어만 남으면 빈 문자열."""
    return recommended_city.replace("남양주시", "", 1).strip()


def build_query(recommended_city: str) -> str:
    area = area_from_city(recommended_city)
    return "남양주 {} 맛집".format(area) if area else "남양주 맛집"


def search_restaurants(query: str, api_key: str, size: int = 15,
                       category: str = "FD6") -> List[Dict]:
    """카카오 키워드 검색 원본 documents 목록을 반환. 실패 시 ApiError."""
    try:
        resp = requests.get(
            KAKAO_KEYWORD_URL,
            headers={"Authorization": "KakaoAK {}".format(api_key)},
            params=dict({"query": query, "size": size},
                        **({"category_group_code": category} if category else {})),
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


def address_in_area(address: str, city: str) -> bool:
    """주소의 행정구역 토큰을 비교한다. 불명확한 주소는 허용하지 않는다."""
    if not isinstance(address, str) or not re.fullmatch(r"남양주시 [가-힣]+[읍면동]", city):
        return False
    parts = address.split()
    if parts and parts[0] in ("경기", "경기도"):
        parts = parts[1:]
    return len(parts) >= 2 and parts[:2] == city.split()


def local_document(doc: Dict, city: str) -> bool:
    # 도로명 주소에 동이 없으면 지번 주소를 사용한다. 두 주소가 충돌하면 제외한다.
    addresses = [doc.get(key) for key in ("road_address_name", "address_name")
                 if doc.get(key)]
    if not any(address_in_area(a, city) for a in addresses):
        return False
    for address in addresses:
        tokens = address.split()
        if tokens and tokens[0] in ("경기", "경기도"):
            tokens = tokens[1:]
        if not tokens or tokens[0] != "남양주시":
            return False
        if len(tokens) > 1 and re.fullmatch(r"[가-힣]+[읍면동]", tokens[1]):
            if tokens[1] != city.split()[1]:
                return False
    return True


def verify_recommendation(recommendation: Dict, api_key: str,
                          errors: List[Dict], log=print) -> Dict:
    """장소명이 일치하고 선택 지역의 주소가 확인된 장소만 남긴다."""
    city = recommendation["recommended_city"]
    places = []
    seen = set()
    for candidate in recommendation.get("events", []):
        try:
            docs = search_restaurants(candidate, api_key, category="")
        except ApiError as exc:
            errors.append({"stage": "place_verification", "message": str(exc)})
            continue
        name_key = re.sub(r"\s+", "", candidate)
        matches = [d for d in docs if isinstance(d, dict)
                   and re.sub(r"\s+", "", d.get("place_name", "")) == name_key]
        # 동명 장소가 여러 곳이면 임의로 선택하지 않는다.
        if len(matches) == 1 and local_document(matches[0], city):
            place = normalize(matches[0])
            if place["name"] not in seen:
                places.append(place)
                seen.add(place["name"])
        else:
            errors.append({"stage": "place_verification",
                           "message": "장소 제외: 지역 밖 또는 이름·주소 확인 불가"})
    result = dict(recommendation)
    result["verified_places"] = places
    result["events"] = [p["name"] for p in places]
    # 모델의 설명에 검증되지 않은 장소가 남아 재등장하지 않도록 한다.
    result["reason"] = "선택 지역 안에서 주소가 확인된 장소와 식당만 안내합니다."
    log("[장소 검증] {}곳 확인".format(len(places)))
    return result


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def normalize(doc: Dict) -> Dict:
    return {
        "name": doc.get("place_name", ""),
        "address": doc.get("road_address_name") or doc.get("address_name", ""),
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
    local = [d for d in docs if isinstance(d, dict) and local_document(d, recommended_city)]
    if len(local) != len(docs):
        errors.append({"stage": "kakao", "message": "지역 밖 또는 주소 확인 불가 식당 {}곳 제외".format(len(docs) - len(local))})
    picked = pick_diverse([normalize(d) for d in local])
    log("[카카오] {}건 중 {}곳 선택".format(len(docs), len(picked)))
    return picked
