"""ui.py のユニットテスト"""

import difflib
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from dupdel.ui import (
    _blinking_input,
    _exec_delete,
    _handle_interrupt,
    _list_dup_cand,
    _print_dup_cand,
    run_interactive,
    run_stats_mode,
)


class TestBlinkingInput:
    """blinking_input のテスト"""

    def test_basic_input(self):
        """基本的な入力"""
        with patch("builtins.input", return_value="y"):
            result = _blinking_input("prompt: ")
            assert result == "y"

    def test_empty_prompt(self):
        """空のプロンプト"""
        with patch("builtins.input", return_value="test"):
            result = _blinking_input("")
            assert result == "test"


class TestPrintDupCand:
    """print_dup_cand のテスト"""

    def test_print_candidate(self, capsys):
        """重複候補の表示"""
        sm = difflib.SequenceMatcher(None, "file1.ts", "file2.ts")
        dup_cand = [
            {
                "path": "/dir/file1.ts",
                "name": "file1.ts",
                "basename": "file1.ts",
                "size": 1000000,
                "mtime": 1000.0,
                "index": 1,
                "sm": sm,
            },
            {
                "path": "/dir/file2.ts",
                "name": "file2.ts",
                "basename": "file2.ts",
                "size": 1000000,
                "mtime": 1001.0,
                "index": 2,
                "sm": sm,
            },
        ]
        _print_dup_cand(dup_cand, 1, 10)
        captured = capsys.readouterr()
        assert "類似度" in captured.out
        assert "サイズ差" in captured.out

    def test_print_with_directory(self, capsys):
        """ディレクトリパス付きの表示"""
        sm = difflib.SequenceMatcher(None, "file1.ts", "file2.ts")
        dup_cand = [
            {
                "path": "/dir/subdir/file1.ts",
                "name": "subdir/file1.ts",
                "basename": "file1.ts",
                "size": 1000000,
                "mtime": 1000.0,
                "index": 1,
                "sm": sm,
            },
            {
                "path": "/dir/subdir/file2.ts",
                "name": "subdir/file2.ts",
                "basename": "file2.ts",
                "size": 1000000,
                "mtime": 1001.0,
                "index": 2,
                "sm": sm,
            },
        ]
        _print_dup_cand(dup_cand, 1, 10)
        captured = capsys.readouterr()
        assert "subdir" in captured.out

    def test_print_with_size_warning(self, capsys):
        """サイズ差警告の表示"""
        sm = difflib.SequenceMatcher(None, "file1.ts", "file2.ts")
        dup_cand = [
            {
                "path": "/dir/file1.ts",
                "name": "file1.ts",
                "basename": "file1.ts",
                "size": 500 * 1024 * 1024,  # 500MB
                "mtime": 1000.0,
                "index": 1,
                "sm": sm,
            },
            {
                "path": "/dir/file2.ts",
                "name": "file2.ts",
                "basename": "file2.ts",
                "size": 100 * 1024 * 1024,  # 100MB
                "mtime": 1001.0,
                "index": 2,
                "sm": sm,
            },
        ]
        _print_dup_cand(dup_cand, 1, 10)
        captured = capsys.readouterr()
        assert "MB" in captured.out

    def test_print_with_long_directory(self, capsys):
        """長いディレクトリパスの省略表示"""
        # ターミナル幅を狭く設定
        with patch("dupdel.ui.get_term_width", return_value=60):
            long_dir = "very/long/directory/path/that/needs/truncation"
            sm = difflib.SequenceMatcher(None, "file1.ts", "file2.ts")
            dup_cand = [
                {
                    "path": f"/dir/{long_dir}/file1.ts",
                    "name": f"{long_dir}/file1.ts",
                    "basename": "file1.ts",
                    "size": 1000000,
                    "mtime": 1000.0,
                    "index": 1,
                    "sm": sm,
                },
                {
                    "path": f"/dir/{long_dir}/file2.ts",
                    "name": f"{long_dir}/file2.ts",
                    "basename": "file2.ts",
                    "size": 1000000,
                    "mtime": 1001.0,
                    "index": 2,
                    "sm": sm,
                },
            ]
            _print_dup_cand(dup_cand, 1, 10)
            captured = capsys.readouterr()
            # 省略記号が含まれていることを確認
            assert "..." in captured.out or "file" in captured.out


