"""키/실제 .env/기존 results 없이 검증하는 회귀 테스트."""
import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

import main
from travel_recommender import gemini, kakao, report
from travel_recommender.errors import ApiError
from tests.test_offline import GOOD_REC, FakeResponse, gemini_text


def document(name="검증명소", address="경기 남양주시 조안면 북한강로 1", **kwargs):
    return dict(place_name=name, address_name=address, category_name="음식점 > 한식",
                place_url="https://place.map.kakao.com/1", **kwargs)


class VerificationTest(unittest.TestCase):
    def test_explicit_alias_searches_and_reports_canonical_name(self):
        rec = dict(GOOD_REC, events=["다산유적지"])
        errors = []
        with mock.patch("requests.get", return_value=FakeResponse(
                200, {"documents": [document("정약용유적지")]})) as get:
            verified = kakao.verify_recommendation(rec, "fake", errors)
        self.assertEqual(get.call_args.kwargs["params"], {
            "query": "남양주시 조안면 정약용유적지", "size": 15})
        self.assertEqual(verified["events"], ["정약용유적지"])
        self.assertEqual(errors, [])
        md = report.build_basic_report("2026-11-10", verified, [])
        self.assertIn("정약용유적지", md)
        self.assertNotIn("다산유적지", md)

    def test_alias_still_requires_selected_area_address(self):
        for address in ("경기 남양주시 화도읍 1", "경기 양평군 양서면 1", ""):
            with self.subTest(address=address), mock.patch("requests.get", return_value=FakeResponse(
                    200, {"documents": [document("정약용유적지", address)]})):
                errors = []
                verified = kakao.verify_recommendation(
                    dict(GOOD_REC, events=["다산유적지"]), "fake", errors)
                self.assertEqual(verified["places"], [])
                self.assertTrue(errors)

    def test_alias_and_unknown_names_do_not_allow_fuzzy_matches(self):
        cases = [("다산유적지", "정약용유적지 주차장"),
                 ("다산유적지", "정약용유적"),
                 ("다산유적지 관람", "정약용유적지"),
                 ("물어나들이", "물의정원"),
                 ("물어나들이", "물어나들이공원")]
        for requested, returned in cases:
            with self.subTest(requested=requested, returned=returned), mock.patch(
                    "requests.get", return_value=FakeResponse(
                        200, {"documents": [document(returned)]})) as get:
                errors = []
                verified = kakao.verify_recommendation(
                    dict(GOOD_REC, events=[requested]), "fake", errors)
                self.assertEqual(verified["places"], [])
                self.assertEqual(errors[0]["place"], requested)
                self.assertIn("이름 확인 불가", errors[0]["message"])
                if requested != "다산유적지":
                    self.assertEqual(get.call_args.kwargs["params"]["query"],
                                     "남양주시 조안면 " + requested)

    def test_general_place_request_omits_category_parameter(self):
        rec = dict(GOOD_REC, events=["검증명소"])
        with mock.patch("requests.get", return_value=FakeResponse(
                200, {"documents": [document()]})) as get:
            verified = kakao.verify_recommendation(rec, "fake", [])
        self.assertEqual(get.call_args.kwargs["params"], {
            "query": "남양주시 조안면 검증명소", "size": 15})
        self.assertEqual(verified["events"], ["검증명소"])

    def test_empty_or_none_category_is_not_sent(self):
        for category in ("", None):
            with self.subTest(category=category), mock.patch(
                    "requests.get", return_value=FakeResponse(200, {"documents": []})) as get:
                kakao.search_restaurants("물의정원", "fake", category=category)
                self.assertEqual(get.call_args.kwargs["params"], {
                    "query": "물의정원", "size": 15})

    def test_restaurant_request_keeps_fd6(self):
        with mock.patch("requests.get", return_value=FakeResponse(
                200, {"documents": [document()]})) as get:
            kakao.find_restaurants("남양주시 조안면", "fake", [], log=lambda _: None)
        self.assertEqual(get.call_args.kwargs["params"], {
            "query": "남양주 조안면 맛집", "size": 15, "category_group_code": "FD6"})

    def test_address_boundaries_and_missing_data(self):
        for address in ("경기 양평군 양서면 1", "경기 남양주시 화도읍 1",
                        "경기 남양주시 조안면외 1", "경기 남양주시 다산동 1", "", None,
                        "경기 남양주시 북한강로 1"):
            with self.subTest(address=address):
                errors = []
                self.assertFalse(kakao.valid_document(document(address=address),
                                                     "남양주시 조안면", errors, "test"))
                self.assertTrue(errors[0]["message"])
        self.assertTrue(kakao.valid_document(document(), "남양주시 조안면", [], "test"))
        self.assertFalse(kakao.valid_document(document(name=""), "남양주시 조안면", [], "test"))

    def test_restaurants_filtered_before_diversity(self):
        docs = [document("외부", "경기 양평군 양서면 1"), document("주소없음", ""),
                document("내부")]
        errors = []
        with mock.patch("requests.get", return_value=FakeResponse(200, {"documents": docs})):
            places = kakao.find_restaurants("남양주시 조안면", "fake", errors, log=lambda _: None)
        self.assertEqual([p["name"] for p in places], ["내부"])
        self.assertEqual(len(errors), 2)

    def test_places_report_and_schedule_exclude_unverified(self):
        rec = dict(GOOD_REC, events=["외부명소", "미확인장소", "검증명소"], reason="외부명소 추천")
        errors = []
        with mock.patch("requests.get", side_effect=[
            FakeResponse(200, {"documents": [document("외부명소", "경기 양평군 양서면 1")]}),
            FakeResponse(200, {"documents": []}),
            FakeResponse(200, {"documents": [document()]}),
        ]):
            verified = kakao.verify_recommendation(rec, "fake", errors)
        md = report.build_basic_report("2026-10-20", verified, [])
        self.assertIn("검증명소", md)
        self.assertNotIn("외부명소", md)
        self.assertNotIn("미확인장소", md)
        self.assertEqual(len(errors), 2)
        self.assertEqual(verified["events"], ["검증명소"])

    def test_main_uses_only_verified_places_without_generated_report(self):
        rec = dict(GOOD_REC, events=["외부명소", "검증명소"])
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(main, "RESULTS_DIR", Path(tmp)), \
                mock.patch("travel_recommender.config.load_keys", return_value={
                    "GEMINI_API_KEY": "fake", "KAKAO_REST_API_KEY": "fake"}), \
                mock.patch("travel_recommender.config.gemini_model", return_value="model"), \
                mock.patch("requests.post", return_value=gemini_text(json.dumps(rec))) as post, \
                mock.patch("requests.get", side_effect=[
                    FakeResponse(200, {"documents": [document("외부명소", "경기 양평군 양서면 1")]}),
                    FakeResponse(200, {"documents": [document()]}),
                    FakeResponse(200, {"documents": [document("내부식당"),
                        document("외부식당", "경기 남양주시 화도읍 1")]}),
                ]), mock.patch("main.log"):
            self.assertEqual(main.main(["-date", "2026-10-20"]), 0)
            self.assertEqual(post.call_count, 1)
            md = next(Path(tmp).glob("*_report.md")).read_text()
            for name in ("외부명소", "외부식당"):
                self.assertNotIn(name, md)
            for name in ("검증명소", "내부식당"):
                self.assertIn(name, md)
            raw = json.loads(next(Path(tmp).glob("*_raw.json")).read_text())
            self.assertEqual(len(raw["errors"]), 2)

    def test_failed_place_search_is_recorded(self):
        errors = []
        with mock.patch("requests.get", side_effect=requests.Timeout("secret")):
            verified = kakao.verify_recommendation(GOOD_REC, "fake", errors)
        self.assertEqual(verified["places"], [])
        self.assertEqual(len(errors), 2)
        self.assertNotIn("secret", json.dumps(errors))

    def test_jibun_used_when_road_address_omits_dong(self):
        doc = document(address="경기 남양주시 다산동 1", road_address_name="경기 남양주시 다산로 1")
        self.assertTrue(kakao.valid_document(doc, "남양주시 다산동", [], "test"))
        self.assertEqual(kakao.normalize(doc)["address"], doc["address_name"])

    def test_strict_dates(self):
        for value in ("2026-1-01", "2026-01-1", "2026-02-29", "2026-04-31",
                      "0000-01-01", "2026-01-01 ", "２０２６-01-01"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                main.parse_date(value)
        self.assertEqual(main.parse_date("2024-02-29").isoformat(), "2024-02-29")

    def test_city_requires_one_area(self):
        for city in ("남양주시", "남양주시 조안면 화도읍", "남양주시 조안면외"):
            with self.assertRaises(gemini.RecommendationError):
                gemini.parse_recommendation(json.dumps(dict(GOOD_REC, recommended_city=city)))

    def test_same_second_keeps_both_result_pairs(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch("travel_recommender.report.datetime") as dt:
            dt.now.return_value.strftime.return_value = "20260101-000000"
            first = report.save_results(Path(tmp), "2026-10-20", GOOD_REC, [], [], "first")
            old = first[0].read_bytes()
            second = report.save_results(Path(tmp), "2026-10-20", None, [], [], "second")
            self.assertNotEqual(first, second)
            self.assertEqual(first[0].read_bytes(), old)
            self.assertEqual(first[1].read_text(), "first")
            self.assertEqual(second[1].read_text(), "second")
            self.assertEqual(len(list(Path(tmp).iterdir())), 4)


class RetryTest(unittest.TestCase):
    @mock.patch("travel_recommender.gemini.time.sleep")
    def test_transient_statuses_stop_at_three(self, sleep):
        for status in (429, 500, 502, 503, 504):
            with self.subTest(status=status), mock.patch("requests.post", return_value=FakeResponse(status)) as post:
                with self.assertRaises(ApiError):
                    gemini.call_gemini("prompt", "fake", "model")
                self.assertEqual(post.call_count, 3)

    @mock.patch("travel_recommender.gemini.time.sleep")
    def test_timeout_recovers_on_third_attempt(self, sleep):
        with mock.patch("requests.post", side_effect=[requests.Timeout("secret"),
                        FakeResponse(503), gemini_text("ok")]) as post:
            self.assertEqual(gemini.call_gemini("prompt", "fake", "model"), "ok")
            self.assertEqual(post.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    @mock.patch("travel_recommender.gemini.time.sleep")
    def test_timeout_exhaustion_and_permanent_errors(self, sleep):
        for response, count in ((requests.Timeout("secret"), 3), (FakeResponse(400), 1),
                                (FakeResponse(401), 1), (FakeResponse(404), 1),
                                (requests.ConnectionError("secret"), 1)):
            with self.subTest(response=type(response).__name__):
                kwargs = {"side_effect": response} if isinstance(response, Exception) else {"return_value": response}
                with mock.patch("requests.post", **kwargs) as post:
                    with self.assertRaises(ApiError) as ctx:
                        gemini.call_gemini("prompt", "fake", "model")
                    self.assertEqual(post.call_count, count)
                    self.assertNotIn("secret", str(ctx.exception))
