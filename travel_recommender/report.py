"""결과 저장과 기본(대체) 리포트 생성."""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from .kakao import is_cafe

WEATHER_NOTE = "※ 실시간 예보가 아니라 해당 날짜(계절)의 일반적인 기후 경향입니다."


def _place_line(r: Dict) -> str:
    return "- [{}]({}) — {} / {}".format(r["name"], r["url"], r["category"], r["address"])


def build_basic_report(date_str: str, recommendation: Dict, restaurants: List[Dict]) -> str:
    """Gemini 리포트 생성 실패 시 가진 데이터만으로 만드는 리포트."""
    city = recommendation.get("recommended_city", "")
    lines = [
        "# 남양주 하루 여행 리포트 ({})".format(date_str),
        "",
        ("> 주소가 확인된 장소로 작성한 리포트입니다. 영업·행사 일정은 별도 확인이 필요합니다."
         if "verified_places" in recommendation else
         "> Gemini 리포트 생성에 실패하여 수집된 데이터로 만든 기본 리포트입니다."),
        "",
        "## 추천 지역",
        "",
        "**{}**".format(city),
        "",
        recommendation.get("reason", ""),
        "",
        "## 날씨",
        "",
        recommendation.get("weather", ""),
        "",
        WEATHER_NOTE,
        "",
        "## 행사·즐길거리",
        "",
    ]
    verified = recommendation.get("verified_places")
    if verified is not None:
        lines += [_place_line(p) for p in verified] or ["- 주소가 확인된 장소 없음"]
    else:
        lines += ["- {}".format(e) for e in recommendation.get("events", [])] or ["- 데이터 없음"]
    meals = [r for r in restaurants if not is_cafe(r.get("category", ""))]
    cafes = [r for r in restaurants if is_cafe(r.get("category", ""))]

    lines += ["", "## 맛집", ""]
    if restaurants:
        lines += ["### 식사", ""]
        lines += [_place_line(r) for r in meals] or ["데이터 없음"]
        if cafes:
            lines += ["", "### 카페·디저트", ""]
            lines += [_place_line(r) for r in cafes]
        lines += ["", "※ 평점 순이 아니라 카카오 검색 정확도 순입니다."]
    else:
        lines.append("데이터 없음")

    lunch = meals[0]["name"] if meals else None
    dinner = meals[1]["name"] if len(meals) > 1 else lunch
    cafe = cafes[0]["name"] if cafes else None
    morning = "{} 도착, 주변 산책과 명소 둘러보기".format(city)
    activity = "행사·즐길거리 참여"
    if verified is not None:
        morning = "{} 방문".format(verified[0]["name"]) if verified else "방문 장소 미정 (주소 확인 필요)"
        activity = (" / ".join(p["name"] for p in verified[1:]) + " 방문"
                    if len(verified) > 1 else "추가 방문 장소 미정")
    lines += [
        "",
        "## 하루 일정",
        "",
        "- **오전**: {}".format(morning),
        "- **오후**: {} {}{}".format(
            "{}에서 점심 후".format(lunch) if lunch else "점심 식사 후",
            activity,
            ", {}에서 커피·디저트로 휴식".format(cafe) if cafe else ""),
        "- **저녁**: {} 후 귀가".format(
            "{}에서 저녁 식사".format(dinner) if dinner else "저녁 식사"),
        "",
    ]
    return "\n".join(lines)


def save_results(results_dir: Path, date_str: str, recommendation: Optional[Dict],
                 restaurants: List[Dict], errors: List[Dict],
                 report_md: Optional[str]) -> Tuple[Path, Optional[Path]]:
    """raw JSON 과 리포트 .md 를 저장하고 경로를 반환."""
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = "{}_{}_{}".format(date_str, stamp, uuid4().hex)

    raw_path = results_dir / "{}_raw.json".format(base)
    raw = {
        "date": date_str,
        "recommendation": recommendation,
        "restaurants": restaurants,
        "errors": errors,
    }
    with raw_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(raw, ensure_ascii=False, indent=2) + "\n")

    report_path = None
    if report_md is not None:
        report_path = results_dir / "{}_report.md".format(base)
        with report_path.open("x", encoding="utf-8") as stream:
            stream.write(report_md)
    return raw_path, report_path