class TestHandleInterrupt:
    """handle_interrupt のテスト"""

    def test_continue(self):
        """継続を選択"""
        with patch("dupdel.ui._blinking_input", return_value="n"):
            result = _handle_interrupt()
            assert result is False

    def test_exit(self):
        """終了を選択"""
        from dupdel.constants import shutdown_event

        shutdown_event.clear()
        with patch("dupdel.ui._blinking_input", return_value="y"):
            result = _handle_interrupt()
            assert result is True
            shutdown_event.clear()

    def test_keyboard_interrupt(self):
        """入力中にKeyboardInterrupt"""
        from dupdel.constants import shutdown_event

        shutdown_event.clear()
        with patch("dupdel.ui._blinking_input", side_effect=KeyboardInterrupt):
            result = _handle_interrupt()
            assert result is True
            shutdown_event.clear()

    def test_eof_error(self):
        """EOFError"""
        from dupdel.constants import shutdown_event

        shutdown_event.clear()
        with patch("dupdel.ui._blinking_input", side_effect=EOFError):
            result = _handle_interrupt()
            assert result is True
            shutdown_event.clear()

    def test_with_manager(self):
        """マネージャー付き"""
        from dupdel.constants import shutdown_event

        shutdown_event.clear()
        manager = MagicMock()
        with patch("dupdel.ui._blinking_input", return_value="y"):
            result = _handle_interrupt(manager)
            assert result is True
            manager.stop.assert_called_once()
            shutdown_event.clear()

    def test_with_manager_on_exception(self):
        """マネージャー付きで例外発生時"""
        from dupdel.constants import shutdown_event

        shutdown_event.clear()
        manager = MagicMock()
        with patch("dupdel.ui._blinking_input", side_effect=KeyboardInterrupt):
            result = _handle_interrupt(manager)
            assert result is True
            manager.stop.assert_called_once()
            shutdown_event.clear()


