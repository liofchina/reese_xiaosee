"""
tests/test_models.py — Pydantic 数据模型校验测试
"""

import pytest
from pydantic import ValidationError

from models.novel import WebNovelRequest


class TestWebNovelRequest:
    def test_valid_request(self):
        req = WebNovelRequest(
            genre="玄幻",
            core_pleasure="逆袭打脸",
            protagonist_name="林逸",
            protagonist_background="废材少年",
            golden_finger="万界交易系统",
        )
        assert req.genre == "玄幻"
        assert req.mode == "bounded"
        assert req.num_volumes == 3
        assert req.quality_mode == "standard"
        assert req.interactive is False

    def test_defaults(self):
        req = WebNovelRequest(
            genre="修仙",
            core_pleasure="升级爽",
            protagonist_name="陈平安",
            protagonist_background="穿越",
            golden_finger="系统",
        )
        assert req.chapters_per_volume == 10
        assert req.words_per_chapter == 2000
        assert req.disciplines == []

    def test_min_chapters_per_volume(self):
        with pytest.raises(ValidationError):
            WebNovelRequest(
                genre="玄幻",
                core_pleasure="逆袭打脸",
                protagonist_name="林逸",
                protagonist_background="废材",
                golden_finger="系统",
                chapters_per_volume=2,  # min is 5
            )

    def test_max_chapters_per_volume(self):
        with pytest.raises(ValidationError):
            WebNovelRequest(
                genre="玄幻",
                core_pleasure="逆袭打脸",
                protagonist_name="林逸",
                protagonist_background="废材",
                golden_finger="系统",
                chapters_per_volume=50,  # max is 30
            )

    def test_words_per_chapter_range(self):
        with pytest.raises(ValidationError):
            WebNovelRequest(
                genre="玄幻",
                core_pleasure="逆袭打脸",
                protagonist_name="林逸",
                protagonist_background="废材",
                golden_finger="系统",
                words_per_chapter=500,  # min is 1000
            )

    def test_required_fields(self):
        with pytest.raises(ValidationError):
            WebNovelRequest(genre="玄幻")  # missing required fields
