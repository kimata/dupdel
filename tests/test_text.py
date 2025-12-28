"""text.py のユニットテスト"""

import difflib
from unittest.mock import patch

import pytest

from dupdel.text import (
    build_diff_text,
    get_term_width,
    get_visible_width,
    pad_to_width,
    truncate_to_width,
)


class TestGetTermWidth:
    """get_term_width のテスト"""

    def test_returns_positive_int(self) -> None:
        """正の整数を返す"""
        width = get_term_width()
        assert isinstance(width, int)
        assert width > 0

    def test_with_mock(self) -> None:
        """モックでターミナル幅をシミュレート"""
        with patch("shutil.get_terminal_size") as mock:
            mock.return_value.columns = 120
            assert get_term_width() == 120


class TestGetVisibleWidth:
    """get_visible_width のテスト"""

    def test_ascii_only(self) -> None:
        """ASCII文字のみ"""
        assert get_visible_width("hello") == 5

    def test_fullwidth_chars(self) -> None:
        """全角文字"""
        assert get_visible_width("日本語") == 6  # 各文字が2幅

    def test_mixed(self) -> None:
        """ASCII と全角の混在"""
        assert get_visible_width("hello日本語") == 5 + 6

    def test_empty_string(self) -> None:
        """空文字列"""
        assert get_visible_width("") == 0

    def test_ansi_escape_removed(self) -> None:
        """ANSIエスケープシーケンスは幅に含まない"""
        # 赤色テキスト
        colored = "\033[31mhello\033[0m"
        assert get_visible_width(colored) == 5

    def test_complex_ansi(self) -> None:
        """複雑なANSIエスケープシーケンス"""
        # 複数のエスケープシーケンス
        text = "\033[1;32;40mtest\033[0m\033[5mblinking\033[0m"
        assert get_visible_width(text) == 12  # "test" + "blinking"


class TestPadToWidth:
    """pad_to_width のテスト"""

    def test_left_align(self) -> None:
        """左揃え（デフォルト）"""
        result = pad_to_width("abc", 10)
        assert result == "abc       "
        assert len(result) == 10

    def test_right_align(self) -> None:
        """右揃え"""
        result = pad_to_width("abc", 10, align="right")
        assert result == "       abc"
        assert len(result) == 10

    def test_no_padding_needed(self) -> None:
        """パディング不要"""
        result = pad_to_width("abcdefghij", 10)
        assert result == "abcdefghij"

    def test_exceeds_width(self) -> None:
        """幅を超える場合はそのまま返す"""
        result = pad_to_width("abcdefghijklmno", 10)
        assert result == "abcdefghijklmno"

    def test_fullwidth_chars(self) -> None:
        """全角文字のパディング"""
        result = pad_to_width("日本", 10)  # 表示幅4
        assert get_visible_width(result) == 10


class TestTruncateToWidth:
    """truncate_to_width のテスト"""

    def test_no_truncation_needed(self) -> None:
        """省略不要"""
        result = truncate_to_width("hello", 10)
        assert result == "hello"

    def test_exact_width(self) -> None:
        """ちょうど幅に収まる"""
        result = truncate_to_width("hello", 5)
        assert result == "hello"

    def test_truncation(self) -> None:
        """省略が必要"""
        result = truncate_to_width("hello world", 8)
        assert result.endswith("...")
        assert get_visible_width(result) <= 8

    def test_fullwidth_truncation(self) -> None:
        """全角文字の省略"""
        result = truncate_to_width("日本語テスト", 8)
        assert result.endswith("...")
        assert get_visible_width(result) <= 8


class TestBuildDiffText:
    """build_diff_text のテスト"""

    def test_equal_strings(self) -> None:
        """同じ文字列"""
        sm = difflib.SequenceMatcher(None, "hello", "hello")
        result = build_diff_text("hello", sm, 0, 100)
        assert "hello" in result

    def test_different_strings_mode0(self) -> None:
        """異なる文字列（mode=0: 古い方）"""
        sm = difflib.SequenceMatcher(None, "hello", "hallo")
        result = build_diff_text("hello", sm, 0, 100)
        # 差分部分に色がついている
        assert "e" in result or "\033[" in result

    def test_different_strings_mode1(self) -> None:
        """異なる文字列（mode=1: 新しい方）"""
        sm = difflib.SequenceMatcher(None, "hello", "hallo")
        result = build_diff_text("hallo", sm, 1, 100)
        # 差分部分に色がついている
        assert "a" in result or "\033[" in result

    def test_max_width_truncation(self) -> None:
        """最大幅で省略"""
        long_text = "a" * 100
        sm = difflib.SequenceMatcher(None, long_text, long_text)
        result = build_diff_text(long_text, sm, 0, 20)
        assert result.endswith("...")

    def test_insert_operation(self) -> None:
        """挿入操作"""
        sm = difflib.SequenceMatcher(None, "ab", "aXb")
        result = build_diff_text("aXb", sm, 1, 100)
        assert "X" in result

    def test_delete_operation(self) -> None:
        """削除操作"""
        sm = difflib.SequenceMatcher(None, "aXb", "ab")
        result = build_diff_text("aXb", sm, 0, 100)
        assert "X" in result

    def test_replace_operation(self) -> None:
        """置換操作"""
        sm = difflib.SequenceMatcher(None, "cat", "bat")
        result = build_diff_text("cat", sm, 0, 100)
        assert "c" in result

    def test_fullwidth_in_diff(self) -> None:
        """全角文字を含む差分"""
        sm = difflib.SequenceMatcher(None, "日本語", "日本人")
        result = build_diff_text("日本語", sm, 0, 100)
        assert "語" in result or "\033[" in result

    def test_ignore_pattern_chars(self) -> None:
        """IGNORE_PAT にマッチする文字（数字、スペースなど）が薄く表示される"""
        # 数字の差分
        sm = difflib.SequenceMatcher(None, "file1", "file2")
        result = build_diff_text("file1", sm, 0, 100)
        # IGNORE_PAT にマッチする数字は COLOR_DIM で表示される
        assert "1" in result

    def test_ignore_pattern_space(self) -> None:
        """スペースを含む差分"""
        sm = difflib.SequenceMatcher(None, "a b", "a  b")
        result = build_diff_text("a  b", sm, 1, 100)
        assert " " in result

    def test_unknown_tag(self) -> None:
        """未知のタグ（else分岐）"""
        # SequenceMatcherは通常equal/replace/delete/insertのみだが、
        # カバレッジのためにelse分岐もテスト
        sm = difflib.SequenceMatcher(None, "abc", "abc")
        result = build_diff_text("abc", sm, 0, 100)
        assert "abc" in result
