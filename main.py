"""남양주시 하루 여행 추천 CLI.

사용법: python main.py -date "YYYY-MM-DD"
"""

import argparse
import sys
import re
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from travel_recommender import config, gemini, kakao, report

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def parse_date(value: str) -> date:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise argparse.ArgumentTypeError("날짜 형식은 YYYY-MM-DD 여야 합니다")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError("날짜 형식은 YYYY-MM-DD 여야 합니다: {!r}".format(value))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="남양주시 하루 여행 추천 (Gemini + 카카오 로컬)",
    )
    parser.add_argument("-date", dest="date", required=True, type=parse_date,
                        metavar="YYYY-MM-DD", help="여행 날짜 (예: 2026-10-20)")
    return parser


def log(message: str) -> None:
    print(message, flush=True)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    date_str = args.date.isoformat()

    keys = config.load_keys()
    missing = config.missing_keys(keys)
    if missing:
        print(config.MISSING_KEY_GUIDE.format(names=", ".join(missing)), file=sys.stderr)
        return 1
    model = config.gemini_model()
    errors: List[Dict] = []

    log("[시작] 여행 날짜: {}".format(date_str))

    # 1) Gemini 지역 추천
    recommendation = gemini.get_recommendation(date_str, keys["GEMINI_API_KEY"], model, errors, log=log)
    if recommendation is None:
        raw_path, _ = report.save_results(RESULTS_DIR, date_str, None, [], errors, None)
        log("[실패] 지역 추천을 받지 못해 종료합니다. (HTTP 404 라면 GEMINI_MODEL 을 바꿔보세요)")
        log("[저장] raw JSON: {}".format(raw_path))
        return 1

    # 원본 생성 문구는 검증된 장소를 우회해 노출하지 않는다.
    recommendation = kakao.verify_recommendation(
        recommendation, keys["KAKAO_REST_API_KEY"], errors)
    restaurants = kakao.find_restaurants(
        recommendation["recommended_city"], keys["KAKAO_REST_API_KEY"], errors, log=log)
    report_md = report.build_basic_report(date_str, recommendation, restaurants)

    raw_path, report_path = report.save_results(
        RESULTS_DIR, date_str, recommendation, restaurants, errors, report_md)
    log("[저장] raw JSON: {}".format(raw_path))
    log("[저장] 리포트:   {}".format(report_path))
    if errors:
        log("[참고] 오류 {}건이 raw JSON 의 errors 에 기록되었습니다.".format(len(errors)))
    log("[완료]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
