"""오프라인 테스트: requests 를 mock 하므로 키와 네트워크 없이 동작한다.

실행: .venv/bin/python -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

import main
from travel_recommender import gemini, kakao, report

FAKE_GEMINI_KEY = "FAKE-GEMINI-KEY-do-not-leak-1234"
FAKE_KAKAO_KEY = "FAKE-KAKAO-KEY-do-not-leak-5678"
FAKE_ENV = {"GEMINI_API_KEY": FAKE_GEMINI_KEY, "KAKAO_REST_API_KEY": FAKE_KAKAO_KEY}

GOOD_REC = {
    "recommended_city": "남양주시 조안면",
    "weather": "계절 경향상 선선하고 맑은 날이 많습니다.",
    "events": ["두물머리 산책", "다산 유적지 관람"],
    "reason": "강변 풍경이 좋습니다. 가을 산책에 알맞습니다.",
}


class FakeResponse:
    def __init__(self, status_code=200, payload=None, body_text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = body_text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def gemini_text(text):
    return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": text}]}}]})


def kakao_docs(*cats):
    return FakeResponse(200, {"documents": [
        {"place_name": "식당{}".format(i), "road_address_name": "남양주시 조안면 {}길".format(i),
         "category_name": c, "place_url": "http://place.map.kakao.com/{}".format(i),
         "x": "127.3", "y": "37.5"}
        for i, c in enumerate(cats)
    ]})


class MainFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        patches = [
            mock.patch.object(main, "RESULTS_DIR", self.tmp),
            mock.patch.dict(os.environ, FAKE_ENV, clear=True),
            # 실제 .env 파일을 절대 읽지 않도록 차단
            mock.patch("travel_recommender.config.load_dotenv", lambda **kw: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_main(self, post_responses, get_response):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("requests.post", side_effect=post_responses) as post, \
                mock.patch("requests.get", side_effect=[get_response] if get_response else []) as get, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main.main(["-date", "2026-10-20"])
        self.post, self.get = post, get
        self.output = out.getvalue() + err.getvalue()
        return code

    def load_raw(self):
        files = list(self.tmp.glob("*_raw.json"))
        self.assertEqual(len(files), 1)
        return json.loads(files[0].read_text(encoding="utf-8"))

    def assert_no_key_leak(self):
        texts = [self.output] + [p.read_text(encoding="utf-8") for p in self.tmp.iterdir()]
        for text in texts:
            self.assertNotIn(FAKE_GEMINI_KEY, text)
            self.assertNotIn(FAKE_KAKAO_KEY, text)

    def test_happy_path_and_key_sent_only_in_headers(self):
        code = self.run_main(
            [gemini_text(json.dumps(GOOD_REC, ensure_ascii=False)), gemini_text("# 리포트\n본문")],
            kakao_docs("음식점 > 한식 > 냉면", "음식점 > 중식", "음식점 > 한식 > 냉면", "음식점 > 카페"),
        )
        self.assertEqual(code, 0)
        call = self.post.call_args_list[0]
        self.assertEqual(call.kwargs["headers"]["x-goog-api-key"], FAKE_GEMINI_KEY)
        self.assertNotIn(FAKE_GEMINI_KEY, call.args[0])
        gcall = self.get.call_args
        self.assertEqual(gcall.kwargs["params"]["category_group_code"], "FD6")
        self.assertEqual(gcall.kwargs["params"]["query"], "남양주 조안면 맛집")
        raw = self.load_raw()
        self.assertEqual(raw["errors"], [])
        self.assertEqual(len(raw["restaurants"]), 3)  # 중복 냉면 제외
        self.assertEqual(set(raw["restaurants"][0]), {"name", "address", "category", "url", "lat", "lng"})
        self.assertTrue(list(self.tmp.glob("*_report.md")))
        self.assert_no_key_leak()

    def test_kakao_zero_results_continues(self):
        code = self.run_main(
            [gemini_text(json.dumps(GOOD_REC, ensure_ascii=False)), FakeResponse(500)],
            FakeResponse(200, {"documents": []}),
        )
        self.assertEqual(code, 0)
        raw = self.load_raw()
        self.assertEqual(raw["restaurants"], [])
        self.assertTrue(any(e["stage"] == "kakao" and "0건" in e["message"] for e in raw["errors"]))
        report_md = next(self.tmp.glob("*_report.md")).read_text(encoding="utf-8")
        self.assertIn("데이터 없음", report_md)  # 리포트 실패 → 기본 리포트
        self.assertIn("기본 리포트", report_md)
        self.assert_no_key_leak()

    def test_kakao_http_error_records_status_only(self):
        secret_body = "server said: secret internal detail"
        code = self.run_main(
            [gemini_text(json.dumps(GOOD_REC, ensure_ascii=False)), gemini_text("# 리포트")],
            FakeResponse(401, {"msg": secret_body}, body_text=secret_body),
        )
        self.assertEqual(code, 0)
        raw = self.load_raw()
        self.assertIn({"stage": "kakao", "message": "카카오 로컬 HTTP 401"}, raw["errors"])
        self.assertNotIn(secret_body, json.dumps(raw, ensure_ascii=False))
        self.assertNotIn(secret_body, self.output)
        self.assert_no_key_leak()

    def test_kakao_network_exception_continues(self):
        with mock.patch("requests.post", side_effect=[
                gemini_text(json.dumps(GOOD_REC, ensure_ascii=False)), gemini_text("# r")]), \
                mock.patch("requests.get", side_effect=requests.ConnectionError(
                    "https://dapi.kakao.com/... " + FAKE_KAKAO_KEY)), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            code = main.main(["-date", "2026-10-20"])
        self.output = out.getvalue()
        self.assertEqual(code, 0)
        raw = self.load_raw()
        self.assertIn({"stage": "kakao", "message": "카카오 로컬 ConnectionError"}, raw["errors"])
        self.assert_no_key_leak()

    def test_gemini_parse_fail_then_retry_success(self):
        fenced = "```json\n" + json.dumps(GOOD_REC, ensure_ascii=False) + "\n```"
        code = self.run_main(
            [gemini_text("이건 JSON 이 아닙니다"), gemini_text(fenced), gemini_text("# r")],
            kakao_docs("음식점 > 한식"),
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.post.call_count, 3)
        raw = self.load_raw()
        self.assertEqual(raw["recommendation"]["recommended_city"], "남양주시 조안면")
        self.assertEqual(raw["errors"][0]["stage"], "gemini_recommend")

    def test_gemini_retry_prompt_adds_format_note(self):
        code = self.run_main(
            [gemini_text("이건 JSON 이 아닙니다"), gemini_text(json.dumps(GOOD_REC, ensure_ascii=False)),
             gemini_text("# r")],
            kakao_docs("음식점 > 한식"),
        )
        self.assertEqual(code, 0)
        prompts = [c.kwargs["json"]["contents"][0]["parts"][0]["text"]
                   for c in self.post.call_args_list[:2]]
        self.assertNotIn(gemini.RETRY_NOTE, prompts[0])
        self.assertTrue(prompts[1].endswith(gemini.RETRY_NOTE))
        self.assertIn("직전 응답이 형식에 맞지 않았다", prompts[1])
        self.assertEqual(prompts[1], prompts[0] + gemini.RETRY_NOTE)

    def test_gemini_validation_fail_twice_exits(self):
        bad = dict(GOOD_REC, recommended_city="서울시 강남구")
        code = self.run_main([gemini_text("not json"), gemini_text(json.dumps(bad, ensure_ascii=False))], None)
        self.assertEqual(code, 1)
        self.assertEqual(self.post.call_count, 2)  # 재시도는 딱 1회
        self.get.assert_not_called()
        raw = self.load_raw()
        self.assertIsNone(raw["recommendation"])
        self.assertEqual(len(raw["errors"]), 2)
        self.assert_no_key_leak()

    def test_gemini_http_404_no_retry(self):
        code = self.run_main([FakeResponse(404, body_text="model not found")], None)
        self.assertEqual(code, 1)
        self.assertEqual(self.post.call_count, 1)
        self.assertIn("GEMINI_MODEL", self.output)
        self.assertEqual(self.load_raw()["errors"], [{"stage": "gemini_recommend", "message": "Gemini HTTP 404"}])

    def test_gemini_model_env(self):
        with mock.patch.dict(os.environ, {"GEMINI_MODEL": "my-model"}):
            self.run_main([FakeResponse(404)], None)
        self.assertIn("/models/my-model:generateContent", self.post.call_args.args[0])


class CliTest(unittest.TestCase):
    def run_cli(self, argv, env):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("travel_recommender.config.load_dotenv", lambda **kw: None), \
                mock.patch("requests.post") as post, mock.patch("requests.get") as get, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main.main(argv)
            except SystemExit as exc:
                code = exc.code
        post.assert_not_called()
        get.assert_not_called()
        return code, out.getvalue() + err.getvalue()

    def test_missing_keys_exit_immediately(self):
        code, output = self.run_cli(["-date", "2026-10-20"], {})
        self.assertEqual(code, 1)
        self.assertIn("GEMINI_API_KEY", output)
        self.assertIn("KAKAO_REST_API_KEY", output)

    def test_one_missing_key_does_not_print_other(self):
        code, output = self.run_cli(["-date", "2026-10-20"], {"GEMINI_API_KEY": FAKE_GEMINI_KEY})
        self.assertEqual(code, 1)
        self.assertNotIn(FAKE_GEMINI_KEY, output)

    def test_bad_date_prints_usage(self):
        for argv in (["-date", "2026/10/20"], ["-date", "2026-02-30"], []):
            code, output = self.run_cli(argv, FAKE_ENV)
            self.assertEqual(code, 2)
            self.assertIn("usage:", output)


class UnitTest(unittest.TestCase):
    def test_pick_diverse(self):
        places = [kakao.normalize(d) for d in kakao_docs(
            "음식점 > 한식 > 냉면", "음식점 > 한식 > 냉면", "음식점 > 한식 > 국수",
            "음식점 > 중식 > 중국요리", "음식점 > 일식 > 초밥,롤", "음식점 > 양식", "음식점 > 분식",
        ).json()["documents"]]
        picked = kakao.pick_diverse(places, 5)
        self.assertEqual(len(picked), 5)
        cats = [p["category"] for p in picked]
        self.assertEqual(len(set(cats)), 5)

    def test_custom_place_searcher(self):
        class FakeSearcher:
            def __init__(self):
                self.calls = []

            def search(self, query, api_key):
                self.calls.append((query, api_key))
                return [{"name": "가", "address": "주소", "category": "음식점 > 한식", "url": "u",
                         "lat": 0.0, "lng": 0.0}]

        searcher = FakeSearcher()
        errors = []
        with mock.patch("requests.get") as get:
            picked = kakao.find_restaurants("남양주시 조안면", "k", errors, log=lambda m: None,
                                            searcher=searcher)
        get.assert_not_called()  # 카카오 API 를 부르지 않음
        self.assertEqual(searcher.calls, [("남양주 조안면 맛집", "k")])
        self.assertEqual([p["name"] for p in picked], ["가"])
        self.assertEqual(errors, [])

    def test_query_building(self):
        self.assertEqual(kakao.build_query("남양주시 화도읍"), "남양주 화도읍 맛집")
        self.assertEqual(kakao.build_query("남양주시"), "남양주 맛집")

    def test_parse_rejects_bad_events(self):
        for events in ([], ["a", "b", "c", "d"], "문자열", [1]):
            with self.assertRaises(gemini.RecommendationError):
                gemini.parse_recommendation(json.dumps(dict(GOOD_REC, events=events)))

    def test_parse_with_surrounding_text(self):
        text = "추천입니다:\n" + json.dumps(GOOD_REC, ensure_ascii=False) + "\n끝"
        self.assertEqual(gemini.parse_recommendation(text)["recommended_city"], "남양주시 조안면")


class BasicReportTest(unittest.TestCase):
    def places(self, *cats):
        return [kakao.normalize(d) for d in kakao_docs(*cats).json()["documents"]]

    def schedule(self, md):
        return md.split("## 하루 일정", 1)[1]

    def test_cafe_not_used_for_dinner(self):
        # 두 번째 결과가 카페여도 저녁은 식사 장소(식당2)로
        md = report.build_basic_report("2026-10-25", GOOD_REC, self.places(
            "음식점 > 한식 > 국수", "음식점 > 카페", "음식점 > 중식"))
        sched = self.schedule(md)
        self.assertIn("**오후**: 식당0에서 점심 후 행사·즐길거리 참여, 식당1에서 커피·디저트로 휴식", sched)
        self.assertIn("**저녁**: 식당2에서 저녁 식사 후 귀가", sched)
        self.assertIn("### 식사", md)
        self.assertIn("### 카페·디저트", md)

    def test_bakery_counts_as_cafe(self):
        self.assertTrue(kakao.is_cafe("음식점 > 간식 > 제과,베이커리"))
        self.assertFalse(kakao.is_cafe("음식점 > 한식 > 냉면"))

    def test_only_cafes(self):
        md = report.build_basic_report("2026-10-25", GOOD_REC, self.places("음식점 > 카페"))
        sched = self.schedule(md)
        self.assertIn("**오후**: 점심 식사 후 행사·즐길거리 참여, 식당0에서 커피·디저트로 휴식", sched)
        self.assertIn("**저녁**: 저녁 식사 후 귀가", sched)
        self.assertIn("### 식사\n\n데이터 없음", md)

    def test_single_meal_place_no_cafe(self):
        md = report.build_basic_report("2026-10-25", GOOD_REC, self.places("음식점 > 한식"))
        sched = self.schedule(md)
        self.assertNotIn("휴식", sched)
        self.assertNotIn("### 카페·디저트", md)


if __name__ == "__main__":
    unittest.main()
