"""모듈 2 파이프라인 테스트. TMDBClient는 가짜로 대체한다 (실제 API 호출 없음)."""
from __future__ import annotations

from src.models import MovieCandidate
from src.movie_search import confirm_movie, search_movies


class FakeTMDB:
    """search_movie/movie_details 호출에 미리 준비한 응답을 돌려주는 가짜."""

    def __init__(self, search_by_lang=None, details_by_id=None):
        self.search_by_lang = search_by_lang or {}
        self.details_by_id = details_by_id or {}
        self.search_calls = []
        self.detail_calls = []

    def search_movie(self, query, year=None, language="ko-KR", page=1):
        self.search_calls.append((query, year, language))
        return self.search_by_lang.get(language, [])

    def movie_details(self, movie_id, language="ko-KR"):
        self.detail_calls.append((movie_id, language))
        return self.details_by_id[(movie_id, language)]


KO_RESULT = {"id": 671, "title": "해리포터와 마법사의 돌",
             "original_title": "Harry Potter and the Philosopher's Stone",
             "release_date": "2001-11-16", "overview": "마법사의 돌 줄거리",
             "poster_path": "/hp.jpg"}
EN_RESULT = {"id": 671, "title": "Harry Potter and the Philosopher's Stone",
             "original_title": "Harry Potter and the Philosopher's Stone",
             "release_date": "2001-11-16", "overview": "English overview",
             "poster_path": "/hp.jpg"}


class TestSearchMovies:
    def test_ko_results_used_first(self):
        tmdb = FakeTMDB(search_by_lang={"ko-KR": [KO_RESULT],
                                        "en-US": [EN_RESULT]})
        out = search_movies("해리포터", tmdb=tmdb)
        assert len(out) == 1  # 같은 tmdb_id는 합쳐진다
        assert out[0].title == "해리포터와 마법사의 돌"  # ko 제목 우선
        assert out[0].overview == "마법사의 돌 줄거리"  # ko 개요 유지
        assert out[0].year == 2001
        assert out[0].tmdb_id == 671
        assert out[0].poster_url == "https://image.tmdb.org/t/p/w342/hp.jpg"
        assert out[0].source_url == "https://www.themoviedb.org/movie/671"

    def test_en_fallback_when_ko_empty(self):
        tmdb = FakeTMDB(search_by_lang={"ko-KR": [], "en-US": [EN_RESULT]})
        out = search_movies("harry potter", tmdb=tmdb)
        assert [c[2] for c in tmdb.search_calls] == ["ko-KR", "en-US"]
        assert out[0].title == "Harry Potter and the Philosopher's Stone"

    def test_en_fills_missing_ko_overview(self):
        ko_no_overview = dict(KO_RESULT, overview="")
        tmdb = FakeTMDB(search_by_lang={"ko-KR": [ko_no_overview],
                                        "en-US": [EN_RESULT]})
        out = search_movies("해리포터", tmdb=tmdb)
        assert out[0].overview == "English overview"

    def test_year_passed_through(self):
        tmdb = FakeTMDB(search_by_lang={"ko-KR": [KO_RESULT]})
        search_movies("해리포터", year=2001, tmdb=tmdb)
        assert tmdb.search_calls[0][1] == 2001

    def test_max_candidates(self):
        many = [dict(KO_RESULT, id=i) for i in range(20)]
        tmdb = FakeTMDB(search_by_lang={"ko-KR": many, "en-US": []})
        out = search_movies("x", tmdb=tmdb, max_candidates=8)
        assert len(out) == 8

    def test_no_results_anywhere(self):
        tmdb = FakeTMDB(search_by_lang={"ko-KR": [], "en-US": []})
        assert search_movies("없는영화", tmdb=tmdb) == []


DETAILS_KO = {"id": 671, "title": "해리포터와 마법사의 돌",
              "original_title": "Harry Potter and the Philosopher's Stone",
              "release_date": "2001-11-16", "overview": "줄거리",
              "poster_path": "/hp.jpg",
              "credits": {"crew": [{"job": "Producer", "name": "David Heyman"},
                                   {"job": "Director", "name": "Chris Columbus"}]}}


def make_candidate():
    return MovieCandidate(title="해리포터와 마법사의 돌", year=2001, tmdb_id=671,
                          original_title="Harry Potter and the Philosopher's Stone",
                          overview="", poster_url=None)


class TestConfirmMovie:
    def test_builds_movie_with_director_and_english_title(self):
        tmdb = FakeTMDB(details_by_id={(671, "ko-KR"): DETAILS_KO})
        movie = confirm_movie(make_candidate(), tmdb)
        assert movie.title == "해리포터와 마법사의 돌"
        assert movie.english_title == "Harry Potter and the Philosopher's Stone"
        assert movie.year == 2001
        assert movie.director == "Chris Columbus"
        assert movie.poster_url == "https://image.tmdb.org/t/p/w342/hp.jpg"
        assert movie.tmdb_url == "https://www.themoviedb.org/movie/671"
        # original_title이 로마자라 en-US를 다시 부르지 않는다
        assert tmdb.detail_calls == [(671, "ko-KR")]

    def test_korean_original_title_fetches_en_details(self):
        details_ko = {"id": 496243, "title": "기생충", "original_title": "기생충",
                      "release_date": "2019-05-30", "overview": "줄거리",
                      "poster_path": "/p.jpg",
                      "credits": {"crew": [{"job": "Director", "name": "봉준호"}]}}
        details_en = {"id": 496243, "title": "Parasite", "original_title": "기생충",
                      "release_date": "2019-05-30", "overview": "Overview",
                      "poster_path": "/p.jpg", "credits": {"crew": []}}
        tmdb = FakeTMDB(details_by_id={(496243, "ko-KR"): details_ko,
                                       (496243, "en-US"): details_en})
        cand = MovieCandidate(title="기생충", year=2019, tmdb_id=496243,
                              original_title="기생충")
        movie = confirm_movie(cand, tmdb)
        assert movie.english_title == "Parasite"
        assert movie.director == "봉준호"
        assert tmdb.detail_calls == [(496243, "ko-KR"), (496243, "en-US")]

    def test_falls_back_to_candidate_fields(self):
        details = {"id": 1, "title": "", "original_title": "",
                   "release_date": "", "overview": "", "poster_path": None,
                   "credits": {"crew": []}}
        tmdb = FakeTMDB(details_by_id={(1, "ko-KR"): details})
        cand = MovieCandidate(title="Some Film", year=2020, tmdb_id=1,
                              original_title="Some Film", overview="후보 개요",
                              poster_url="https://image.tmdb.org/t/p/w342/c.jpg")
        movie = confirm_movie(cand, tmdb)
        assert movie.title == "Some Film"
        assert movie.year == 2020
        assert movie.overview == "후보 개요"
        assert movie.poster_url == "https://image.tmdb.org/t/p/w342/c.jpg"
        assert movie.director is None