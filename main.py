"""남양주시 하루 여행 추천 CLI.

사용법: python main.py -date "YYYY-MM-DD"
"""

import argparse
import sys
from datetime import date, datetime
from typing import List, Optional

from travel_recommender import config


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

    keys = config.load_keys()
    missing = config.missing_keys(keys)
    if missing:
        print(config.MISSING_KEY_GUIDE.format(names=", ".join(missing)), file=sys.stderr)
        return 1

    log("[시작] 여행 날짜: {}".format(args.date.isoformat()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
