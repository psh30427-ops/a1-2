"""남양주시 하루 여행 추천 CLI.

사용법: python main.py -date "YYYY-MM-DD"
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from travel_recommender import config, gemini, kakao, report
from travel_recommender.errors import ApiError

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def parse_date(value: str) -> date:
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

    # 2) 카카오 맛집 검색 (실패해도 계속)
    restaurants = kakao.find_restaurants(
        recommendation["recommended_city"], keys["KAKAO_REST_API_KEY"], errors, log=log)

    # 3) Gemini 최종 리포트 (실패 시 기본 리포트)
    log("[Gemini] 최종 리포트 작성 요청")
    try:
        report_md = gemini.write_report(date_str, recommendation, restaurants,
                                        keys["GEMINI_API_KEY"], model)
    except ApiError as exc:
        errors.append({"stage": "gemini_report", "message": str(exc)})
        log("[Gemini] 리포트 생성 실패: {} → 기본 리포트로 대체".format(exc))
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