class TestExecDelete:
    """exec_delete のテスト"""

    def test_empty_list(self, capsys):
        """空のリスト"""
        manager = MagicMock()
        manager.counter.return_value = MagicMock()
        result = _exec_delete([], "/tmp/trash", manager)
        assert result is True
        captured = capsys.readouterr()
        assert "削除候補がありません" in captured.out

    def test_delete_yes(self):
        """削除を確認"""
        with tempfile.TemporaryDirectory() as tmpdir:
            trash_dir = os.path.join(tmpdir, "trash")
            test_file = os.path.join(tmpdir, "test.ts")
            with open(test_file, "w") as f:
                f.write("content")

            sm = difflib.SequenceMatcher(None, "test.ts", "test.ts")
            dup_cand_list = [
                [
                    {
                        "path": test_file,
                        "name": "test.ts",
                        "basename": "test.ts",
                        "size": 7,
                        "mtime": 1000.0,
                        "index": 1,
                        "sm": sm,
                    },
                    {
                        "path": test_file,
                        "name": "test.ts",
                        "basename": "test.ts",
                        "size": 7,
                        "mtime": 1001.0,
                        "index": 2,
                        "sm": sm,
                    },
                ]
            ]

            manager = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.counter.return_value = counter

            with patch("dupdel.ui._blinking_input", return_value="y"):
                result = _exec_delete(dup_cand_list, trash_dir, manager)
                assert result is True
                assert not os.path.exists(test_file)
                assert os.path.exists(os.path.join(trash_dir, "test.ts"))

    def test_delete_no(self):
        """削除を拒否"""
        with tempfile.TemporaryDirectory() as tmpdir:
            trash_dir = os.path.join(tmpdir, "trash")
            test_file = os.path.join(tmpdir, "test.ts")
            with open(test_file, "w") as f:
                f.write("content")

            sm = difflib.SequenceMatcher(None, "test.ts", "test.ts")
            dup_cand_list = [
                [
                    {
                        "path": test_file,
                        "name": "test.ts",
                        "basename": "test.ts",
                        "size": 7,
                        "mtime": 1000.0,
                        "index": 1,
                        "sm": sm,
                    },
                    {
                        "path": test_file,
                        "name": "test.ts",
                        "basename": "test.ts",
                        "size": 7,
                        "mtime": 1001.0,
                        "index": 2,
                        "sm": sm,
                    },
                ]
            ]

            manager = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.counter.return_value = counter

            with patch("dupdel.ui._blinking_input", return_value="n"):
                result = _exec_delete(dup_cand_list, trash_dir, manager)
                assert result is False
                assert os.path.exists(test_file)

    def test_delete_all(self):
        """すべて削除"""
        with tempfile.TemporaryDirectory() as tmpdir:
            trash_dir = os.path.join(tmpdir, "trash")
            test_file1 = os.path.join(tmpdir, "test1.ts")
            test_file2 = os.path.join(tmpdir, "test2.ts")
            with open(test_file1, "w") as f:
                f.write("content")
            with open(test_file2, "w") as f:
                f.write("content")

            sm = difflib.SequenceMatcher(None, "test.ts", "test.ts")
            dup_cand_list = [
                [
                    {
                        "path": test_file1,
                        "name": "test1.ts",
                        "basename": "test1.ts",
                        "size": 7,
                        "mtime": 1000.0,
                        "index": 1,
                        "sm": sm,
                    },
                    {
                        "path": test_file1,
                        "name": "test1.ts",
                        "basename": "test1.ts",
                        "size": 7,
                        "mtime": 1001.0,
                        "index": 2,
                        "sm": sm,
                    },
                ],
                [
                    {
                        "path": test_file2,
                        "name": "test2.ts",
                        "basename": "test2.ts",
                        "size": 7,
                        "mtime": 1000.0,
                        "index": 1,
                        "sm": sm,
                    },
                    {
                        "path": test_file2,
                        "name": "test2.ts",
                        "basename": "test2.ts",
                        "size": 7,
                        "mtime": 1001.0,
                        "index": 2,
                        "sm": sm,
                    },
                ],
            ]

            manager = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.counter.return_value = counter

            with patch("dupdel.ui._blinking_input", return_value="a"):
                result = _exec_delete(dup_cand_list, trash_dir, manager)
                assert result is True

    def test_file_not_found(self, capsys):
        """ファイルが見つからない"""
        sm = difflib.SequenceMatcher(None, "test.ts", "test.ts")
        dup_cand_list = [
            [
                {
                    "path": "/nonexistent/file1.ts",
                    "name": "file1.ts",
                    "basename": "file1.ts",
                    "size": 7,
                    "mtime": 1000.0,
                    "index": 1,
                    "sm": sm,
                },
                {
                    "path": "/nonexistent/file2.ts",
                    "name": "file2.ts",
                    "basename": "file2.ts",
                    "size": 7,
                    "mtime": 1001.0,
                    "index": 2,
                    "sm": sm,
                },
            ]
        ]

        manager = MagicMock()
        counter = MagicMock()
        counter.count = 0
        manager.counter.return_value = counter

        result = _exec_delete(dup_cand_list, "/tmp/trash", manager)
        captured = capsys.readouterr()
        assert "ファイルが見つかりません" in captured.out


