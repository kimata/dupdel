#!/usr/bin/env python3
"""
core.py のユニットテスト
"""
# ruff: noqa: S101

import pytest

from dupdel.core import (
    expand_to_digit_group,
    find_digit_group_in_range,
    has_episode_number_diff,
    has_zengo_diff,
)


class TestExpandToDigitGroup:
    """expand_to_digit_group のテスト"""

    def test_single_digit(self):
        """単一の数字"""
        name = "test1file"
        start, end = expand_to_digit_group(name, 4, 5)
        assert name[start:end] == "1"

    def test_multiple_digits(self):
        """複数桁の数字"""
        name = "test123file"
        start, end = expand_to_digit_group(name, 5, 6)
        assert name[start:end] == "123"

    def test_no_expansion_needed(self):
        """拡張不要な場合"""
        name = "a1b"
        start, end = expand_to_digit_group(name, 1, 2)
        assert name[start:end] == "1"


class TestFindDigitGroupInRange:
    """find_digit_group_in_range のテスト"""

    def test_digit_in_range(self):
        """範囲内に数字がある場合"""
        name = "test123file"
        result = find_digit_group_in_range(name, 4, 7)
        assert result is not None
        assert name[result[0] : result[1]] == "123"

    def test_no_digit_in_range(self):
        """範囲内に数字がない場合"""
        name = "testfile"
        result = find_digit_group_in_range(name, 0, 4)
        assert result is None

    def test_digit_with_space(self):
        """数字とスペースが混在する範囲"""
        name = "#2 (test)"
        result = find_digit_group_in_range(name, 1, 3)
        assert result is not None
        assert name[result[0] : result[1]] == "2"


class TestHasZengoDiff:
    """has_zengo_diff のテスト"""

    def test_zengo_diff_mae_ato(self):
        """「前」と「後」の差分"""
        assert has_zengo_diff("番組名 前編", "番組名 後編") is True

    def test_zengo_diff_ato_mae(self):
        """「後」と「前」の差分（逆順）"""
        assert has_zengo_diff("番組名 後編", "番組名 前編") is True

    def test_no_zengo_diff(self):
        """前後の差分なし"""
        assert has_zengo_diff("番組名 第1話", "番組名 第2話") is False


class TestHasEpisodeNumberDiff:
    """has_episode_number_diff のテスト"""

    def test_single_digit_episode(self):
        """1桁のエピソード番号差分"""
        name1 = "番組名 #1_200101.ts"
        name2 = "番組名 #2_200101.ts"
        assert has_episode_number_diff(name1, name2) is True

    def test_double_digit_episode(self):
        """2桁のエピソード番号差分"""
        name1 = "番組名（10）内容_250716_2130.ts"
        name2 = "番組名（11）内容_250716_2130.ts"
        assert has_episode_number_diff(name1, name2) is True

    def test_date_diff_not_episode(self):
        """日付差分はエピソードではない"""
        name1 = "番組名_250716_2130.ts"
        name2 = "番組名_250723_1215.ts"
        assert has_episode_number_diff(name1, name2) is False

    def test_triple_digit_not_episode(self):
        """3桁以上はエピソードではない"""
        name1 = "番組名_100_内容.ts"
        name2 = "番組名_101_内容.ts"
        assert has_episode_number_diff(name1, name2) is False

    def test_delete_digit_episode(self):
        """数字削除（#11 → #1）"""
        name1 = "[終]番組名 #11[字]_200816_1950.ts"
        name2 = "[新]番組名 #1[字]_201103_0100.ts"
        assert has_episode_number_diff(name1, name2) is True

    def test_insert_digit_episode(self):
        """数字挿入（#1 → #11）"""
        name1 = "[新]番組名 #1[字]_201103_0100.ts"
        name2 = "[終]番組名 #11[字]_200816_1950.ts"
        assert has_episode_number_diff(name1, name2) is True

    def test_episode_with_space_diff(self):
        """スペースの有無がある場合（#2  → #3）"""
        name1 = "[初]Fleabag #2 (字幕版)_200706_2330.ts"
        name2 = "[初]Fleabag #3(字幕版)_200707_0000.ts"
        assert has_episode_number_diff(name1, name2) is True

    def test_same_episode(self):
        """同じエピソード番号（日付のみ異なる）"""
        name1 = "番組名（３）タイムマシン_250716_2130.ts"
        name2 = "番組名（３）タイムマシン_250723_1215.ts"
        assert has_episode_number_diff(name1, name2) is False
