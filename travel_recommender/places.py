"""지도(장소) 검색 인터페이스. 다른 지도 서비스로 바꾸려면 이 형태에 맞는 구현을 추가한다."""

from typing import Dict, List, Protocol

# search() 가 돌려주는 장소 dict 의 키
PLACE_KEYS = ("name", "address", "category", "url", "lat", "lng")


class PlaceSearcher(Protocol):
    """query 로 음식점을 검색해 PLACE_KEYS 형태의 dict 목록을 정확도 순으로 돌려준다.

    결과가 없으면 [] 를 돌려주고, 요청이 실패하면 errors.ApiError 를 던진다
    (상태 코드나 예외 종류만 담고 키·응답 본문은 담지 않는다).
    """

    def search(self, query: str, api_key: str) -> List[Dict]:
        ...
