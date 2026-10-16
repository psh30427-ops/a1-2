"""결과 저장과 기본(대체) 리포트 생성."""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

WEATHER_NOTE = "※ 실시간 예보가 아니라 해당 날짜(계절)의 일반적인 기후 경향입니다."


def build_basic_report(date_str: str, recommendation: Dict, restaurants: List[Dict]) -> str:
    """Gemini 리포트 생성 실패 시 가진 데이터만으로 만드는 리포트."""
    city = recommendation.get("recommended_city", "")
    lines = [
        "# 남양주 하루 여행 리포트 ({})".format(date_str),
        "",
        "> Gemini 리포트 생성에 실패하여 수집된 데이터로 만든 기본 리포트입니다.",
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
    lines += ["- {}".format(e) for e in recommendation.get("events", [])] or ["- 데이터 없음"]
    lines += ["", "## 맛집", ""]
    if restaurants:
        for r in restaurants:
            lines.append("- [{}]({}) — {} / {}".format(r["name"], r["url"], r["category"], r["address"]))
        lines.append("")
        lines.append("※ 평점 순이 아니라 카카오 검색 정확도 순입니다.")
    else:
        lines.append("데이터 없음")
    first = restaurants[0]["name"] if restaurants else None
    second = restaurants[1]["name"] if len(restaurants) > 1 else first
    lines += [
        "",
        "## 하루 일정",
        "",
        "- **오전**: {} 도착, 주변 산책과 명소 둘러보기".format(city),
        "- **오후**: {}에서 점심 후 행사·즐길거리 참여".format(first) if first
        else "- **오후**: 점심 식사 후 행사·즐길거리 참여",
        "- **저녁**: {}에서 저녁 식사 후 귀가".format(second) if second
        else "- **저녁**: 저녁 식사 후 귀가",
        "",
    ]
    return "\n".join(lines)


def save_results(results_dir: Path, date_str: str, recommendation: Optional[Dict],
                 restaurants: List[Dict], errors: List[Dict],
                 report_md: Optional[str]) -> Tuple[Path, Optional[Path]]:
    """raw JSON 과 리포트 .md 를 저장하고 경로를 반환."""
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = "{}_{}".format(date_str, stamp)

    raw_path = results_dir / "{}_raw.json".format(base)
    raw = {
        "date": date_str,
        "recommendation": recommendation,
        "restaurants": restaurants,
        "errors": errors,
    }
    raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report_path = None
    if report_md is not None:
        report_path = results_dir / "{}_report.md".format(base)
        report_path.write_text(report_md, encoding="utf-8")
    return raw_path, report_path
