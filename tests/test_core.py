#!/usr/bin/env python3
"""
core.py のユニットテスト
"""
# ruff: noqa: S101

import os
import tempfile
from unittest.mock import patch

import pytest

from dupdel.core import (
    PrecomputedFileInfo,
    _compare_pair,
    count_valid_comparisons,
    expand_to_digit_group,
    find_digit_group_in_range,
    find_dup_candidates_parallel,
    get_mtime_safe,
    has_episode_number_diff,
    has_zengo_diff,
    list_files,
    precompute_file_info,
    sort_files_by_mtime,
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

    def test_replace_no_digit_in_name2(self):
        """replaceタグでname2側に数字がない場合"""
        # name1側には数字があるがname2側にはない
        name1 = "番組1話.ts"
        name2 = "番組X話.ts"
        assert has_episode_number_diff(name1, name2) is False

    def test_replace_group_none(self):
        """replaceタグで数字グループが範囲外"""
        # 差分位置に数字があるが、find_digit_group_in_rangeがNoneを返すケース
        # これは実際には起きにくいが、コード上のパスをテスト
        name1 = "test.ts"
        name2 = "TEST.ts"
        assert has_episode_number_diff(name1, name2) is False

    def test_delete_no_digit(self):
        """deleteタグで削除部分に数字がない場合"""
        name1 = "番組ABC内容.ts"
        name2 = "番組内容.ts"
        assert has_episode_number_diff(name1, name2) is False

    def test_insert_no_digit(self):
        """insertタグで挿入部分に数字がない場合"""
        name1 = "番組内容.ts"
        name2 = "番組ABC内容.ts"
        assert has_episode_number_diff(name1, name2) is False

    def test_three_digit_insert(self):
        """3桁以上の数字挿入はエピソードではない"""
        name1 = "番組#1.ts"
        name2 = "番組#100.ts"
        assert has_episode_number_diff(name1, name2) is False

    def test_three_digit_delete(self):
        """3桁以上の数字削除はエピソードではない"""
        name1 = "番組#100.ts"
        name2 = "番組#1.ts"
        assert has_episode_number_diff(name1, name2) is False


class TestCountValidComparisons:
    """count_valid_comparisons のテスト"""

    def test_same_directory(self):
        """同じディレクトリのファイル"""
        infos = [
            PrecomputedFileInfo(
                path="/dir/file1.txt",
                dir_path="/dir",
                name="file1.txt",
                rel_name="file1.txt",
                normalized="file1.txt",
                size=100,
                mtime=1000.0,
                index=1,
            ),
            PrecomputedFileInfo(
                path="/dir/file2.txt",
                dir_path="/dir",
                name="file2.txt",
                rel_name="file2.txt",
                normalized="file2.txt",
                size=100,
                mtime=1001.0,
                index=2,
            ),
            PrecomputedFileInfo(
                path="/dir/file3.txt",
                dir_path="/dir",
                name="file3.txt",
                rel_name="file3.txt",
                normalized="file3.txt",
                size=100,
                mtime=1002.0,
                index=3,
            ),
        ]
        # 3ファイル: 3*(3-1)/2 = 3 ペア
        assert count_valid_comparisons(infos) == 3

    def test_different_directories(self):
        """異なるディレクトリのファイル"""
        infos = [
            PrecomputedFileInfo(
                path="/dir1/file1.txt",
                dir_path="/dir1",
                name="file1.txt",
                rel_name="file1.txt",
                normalized="file1.txt",
                size=100,
                mtime=1000.0,
                index=1,
            ),
            PrecomputedFileInfo(
                path="/dir2/file2.txt",
                dir_path="/dir2",
                name="file2.txt",
                rel_name="file2.txt",
                normalized="file2.txt",
                size=100,
                mtime=1001.0,
                index=2,
            ),
        ]
        # 異なるディレクトリなので0ペア
        assert count_valid_comparisons(infos) == 0

    def test_empty_list(self):
        """空リスト"""
        assert count_valid_comparisons([]) == 0


class TestPrecomputeFileInfo:
    """precompute_file_info のテスト"""

    def test_basic(self):
        """基本的なファイル情報計算"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # テストファイルを作成
            file1 = os.path.join(tmpdir, "test1.txt")
            file2 = os.path.join(tmpdir, "test2.txt")
            with open(file1, "w") as f:
                f.write("content1")
            with open(file2, "w") as f:
                f.write("content22")

            file_list = [file1, file2]
            result = precompute_file_info(file_list, tmpdir)

            assert len(result) == 2
            assert result[0].name == "test1.txt"
            assert result[1].name == "test2.txt"
            assert result[0].size == 8
            assert result[1].size == 9

    def test_with_progress_callback(self):
        """進捗コールバック付き"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file1 = os.path.join(tmpdir, "test.txt")
            with open(file1, "w") as f:
                f.write("content")

            progress_count = [0]

            def callback(n):
                progress_count[0] += n

            result = precompute_file_info([file1], tmpdir, callback)
            assert len(result) == 1
            assert progress_count[0] == 1

    def test_nonexistent_file(self):
        """存在しないファイル"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = precompute_file_info(["/nonexistent/file.txt"], tmpdir)
            assert len(result) == 0

    def test_shutdown_event(self):
        """シャットダウンイベント"""
        from dupdel.constants import shutdown_event

        with tempfile.TemporaryDirectory() as tmpdir:
            file1 = os.path.join(tmpdir, "test.txt")
            with open(file1, "w") as f:
                f.write("content")

            shutdown_event.set()
            try:
                result = precompute_file_info([file1], tmpdir)
                assert len(result) == 0
            finally:
                shutdown_event.clear()


class TestComparePair:
    """_compare_pair のテスト"""

    def test_similar_files(self):
        """類似ファイル"""
        info1 = PrecomputedFileInfo(
            path="/dir/file1.txt",
            dir_path="/dir",
            name="番組名_200101.ts",
            rel_name="番組名_200101.ts",
            normalized="番組名.ts",
            size=1000000,
            mtime=1000.0,
            index=1,
        )
        info2 = PrecomputedFileInfo(
            path="/dir/file2.txt",
            dir_path="/dir",
            name="番組名_200102.ts",
            rel_name="番組名_200102.ts",
            normalized="番組名.ts",
            size=1000000,
            mtime=1001.0,
            index=2,
        )
        result = _compare_pair(info1, info2, 0.85)
        assert result is not None
        assert len(result) == 2

    def test_different_files(self):
        """異なるファイル"""
        info1 = PrecomputedFileInfo(
            path="/dir/file1.txt",
            dir_path="/dir",
            name="completely_different_name.ts",
            rel_name="completely_different_name.ts",
            normalized="completelydifferentname.ts",
            size=1000000,
            mtime=1000.0,
            index=1,
        )
        info2 = PrecomputedFileInfo(
            path="/dir/file2.txt",
            dir_path="/dir",
            name="another_totally_unique.ts",
            rel_name="another_totally_unique.ts",
            normalized="anothertotallyunique.ts",
            size=1000000,
            mtime=1001.0,
            index=2,
        )
        result = _compare_pair(info1, info2, 0.85)
        assert result is None

    def test_size_difference(self):
        """サイズ差が大きい"""
        info1 = PrecomputedFileInfo(
            path="/dir/file1.txt",
            dir_path="/dir",
            name="same_name.ts",
            rel_name="same_name.ts",
            normalized="samename.ts",
            size=1000000,
            mtime=1000.0,
            index=1,
        )
        info2 = PrecomputedFileInfo(
            path="/dir/file2.txt",
            dir_path="/dir",
            name="same_name.ts",
            rel_name="same_name.ts",
            normalized="samename.ts",
            size=100000,  # 10倍の差
            mtime=1001.0,
            index=2,
        )
        result = _compare_pair(info1, info2, 0.85)
        assert result is None

    def test_episode_diff(self):
        """話数差分"""
        info1 = PrecomputedFileInfo(
            path="/dir/file1.txt",
            dir_path="/dir",
            name="番組 #1.ts",
            rel_name="番組 #1.ts",
            normalized="番組 #.ts",
            size=1000000,
            mtime=1000.0,
            index=1,
        )
        info2 = PrecomputedFileInfo(
            path="/dir/file2.txt",
            dir_path="/dir",
            name="番組 #2.ts",
            rel_name="番組 #2.ts",
            normalized="番組 #.ts",
            size=1000000,
            mtime=1001.0,
            index=2,
        )
        result = _compare_pair(info1, info2, 0.85)
        assert result is None

    def test_zengo_diff(self):
        """前後差分"""
        info1 = PrecomputedFileInfo(
            path="/dir/file1.txt",
            dir_path="/dir",
            name="番組 前編.ts",
            rel_name="番組 前編.ts",
            normalized="番組 編.ts",
            size=1000000,
            mtime=1000.0,
            index=1,
        )
        info2 = PrecomputedFileInfo(
            path="/dir/file2.txt",
            dir_path="/dir",
            name="番組 後編.ts",
            rel_name="番組 後編.ts",
            normalized="番組 編.ts",
            size=1000000,
            mtime=1001.0,
            index=2,
        )
        result = _compare_pair(info1, info2, 0.85)
        assert result is None

    def test_length_ratio_filter(self):
        """長さ比率フィルタ"""
        info1 = PrecomputedFileInfo(
            path="/dir/file1.txt",
            dir_path="/dir",
            name="a.ts",
            rel_name="a.ts",
            normalized="a.ts",
            size=1000000,
            mtime=1000.0,
            index=1,
        )
        info2 = PrecomputedFileInfo(
            path="/dir/file2.txt",
            dir_path="/dir",
            name="very_very_long_name.ts",
            rel_name="very_very_long_name.ts",
            normalized="veryverylongname.ts",
            size=1000000,
            mtime=1001.0,
            index=2,
        )
        result = _compare_pair(info1, info2, 0.85)
        assert result is None

    def test_older_newer_order(self):
        """古い方が先になる"""
        info1 = PrecomputedFileInfo(
            path="/dir/file1.txt",
            dir_path="/dir",
            name="same.ts",
            rel_name="same.ts",
            normalized="same.ts",
            size=1000000,
            mtime=2000.0,  # 新しい
            index=1,
        )
        info2 = PrecomputedFileInfo(
            path="/dir/file2.txt",
            dir_path="/dir",
            name="same.ts",
            rel_name="same.ts",
            normalized="same.ts",
            size=1000000,
            mtime=1000.0,  # 古い
            index=2,
        )
        result = _compare_pair(info1, info2, 0.85)
        assert result is not None
        assert result[0]["mtime"] < result[1]["mtime"]

    def test_ratio_filter(self):
        """quick_ratioは通るがratioで落ちるケース"""
        # 文字の順序が異なるため、quick_ratioとratioの差が出やすい
        info1 = PrecomputedFileInfo(
            path="/dir/file1.txt",
            dir_path="/dir",
            name="abcdefghij.ts",
            rel_name="abcdefghij.ts",
            normalized="abcdefghij.ts",
            size=1000000,
            mtime=1000.0,
            index=1,
        )
        info2 = PrecomputedFileInfo(
            path="/dir/file2.txt",
            dir_path="/dir",
            name="jihgfedcba.ts",
            rel_name="jihgfedcba.ts",
            normalized="jihgfedcba.ts",
            size=1000000,
            mtime=1001.0,
            index=2,
        )
        # 高いしきい値で呼び出すと、quick_ratioは通ってもratioで落ちる可能性
        result = _compare_pair(info1, info2, 0.95)
        assert result is None

    def test_empty_normalized(self):
        """正規化名が空の場合"""
        info1 = PrecomputedFileInfo(
            path="/dir/file1.txt",
            dir_path="/dir",
            name="____.ts",
            rel_name="____.ts",
            normalized="",
            size=1000000,
            mtime=1000.0,
            index=1,
        )
        info2 = PrecomputedFileInfo(
            path="/dir/file2.txt",
            dir_path="/dir",
            name="____.ts",
            rel_name="____.ts",
            normalized="",
            size=1000000,
            mtime=1001.0,
            index=2,
        )
        result = _compare_pair(info1, info2, 0.85)
        # 空文字の場合でも比較は行われる
        assert result is not None


class TestGetMtimeSafe:
    """get_mtime_safe のテスト"""

    def test_existing_file(self):
        """存在するファイル"""
        with tempfile.NamedTemporaryFile() as f:
            mtime = get_mtime_safe(f.name)
            assert mtime > 0

    def test_nonexistent_file(self):
        """存在しないファイル"""
        mtime = get_mtime_safe("/nonexistent/file.txt")
        assert mtime == 0


class TestListFiles:
    """list_files のテスト"""

    def test_basic(self):
        """基本的なファイル一覧"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # テストファイルを作成
            file1 = os.path.join(tmpdir, "test1.txt")
            file2 = os.path.join(tmpdir, "test2.txt")
            with open(file1, "w") as f:
                f.write("content1")
            with open(file2, "w") as f:
                f.write("content2")

            result = list_files(tmpdir)
            assert len(result) == 2

    def test_hidden_files_excluded(self):
        """隠しファイルは除外"""
        with tempfile.TemporaryDirectory() as tmpdir:
            visible = os.path.join(tmpdir, "visible.txt")
            hidden = os.path.join(tmpdir, ".hidden.txt")
            with open(visible, "w") as f:
                f.write("content")
            with open(hidden, "w") as f:
                f.write("content")

            result = list_files(tmpdir)
            assert len(result) == 1
            assert "visible.txt" in result[0]

    def test_hidden_directories_excluded(self):
        """隠しディレクトリは除外"""
        with tempfile.TemporaryDirectory() as tmpdir:
            hidden_dir = os.path.join(tmpdir, ".hidden_dir")
            os.makedirs(hidden_dir)
            hidden_file = os.path.join(hidden_dir, "file.txt")
            with open(hidden_file, "w") as f:
                f.write("content")

            result = list_files(tmpdir)
            assert len(result) == 0

    def test_subdirectories(self):
        """サブディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = os.path.join(tmpdir, "subdir")
            os.makedirs(subdir)
            file1 = os.path.join(tmpdir, "root.txt")
            file2 = os.path.join(subdir, "sub.txt")
            with open(file1, "w") as f:
                f.write("content")
            with open(file2, "w") as f:
                f.write("content")

            result = list_files(tmpdir)
            assert len(result) == 2

    def test_with_progress_callback(self):
        """進捗コールバック付き"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file1 = os.path.join(tmpdir, "test.txt")
            with open(file1, "w") as f:
                f.write("content")

            progress_count = [0]

            def callback(n):
                progress_count[0] += n

            result = list_files(tmpdir, callback)
            assert len(result) == 1
            assert progress_count[0] == 1

    def test_shutdown_event(self):
        """シャットダウンイベント"""
        from dupdel.constants import shutdown_event

        with tempfile.TemporaryDirectory() as tmpdir:
            file1 = os.path.join(tmpdir, "test.txt")
            with open(file1, "w") as f:
                f.write("content")

            shutdown_event.set()
            try:
                result = list_files(tmpdir)
                assert len(result) == 0
            finally:
                shutdown_event.clear()

    def test_shutdown_event_in_files_loop(self):
        """ファイルループ中のシャットダウンイベント"""
        from dupdel.constants import shutdown_event

        with tempfile.TemporaryDirectory() as tmpdir:
            # 複数ファイルを作成
            for i in range(5):
                with open(os.path.join(tmpdir, f"test{i}.txt"), "w") as f:
                    f.write("content")

            call_count = [0]

            def callback_with_shutdown(n):
                call_count[0] += 1
                if call_count[0] >= 2:
                    shutdown_event.set()

            try:
                result = list_files(tmpdir, callback_with_shutdown)
                # シャットダウンにより途中で停止
                assert len(result) < 5
            finally:
                shutdown_event.clear()

    def test_oserror_on_isfile(self):
        """os.path.isfileでOSError"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file1 = os.path.join(tmpdir, "test.txt")
            with open(file1, "w") as f:
                f.write("content")

            with patch("os.path.isfile", side_effect=OSError("Permission denied")):
                result = list_files(tmpdir)
                assert len(result) == 0


class TestSortFilesByMtime:
    """sort_files_by_mtime のテスト"""

    def test_sorting(self):
        """更新時刻でソート"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file1 = os.path.join(tmpdir, "first.txt")
            file2 = os.path.join(tmpdir, "second.txt")

            with open(file1, "w") as f:
                f.write("content")
            import time

            time.sleep(0.01)
            with open(file2, "w") as f:
                f.write("content")

            result = sort_files_by_mtime([file2, file1])
            assert "first.txt" in result[0]
            assert "second.txt" in result[1]


class TestFindDupCandidatesParallel:
    """find_dup_candidates_parallel のテスト"""

    def test_empty_list(self):
        """空リスト"""
        result = find_dup_candidates_parallel([], lambda c, f: None, 1)
        assert result == []

    def test_single_file(self):
        """1ファイルのみ"""
        infos = [
            PrecomputedFileInfo(
                path="/dir/file1.txt",
                dir_path="/dir",
                name="file1.txt",
                rel_name="file1.txt",
                normalized="file1.txt",
                size=100,
                mtime=1000.0,
                index=1,
            )
        ]
        result = find_dup_candidates_parallel(infos, lambda c, f: None, 1)
        assert result == []

    def test_find_duplicates(self):
        """重複を見つける"""
        infos = [
            PrecomputedFileInfo(
                path="/dir/番組名_200101.ts",
                dir_path="/dir",
                name="番組名_200101.ts",
                rel_name="番組名_200101.ts",
                normalized="番組名.ts",
                size=1000000,
                mtime=1000.0,
                index=1,
            ),
            PrecomputedFileInfo(
                path="/dir/番組名_200102.ts",
                dir_path="/dir",
                name="番組名_200102.ts",
                rel_name="番組名_200102.ts",
                normalized="番組名.ts",
                size=1000000,
                mtime=1001.0,
                index=2,
            ),
        ]
        comparisons = [0]
        found = [0]

        def callback(c, f):
            comparisons[0] += c
            found[0] += f

        result = find_dup_candidates_parallel(infos, callback, 1)
        assert len(result) == 1
        assert comparisons[0] >= 1

    def test_default_num_workers(self):
        """num_workersがNoneの場合"""
        infos = [
            PrecomputedFileInfo(
                path="/dir/番組名_200101.ts",
                dir_path="/dir",
                name="番組名_200101.ts",
                rel_name="番組名_200101.ts",
                normalized="番組名.ts",
                size=1000000,
                mtime=1000.0,
                index=1,
            ),
            PrecomputedFileInfo(
                path="/dir/番組名_200102.ts",
                dir_path="/dir",
                name="番組名_200102.ts",
                rel_name="番組名_200102.ts",
                normalized="番組名.ts",
                size=1000000,
                mtime=1001.0,
                index=2,
            ),
        ]
        # num_workers=Noneでデフォルト値を使用
        result = find_dup_candidates_parallel(infos, lambda c, f: None)
        assert len(result) == 1