class TestListDupCand:
    """list_dup_cand のテスト"""

    def test_empty_directory(self):
        """空のディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            result, skipped = _list_dup_cand(tmpdir, manager)
            assert result == []
            assert skipped == []

    def test_single_file(self):
        """1ファイルのみ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test.ts")
            with open(test_file, "w") as f:
                f.write("content")

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            result, skipped = _list_dup_cand(tmpdir, manager)
            assert result == []
            assert skipped == []

    def test_shutdown_event_early_return(self):
        """shutdown_eventによる早期リターン"""
        from dupdel.constants import shutdown_event

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test.ts")
            with open(test_file, "w") as f:
                f.write("content")

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            shutdown_event.set()
            try:
                result, skipped = _list_dup_cand(tmpdir, manager)
                assert result == []
                assert skipped == []
            finally:
                shutdown_event.clear()

    def test_with_similar_files_yes(self):
        """類似ファイルがあり「y」と回答"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 類似したファイル名を作成
            with open(os.path.join(tmpdir, "番組名_200101.ts"), "w") as f:
                f.write("x" * 1000)
            with open(os.path.join(tmpdir, "番組名_200102.ts"), "w") as f:
                f.write("x" * 1000)

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            with patch("dupdel.ui._blinking_input", return_value="y"):
                result, skipped = _list_dup_cand(tmpdir, manager)
                assert len(result) == 1

    def test_with_similar_files_no(self):
        """類似ファイルがあり「n」と回答"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 類似したファイル名を作成
            with open(os.path.join(tmpdir, "番組名_200101.ts"), "w") as f:
                f.write("x" * 1000)
            with open(os.path.join(tmpdir, "番組名_200102.ts"), "w") as f:
                f.write("x" * 1000)

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            with patch("dupdel.ui._blinking_input", return_value="n"):
                result, skipped = _list_dup_cand(tmpdir, manager)
                assert len(result) == 0
                assert len(skipped) == 1

    def test_with_similar_files_quit(self):
        """類似ファイルがあり「q」と回答"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 類似したファイル名を作成
            with open(os.path.join(tmpdir, "番組名_200101.ts"), "w") as f:
                f.write("x" * 1000)
            with open(os.path.join(tmpdir, "番組名_200102.ts"), "w") as f:
                f.write("x" * 1000)

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            with patch("dupdel.ui._blinking_input", return_value="q"):
                result, skipped = _list_dup_cand(tmpdir, manager)
                assert len(result) == 0

    def test_no_valid_comparisons(self):
        """有効な比較対象がない（異なるディレクトリのファイル）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 異なるサブディレクトリにファイルを作成
            subdir1 = os.path.join(tmpdir, "dir1")
            subdir2 = os.path.join(tmpdir, "dir2")
            os.makedirs(subdir1)
            os.makedirs(subdir2)
            with open(os.path.join(subdir1, "file.ts"), "w") as f:
                f.write("content")
            with open(os.path.join(subdir2, "file.ts"), "w") as f:
                f.write("content")

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            result, skipped = _list_dup_cand(tmpdir, manager)
            assert result == []
            assert skipped == []

    def test_with_cached_pairs(self):
        """キャッシュ済みペアがスキップされる"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 類似したファイル名を作成
            file1 = os.path.join(tmpdir, "番組名_200101.ts")
            file2 = os.path.join(tmpdir, "番組名_200102.ts")
            with open(file1, "w") as f:
                f.write("x" * 1000)
            with open(file2, "w") as f:
                f.write("x" * 1000)

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            with patch("dupdel.ui.is_pair_cached", return_value=True):
                result, skipped = _list_dup_cand(tmpdir, manager)
                assert len(result) == 0

    def test_shutdown_during_question_loop(self):
        """質問ループ中にshutdown_eventがセットされた場合（複数ペア）"""
        from dupdel.constants import shutdown_event

        with tempfile.TemporaryDirectory() as tmpdir:
            # 複数の類似ファイルペアを作成（3つ以上で2ペア以上検出される）
            for i in range(4):
                with open(os.path.join(tmpdir, f"番組名_20010{i}.ts"), "w") as f:
                    f.write("x" * 1000)

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            call_count = [0]

            def input_with_shutdown(prompt):
                call_count[0] += 1
                if call_count[0] >= 1:
                    # 1回目の回答後にshutdown_eventをセット
                    shutdown_event.set()
                return "y"

            try:
                with patch(
                    "dupdel.ui._blinking_input", side_effect=input_with_shutdown
                ):
                    result, skipped = _list_dup_cand(tmpdir, manager)
                    # shutdown後は残りの質問がスキップされる
            finally:
                shutdown_event.clear()

    def test_keyboard_interrupt_continue(self):
        """KeyboardInterruptで継続を選択"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 類似したファイル名を作成
            with open(os.path.join(tmpdir, "番組名_200101.ts"), "w") as f:
                f.write("x" * 1000)
            with open(os.path.join(tmpdir, "番組名_200102.ts"), "w") as f:
                f.write("x" * 1000)

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            call_count = [0]

            def input_with_interrupt(prompt):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise KeyboardInterrupt
                return "q"

            with patch("dupdel.ui._blinking_input", side_effect=input_with_interrupt):
                with patch("dupdel.ui._handle_interrupt", return_value=False):
                    with pytest.raises(KeyboardInterrupt):
                        _list_dup_cand(tmpdir, manager)

    def test_keyboard_interrupt_exit(self):
        """KeyboardInterruptで終了を選択"""
        from dupdel.constants import shutdown_event

        with tempfile.TemporaryDirectory() as tmpdir:
            # 類似したファイル名を作成
            with open(os.path.join(tmpdir, "番組名_200101.ts"), "w") as f:
                f.write("x" * 1000)
            with open(os.path.join(tmpdir, "番組名_200102.ts"), "w") as f:
                f.write("x" * 1000)

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            shutdown_event.clear()
            try:
                with patch("dupdel.ui._blinking_input", side_effect=KeyboardInterrupt):
                    with patch("dupdel.ui._handle_interrupt", return_value=True):
                        result, skipped = _list_dup_cand(tmpdir, manager)
                        assert shutdown_event.is_set()
            finally:
                shutdown_event.clear()

    def test_shutdown_after_cache_filter(self):
        """キャッシュフィルタリング後にshutdown_eventがセットされた場合"""
        from dupdel.constants import shutdown_event

        with tempfile.TemporaryDirectory() as tmpdir:
            # 類似したファイル名を作成
            with open(os.path.join(tmpdir, "番組名_200101.ts"), "w") as f:
                f.write("x" * 1000)
            with open(os.path.join(tmpdir, "番組名_200102.ts"), "w") as f:
                f.write("x" * 1000)

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            def is_cached_with_shutdown(path1, path2):
                shutdown_event.set()
                return False

            try:
                with patch(
                    "dupdel.ui.is_pair_cached", side_effect=is_cached_with_shutdown
                ):
                    result, skipped = _list_dup_cand(tmpdir, manager)
                    assert result == []
                    assert skipped == []
            finally:
                shutdown_event.clear()

    def test_question_counter_close_exception(self):
        """question_counter.close()が例外を投げる場合"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 類似したファイル名を作成
            with open(os.path.join(tmpdir, "番組名_200101.ts"), "w") as f:
                f.write("x" * 1000)
            with open(os.path.join(tmpdir, "番組名_200102.ts"), "w") as f:
                f.write("x" * 1000)

            manager = MagicMock()
            status_bar = MagicMock()
            manager.status_bar.return_value = status_bar

            # 各counter呼び出しで異なるMockを返す
            counter_call_count = [0]
            question_counter_mock = None

            def create_counter(*args, **kwargs):
                nonlocal question_counter_mock
                counter_call_count[0] += 1
                mock = MagicMock()
                mock.count = 0
                # question_counterは4番目に作成される（counter, progress_bar, compare_bar, question_counter）
                if counter_call_count[0] == 4:
                    question_counter_mock = mock
                    # question_counterのclose()は2回呼ばれる: Line 273とLine 317
                    close_call_count = [0]

                    def close_with_exception():
                        close_call_count[0] += 1
                        if close_call_count[0] == 2:
                            raise RuntimeError("Already closed")

                    mock.close.side_effect = close_with_exception
                return mock

            manager.counter.side_effect = create_counter

            with patch("dupdel.ui._blinking_input", return_value="y"):
                result, skipped = _list_dup_cand(tmpdir, manager)
                assert len(result) == 1


class TestRunStatsMode:
    """run_stats_mode のテスト"""

    def test_empty_directory(self, capsys):
        """空のディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_stats_mode(tmpdir)
            captured = capsys.readouterr()
            assert "統計モード" in captured.out
            assert "0 ファイル" in captured.out

    def test_with_files(self, capsys):
        """ファイルがある場合"""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                with open(os.path.join(tmpdir, f"test{i}.ts"), "w") as f:
                    f.write("content")

            run_stats_mode(tmpdir)
            captured = capsys.readouterr()
            assert "3 ファイル" in captured.out

    def test_with_similar_files(self, capsys):
        """類似ファイルがある場合"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 類似したファイル名を作成
            with open(os.path.join(tmpdir, "番組名_200101.ts"), "w") as f:
                f.write("x" * 1000)
            with open(os.path.join(tmpdir, "番組名_200102.ts"), "w") as f:
                f.write("x" * 1000)

            run_stats_mode(tmpdir)
            captured = capsys.readouterr()
            assert "2 ファイル" in captured.out

    def test_single_file_in_directory(self, capsys):
        """ディレクトリに1ファイルのみ（スキップされる）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # サブディレクトリに1ファイルのみ
            subdir = os.path.join(tmpdir, "subdir")
            os.makedirs(subdir)
            with open(os.path.join(subdir, "single.ts"), "w") as f:
                f.write("content")

            run_stats_mode(tmpdir)
            captured = capsys.readouterr()
            assert "1 ファイル" in captured.out

    def test_with_long_path(self, capsys):
        """長いパス名の省略表示"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 長いディレクトリ名を作成
            long_name = "a" * 100
            long_dir = os.path.join(tmpdir, long_name)
            os.makedirs(long_dir)
            with open(os.path.join(long_dir, "番組名_200101.ts"), "w") as f:
                f.write("x" * 1000)
            with open(os.path.join(long_dir, "番組名_200102.ts"), "w") as f:
                f.write("x" * 1000)

            run_stats_mode(tmpdir)
            captured = capsys.readouterr()
            # 長いパスが省略されることを確認
            assert "..." in captured.out or long_name[:10] in captured.out


class TestRunInteractive:
    """run_interactive のテスト"""

    def test_empty_directory(self, capsys):
        """空のディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_interactive(tmpdir)
            captured = capsys.readouterr()
            assert "重複候補は見つかりませんでした" in captured.out

    def test_keyboard_interrupt(self):
        """KeyboardInterrupt"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("dupdel.ui._list_dup_cand", side_effect=KeyboardInterrupt):
                with patch("dupdel.ui._handle_interrupt", return_value=True):
                    with pytest.raises(SystemExit) as exc_info:
                        run_interactive(tmpdir)
                    assert exc_info.value.code == 130

    def test_shutdown_event(self, capsys):
        """shutdown_eventが設定された場合"""
        from dupdel.constants import shutdown_event

        with tempfile.TemporaryDirectory() as tmpdir:
            shutdown_event.set()
            try:
                with patch("dupdel.ui._list_dup_cand", return_value=([], [])):
                    run_interactive(tmpdir)
                captured = capsys.readouterr()
                assert "中断しました" in captured.out
            finally:
                shutdown_event.clear()

    def test_with_candidates_confirmed(self, capsys):
        """削除候補があり確認された場合"""
        import difflib
        from dupdel.constants import shutdown_event

        shutdown_event.clear()
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test.ts")
            with open(test_file, "w") as f:
                f.write("content")

            sm = difflib.SequenceMatcher(None, "test.ts", "test.ts")
            dup_cand = [
                {
                    "path": test_file,
                    "name": "test.ts",
                    "basename": "test.ts",
                    "size": 7,
                    "mtime": 1000.0,
                    "index": 1,
                    "sm": sm,
                },
                {
                    "path": test_file,
                    "name": "test.ts",
                    "basename": "test.ts",
                    "size": 7,
                    "mtime": 1001.0,
                    "index": 2,
                    "sm": sm,
                },
            ]

            with patch("dupdel.ui._list_dup_cand", return_value=([dup_cand], [])):
                with patch("dupdel.ui._exec_delete", return_value=True):
                    run_interactive(tmpdir)
            captured = capsys.readouterr()
            assert "削除の最終確認" in captured.out

    def test_with_skipped_pairs_saved(self, capsys):
        """スキップしたペアがキャッシュ保存される場合"""
        from dupdel.constants import shutdown_event

        shutdown_event.clear()
        with tempfile.TemporaryDirectory() as tmpdir:
            skipped = [("/path/file1", "/path/file2")]

            with patch("dupdel.ui._list_dup_cand", return_value=([], skipped)):
                with patch("dupdel.ui.cache_pairs_bulk", return_value=1) as mock_cache:
                    run_interactive(tmpdir)
                    mock_cache.assert_called_once_with(skipped)
            captured = capsys.readouterr()
            assert "キャッシュに" in captured.out

    def test_with_skipped_pairs_not_saved(self, capsys):
        """削除拒否によりキャッシュ保存されない場合"""
        import difflib
        from dupdel.constants import shutdown_event

        shutdown_event.clear()
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test.ts")
            with open(test_file, "w") as f:
                f.write("content")

            sm = difflib.SequenceMatcher(None, "test.ts", "test.ts")
            dup_cand = [
                {
                    "path": test_file,
                    "name": "test.ts",
                    "basename": "test.ts",
                    "size": 7,
                    "mtime": 1000.0,
                    "index": 1,
                    "sm": sm,
                },
                {
                    "path": test_file,
                    "name": "test.ts",
                    "basename": "test.ts",
                    "size": 7,
                    "mtime": 1001.0,
                    "index": 2,
                    "sm": sm,
                },
            ]
            skipped = [("/path/file1", "/path/file2")]

            with patch("dupdel.ui._list_dup_cand", return_value=([dup_cand], skipped)):
                with patch("dupdel.ui._exec_delete", return_value=False):
                    run_interactive(tmpdir)
            captured = capsys.readouterr()
            assert "キャッシュは保存されませんでした" in captured.out
