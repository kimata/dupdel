"""ui.py のユニットテスト"""
# ruff: noqa: S101, SIM117

import difflib
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from dupdel.cache import get_pair_key
from dupdel.constants import FileInfo
from dupdel.ui import (
    _blinking_input,
    _confirm_quit,
    _exec_delete,
    _list_dup_cand,
    _print_dup_cand,
    _resolve_trash_path,
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

    def test_lowercase_by_default(self):
        """デフォルトでは小文字に正規化される"""
        with patch("builtins.input", return_value="  Y  "):
            assert _blinking_input("prompt: ") == "y"

    def test_keep_case(self):
        """keep_case=True では大文字小文字を保持する"""
        with patch("builtins.input", return_value="  N  "):
            assert _blinking_input("prompt: ", keep_case=True) == "N"


class TestPrintDupCand:
    """print_dup_cand のテスト"""

    def test_print_candidate(self, capsys):
        """重複候補の表示"""
        sm = difflib.SequenceMatcher(None, "file1.ts", "file2.ts")
        dup_cand = (
            FileInfo(
                path="/dir/file1.ts",
                name="file1.ts",
                basename="file1.ts",
                size=1000000,
                mtime=1000.0,
                index=1,
                sm=sm,
            ),
            FileInfo(
                path="/dir/file2.ts",
                name="file2.ts",
                basename="file2.ts",
                size=1000000,
                mtime=1001.0,
                index=2,
                sm=sm,
            ),
        )
        _print_dup_cand(dup_cand, 1, 10)
        captured = capsys.readouterr()
        assert "類似度" in captured.out
        assert "サイズ差" in captured.out

    def test_print_with_directory(self, capsys):
        """ディレクトリパス付きの表示"""
        sm = difflib.SequenceMatcher(None, "file1.ts", "file2.ts")
        dup_cand = (
            FileInfo(
                path="/dir/subdir/file1.ts",
                name="subdir/file1.ts",
                basename="file1.ts",
                size=1000000,
                mtime=1000.0,
                index=1,
                sm=sm,
            ),
            FileInfo(
                path="/dir/subdir/file2.ts",
                name="subdir/file2.ts",
                basename="file2.ts",
                size=1000000,
                mtime=1001.0,
                index=2,
                sm=sm,
            ),
        )
        _print_dup_cand(dup_cand, 1, 10)
        captured = capsys.readouterr()
        assert "subdir" in captured.out

    def test_print_with_size_warning(self, capsys):
        """サイズ差警告の表示"""
        sm = difflib.SequenceMatcher(None, "file1.ts", "file2.ts")
        dup_cand = (
            FileInfo(
                path="/dir/file1.ts",
                name="file1.ts",
                basename="file1.ts",
                size=500 * 1024 * 1024,  # 500MB
                mtime=1000.0,
                index=1,
                sm=sm,
            ),
            FileInfo(
                path="/dir/file2.ts",
                name="file2.ts",
                basename="file2.ts",
                size=100 * 1024 * 1024,  # 100MB
                mtime=1001.0,
                index=2,
                sm=sm,
            ),
        )
        _print_dup_cand(dup_cand, 1, 10)
        captured = capsys.readouterr()
        assert "MB" in captured.out

    def test_print_with_long_directory(self, capsys):
        """長いディレクトリパスの省略表示"""
        # ターミナル幅を狭く設定
        with patch("dupdel.ui.get_term_width", return_value=60):
            long_dir = "very/long/directory/path/that/needs/truncation"
            sm = difflib.SequenceMatcher(None, "file1.ts", "file2.ts")
            dup_cand = (
                FileInfo(
                    path=f"/dir/{long_dir}/file1.ts",
                    name=f"{long_dir}/file1.ts",
                    basename="file1.ts",
                    size=1000000,
                    mtime=1000.0,
                    index=1,
                    sm=sm,
                ),
                FileInfo(
                    path=f"/dir/{long_dir}/file2.ts",
                    name=f"{long_dir}/file2.ts",
                    basename="file2.ts",
                    size=1000000,
                    mtime=1001.0,
                    index=2,
                    sm=sm,
                ),
            )
            _print_dup_cand(dup_cand, 1, 10)
            captured = capsys.readouterr()
            # 省略記号が含まれていることを確認
            assert "..." in captured.out or "file" in captured.out


class TestConfirmQuit:
    """_confirm_quit のテスト"""

    def test_continue(self):
        """継続を選択"""
        with patch("dupdel.ui._blinking_input", return_value="n"):
            assert _confirm_quit() is False

    def test_exit(self):
        """終了を選択"""
        with patch("dupdel.ui._blinking_input", return_value="y"):
            assert _confirm_quit() is True

    def test_keyboard_interrupt(self):
        """入力中にKeyboardInterrupt"""
        with patch("dupdel.ui._blinking_input", side_effect=KeyboardInterrupt):
            assert _confirm_quit() is True

    def test_eof_error(self):
        """EOFError"""
        with patch("dupdel.ui._blinking_input", side_effect=EOFError):
            assert _confirm_quit() is True


class TestResolveTrashPath:
    """_resolve_trash_path のテスト"""

    def test_no_collision(self, tmp_path):
        """同名ファイルがなければベース名のまま"""
        dst = _resolve_trash_path(str(tmp_path), Path("/data/番組名.ts"))
        assert dst == tmp_path / "番組名.ts"

    def test_collision_adds_suffix(self, tmp_path):
        """同名ファイルがあれば連番を付与して上書きを防ぐ"""
        (tmp_path / "番組名.ts").touch()
        dst = _resolve_trash_path(str(tmp_path), Path("/data/番組名.ts"))
        assert dst == tmp_path / "番組名 (1).ts"

    def test_multiple_collisions(self, tmp_path):
        """連番が既に存在する場合は次の番号を使う"""
        (tmp_path / "番組名.ts").touch()
        (tmp_path / "番組名 (1).ts").touch()
        dst = _resolve_trash_path(str(tmp_path), Path("/data/番組名.ts"))
        assert dst == tmp_path / "番組名 (2).ts"


class TestExecDelete:
    """exec_delete のテスト"""

    def test_empty_list(self, capsys):
        """空のリスト"""
        manager = MagicMock()
        manager.counter.return_value = MagicMock()
        _exec_delete([], "/tmp/trash", manager)  # noqa: S108
        captured = capsys.readouterr()
        assert "削除候補がありません" in captured.out

    def test_delete_yes(self):
        """削除を確認"""
        with tempfile.TemporaryDirectory() as tmpdir:
            trash_dir = Path(tmpdir) / "trash"
            test_file = Path(tmpdir) / "test.ts"
            test_file.write_text("content")

            sm = difflib.SequenceMatcher(None, "test.ts", "test.ts")
            dup_cand_list = [
                (
                    FileInfo(
                        path=str(test_file),
                        name="test.ts",
                        basename="test.ts",
                        size=7,
                        mtime=1000.0,
                        index=1,
                        sm=sm,
                    ),
                    FileInfo(
                        path=str(test_file),
                        name="test.ts",
                        basename="test.ts",
                        size=7,
                        mtime=1001.0,
                        index=2,
                        sm=sm,
                    ),
                )
            ]

            manager = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.counter.return_value = counter

            with patch("dupdel.ui._blinking_input", return_value="y"):
                _exec_delete(dup_cand_list, str(trash_dir), manager)
                assert not test_file.exists()
                assert (trash_dir / "test.ts").exists()

    def test_delete_no(self):
        """削除を拒否"""
        with tempfile.TemporaryDirectory() as tmpdir:
            trash_dir = Path(tmpdir) / "trash"
            test_file = Path(tmpdir) / "test.ts"
            test_file.write_text("content")

            sm = difflib.SequenceMatcher(None, "test.ts", "test.ts")
            dup_cand_list = [
                (
                    FileInfo(
                        path=str(test_file),
                        name="test.ts",
                        basename="test.ts",
                        size=7,
                        mtime=1000.0,
                        index=1,
                        sm=sm,
                    ),
                    FileInfo(
                        path=str(test_file),
                        name="test.ts",
                        basename="test.ts",
                        size=7,
                        mtime=1001.0,
                        index=2,
                        sm=sm,
                    ),
                )
            ]

            manager = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.counter.return_value = counter

            with patch("dupdel.ui._blinking_input", return_value="n"):
                _exec_delete(dup_cand_list, str(trash_dir), manager)
                assert test_file.exists()

    def test_delete_all(self):
        """すべて削除"""
        with tempfile.TemporaryDirectory() as tmpdir:
            trash_dir = Path(tmpdir) / "trash"
            test_file1 = Path(tmpdir) / "test1.ts"
            test_file2 = Path(tmpdir) / "test2.ts"
            test_file1.write_text("content")
            test_file2.write_text("content")

            sm = difflib.SequenceMatcher(None, "test.ts", "test.ts")
            dup_cand_list = [
                (
                    FileInfo(
                        path=str(test_file1),
                        name="test1.ts",
                        basename="test1.ts",
                        size=7,
                        mtime=1000.0,
                        index=1,
                        sm=sm,
                    ),
                    FileInfo(
                        path=str(test_file1),
                        name="test1.ts",
                        basename="test1.ts",
                        size=7,
                        mtime=1001.0,
                        index=2,
                        sm=sm,
                    ),
                ),
                (
                    FileInfo(
                        path=str(test_file2),
                        name="test2.ts",
                        basename="test2.ts",
                        size=7,
                        mtime=1000.0,
                        index=1,
                        sm=sm,
                    ),
                    FileInfo(
                        path=str(test_file2),
                        name="test2.ts",
                        basename="test2.ts",
                        size=7,
                        mtime=1001.0,
                        index=2,
                        sm=sm,
                    ),
                ),
            ]

            manager = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.counter.return_value = counter

            with patch("dupdel.ui._blinking_input", return_value="a"):
                _exec_delete(dup_cand_list, str(trash_dir), manager)
                assert not test_file1.exists()
                assert not test_file2.exists()

    def test_file_not_found(self, capsys):
        """ファイルが見つからない"""
        sm = difflib.SequenceMatcher(None, "test.ts", "test.ts")
        dup_cand_list = [
            (
                FileInfo(
                    path="/nonexistent/file1.ts",
                    name="file1.ts",
                    basename="file1.ts",
                    size=7,
                    mtime=1000.0,
                    index=1,
                    sm=sm,
                ),
                FileInfo(
                    path="/nonexistent/file2.ts",
                    name="file2.ts",
                    basename="file2.ts",
                    size=7,
                    mtime=1001.0,
                    index=2,
                    sm=sm,
                ),
            )
        ]

        manager = MagicMock()
        counter = MagicMock()
        counter.count = 0
        manager.counter.return_value = counter

        _exec_delete(dup_cand_list, "/tmp/trash", manager)  # noqa: S108
        captured = capsys.readouterr()
        assert "ファイルが見つかりません" in captured.out

    def test_move_oserror(self, capsys):
        """移動失敗（ディスク満杯・権限など）で全体が止まらない"""
        with tempfile.TemporaryDirectory() as tmpdir:
            trash_dir = Path(tmpdir) / "trash"
            test_file = Path(tmpdir) / "test.ts"
            test_file.write_text("content")

            sm = difflib.SequenceMatcher(None, "test.ts", "test.ts")
            dup_cand_list = [
                (
                    FileInfo(
                        path=str(test_file),
                        name="test.ts",
                        basename="test.ts",
                        size=7,
                        mtime=1000.0,
                        index=1,
                        sm=sm,
                    ),
                    FileInfo(
                        path=str(test_file),
                        name="test.ts",
                        basename="test.ts",
                        size=7,
                        mtime=1001.0,
                        index=2,
                        sm=sm,
                    ),
                )
            ]

            manager = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.counter.return_value = counter

            with patch("dupdel.ui._blinking_input", return_value="y"):
                with patch("dupdel.ui.shutil.move", side_effect=OSError("No space left")):
                    _exec_delete(dup_cand_list, str(trash_dir), manager)
            captured = capsys.readouterr()
            assert "移動に失敗しました" in captured.out
            assert test_file.exists()

    def test_trash_dir_creation_failure(self, capsys):
        """ゴミ箱ディレクトリが作成できない場合"""
        sm = difflib.SequenceMatcher(None, "test.ts", "test.ts")
        dup_cand_list = [
            (
                FileInfo(
                    path="/dir/file1.ts",
                    name="file1.ts",
                    basename="file1.ts",
                    size=7,
                    mtime=1000.0,
                    index=1,
                    sm=sm,
                ),
                FileInfo(
                    path="/dir/file2.ts",
                    name="file2.ts",
                    basename="file2.ts",
                    size=7,
                    mtime=1001.0,
                    index=2,
                    sm=sm,
                ),
            )
        ]

        manager = MagicMock()
        with patch("dupdel.ui.Path.mkdir", side_effect=OSError("Permission denied")):
            _exec_delete(dup_cand_list, "/proc/invalid/trash", manager)
        captured = capsys.readouterr()
        assert "ゴミ箱ディレクトリを作成できません" in captured.out


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

            result = _list_dup_cand(tmpdir, manager)
            assert result == []

    def test_single_file(self):
        """1ファイルのみ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.ts"
            test_file.write_text("content")

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            result = _list_dup_cand(tmpdir, manager)
            assert result == []

    def test_shutdown_event_early_return(self):
        """shutdown_eventによる早期リターン"""
        from dupdel.constants import shutdown_event

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.ts"
            test_file.write_text("content")

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            shutdown_event.set()
            try:
                result = _list_dup_cand(tmpdir, manager)
                assert result == []
            finally:
                shutdown_event.clear()

    def test_with_similar_files_yes(self):
        """類似ファイルがあり「y」と回答"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 類似したファイル名を作成
            (Path(tmpdir) / "番組名_200101.ts").write_text("x" * 1000)
            (Path(tmpdir) / "番組名_200102.ts").write_text("x" * 1000)

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            with patch("dupdel.ui._blinking_input", return_value="y"):
                result = _list_dup_cand(tmpdir, manager)
                assert len(result) == 1

    def test_with_similar_files_no(self):
        """類似ファイルがあり「n」と回答"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 類似したファイル名を作成
            (Path(tmpdir) / "番組名_200101.ts").write_text("x" * 1000)
            (Path(tmpdir) / "番組名_200102.ts").write_text("x" * 1000)

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            with patch("dupdel.ui._blinking_input", return_value="n"):
                with patch("dupdel.ui.cache_pair") as mock_cache_pair:
                    result = _list_dup_cand(tmpdir, manager)
                    assert len(result) == 0
                    # 「n」= 重複ではない、は即座にキャッシュへ保存される
                    mock_cache_pair.assert_called_once()

    def test_with_similar_files_quit(self):
        """類似ファイルがあり「q」と回答"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 類似したファイル名を作成
            (Path(tmpdir) / "番組名_200101.ts").write_text("x" * 1000)
            (Path(tmpdir) / "番組名_200102.ts").write_text("x" * 1000)

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            with patch("dupdel.ui._blinking_input", return_value="q"):
                result = _list_dup_cand(tmpdir, manager)
                assert len(result) == 0

    def test_folder_skip_with_capital_n(self):
        """「N」で同じフォルダの残りの質問がすべてスキップされる（今回の実行のみ）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # dir1: 類似ファイル3つ → 3ペア、dir2: 類似ファイル2つ → 1ペア
            dir1 = Path(tmpdir) / "dir1"
            dir2 = Path(tmpdir) / "dir2"
            dir1.mkdir()
            dir2.mkdir()
            for i in range(3):
                (dir1 / f"番組名_20010{i}.ts").write_text("x" * 1000)
            for i in range(2):
                (dir2 / f"別番組_20020{i}.ts").write_text("x" * 1000)

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            # 質問はパス順なので dir1 のペアが先。「N」で dir1 の3ペアを全部飛ばし、
            # 続く dir2 のペアには「y」と答える
            answers = iter(["N", "y"])

            def fake_input(prompt, **kwargs):
                return next(answers)

            with patch("dupdel.ui._blinking_input", side_effect=fake_input):
                with patch("dupdel.ui.cache_pair") as mock_cache_pair:
                    result = _list_dup_cand(tmpdir, manager)

            # dir2 のペアだけが削除候補になる
            assert len(result) == 1
            assert Path(result[0][0].path).parent == dir2
            # 「N」のスキップはキャッシュに保存されない（今回の実行のみ）
            mock_cache_pair.assert_not_called()

    def test_no_valid_comparisons(self):
        """有効な比較対象がない（異なるディレクトリのファイル）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 異なるサブディレクトリにファイルを作成
            subdir1 = Path(tmpdir) / "dir1"
            subdir2 = Path(tmpdir) / "dir2"
            subdir1.mkdir()
            subdir2.mkdir()
            (subdir1 / "file.ts").write_text("content")
            (subdir2 / "file.ts").write_text("content")

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            result = _list_dup_cand(tmpdir, manager)
            assert result == []

    def test_with_cached_pairs(self):
        """キャッシュ済みペアがスキップされる"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 類似したファイル名を作成
            file1 = Path(tmpdir) / "番組名_200101.ts"
            file2 = Path(tmpdir) / "番組名_200102.ts"
            file1.write_text("x" * 1000)
            file2.write_text("x" * 1000)

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            cached = {get_pair_key(str(file1), str(file2))}
            with patch("dupdel.ui.load_cached_pairs", return_value=cached):
                result = _list_dup_cand(tmpdir, manager)
                assert len(result) == 0

    def test_shutdown_during_question_loop(self):
        """質問ループ中にshutdown_eventがセットされた場合（複数ペア）"""
        from dupdel.constants import shutdown_event

        with tempfile.TemporaryDirectory() as tmpdir:
            # 複数の類似ファイルペアを作成（3つ以上で2ペア以上検出される）
            for i in range(4):
                (Path(tmpdir) / f"番組名_20010{i}.ts").write_text("x" * 1000)

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            call_count = [0]

            def input_with_shutdown(prompt, **kwargs):
                call_count[0] += 1
                if call_count[0] >= 1:
                    # 1回目の回答後にshutdown_eventをセット
                    shutdown_event.set()
                return "y"

            try:
                with patch("dupdel.ui._blinking_input", side_effect=input_with_shutdown):
                    _list_dup_cand(tmpdir, manager)
                    # shutdown後は残りの質問がスキップされる
            finally:
                shutdown_event.clear()

    def test_keyboard_interrupt_continue(self):
        """KeyboardInterruptで継続を選択"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 類似したファイル名を作成
            (Path(tmpdir) / "番組名_200101.ts").write_text("x" * 1000)
            (Path(tmpdir) / "番組名_200102.ts").write_text("x" * 1000)

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            call_count = [0]

            def input_with_interrupt(prompt, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise KeyboardInterrupt
                return "q"

            with patch("dupdel.ui._blinking_input", side_effect=input_with_interrupt):
                with patch("dupdel.ui._confirm_quit", return_value=False):
                    result = _list_dup_cand(tmpdir, manager)
                    # 「継続」を選ぶと同じ質問が再表示される
                    assert call_count[0] == 2
                    assert result == []

    def test_keyboard_interrupt_exit(self):
        """KeyboardInterruptで終了を選択"""
        from dupdel.constants import shutdown_event

        with tempfile.TemporaryDirectory() as tmpdir:
            # 類似したファイル名を作成
            (Path(tmpdir) / "番組名_200101.ts").write_text("x" * 1000)
            (Path(tmpdir) / "番組名_200102.ts").write_text("x" * 1000)

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            shutdown_event.clear()
            try:
                with patch("dupdel.ui._blinking_input", side_effect=KeyboardInterrupt):
                    with patch("dupdel.ui._confirm_quit", return_value=True):
                        result = _list_dup_cand(tmpdir, manager)
                        assert shutdown_event.is_set()
                        assert result == []
            finally:
                shutdown_event.clear()

    def test_shutdown_after_cache_filter(self):
        """キャッシュフィルタリング後にshutdown_eventがセットされた場合"""
        from dupdel.constants import shutdown_event

        with tempfile.TemporaryDirectory() as tmpdir:
            # 類似したファイル名を作成
            (Path(tmpdir) / "番組名_200101.ts").write_text("x" * 1000)
            (Path(tmpdir) / "番組名_200102.ts").write_text("x" * 1000)

            manager = MagicMock()
            status_bar = MagicMock()
            counter = MagicMock()
            counter.count = 0
            manager.status_bar.return_value = status_bar
            manager.counter.return_value = counter

            def load_with_shutdown():
                shutdown_event.set()
                return set()

            try:
                with patch("dupdel.ui.load_cached_pairs", side_effect=load_with_shutdown):
                    result = _list_dup_cand(tmpdir, manager)
                    # shutdown 後は質問ループが即座に終了する
                    assert result == []
            finally:
                shutdown_event.clear()

    def test_question_counter_close_exception(self):
        """question_counter.close()が例外を投げても処理が継続する"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 類似したファイル名を作成
            (Path(tmpdir) / "番組名_200101.ts").write_text("x" * 1000)
            (Path(tmpdir) / "番組名_200102.ts").write_text("x" * 1000)

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
                    mock.close.side_effect = RuntimeError("Already closed")
                return mock

            manager.counter.side_effect = create_counter

            with patch("dupdel.ui._blinking_input", return_value="y"):
                result = _list_dup_cand(tmpdir, manager)
                assert len(result) == 1

            # close はフェーズ2開始時の1回だけ呼ばれる（二重closeしない）
            assert question_counter_mock is not None
            question_counter_mock.close.assert_called_once()


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
                (Path(tmpdir) / f"test{i}.ts").write_text("content")

            run_stats_mode(tmpdir)
            captured = capsys.readouterr()
            assert "3 ファイル" in captured.out

    def test_with_similar_files(self, capsys):
        """類似ファイルがある場合"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 類似したファイル名を作成
            (Path(tmpdir) / "番組名_200101.ts").write_text("x" * 1000)
            (Path(tmpdir) / "番組名_200102.ts").write_text("x" * 1000)

            run_stats_mode(tmpdir)
            captured = capsys.readouterr()
            assert "2 ファイル" in captured.out

    def test_single_file_in_directory(self, capsys):
        """ディレクトリに1ファイルのみ（スキップされる）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # サブディレクトリに1ファイルのみ
            subdir = Path(tmpdir) / "subdir"
            subdir.mkdir()
            (subdir / "single.ts").write_text("content")

            run_stats_mode(tmpdir)
            captured = capsys.readouterr()
            assert "1 ファイル" in captured.out

    def test_with_long_path(self, capsys):
        """長いパス名の省略表示"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 長いディレクトリ名を作成
            long_name = "a" * 100
            long_dir = Path(tmpdir) / long_name
            long_dir.mkdir()
            (long_dir / "番組名_200101.ts").write_text("x" * 1000)
            (long_dir / "番組名_200102.ts").write_text("x" * 1000)

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
        from dupdel.constants import shutdown_event

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                with patch("dupdel.ui._list_dup_cand", side_effect=KeyboardInterrupt):
                    with pytest.raises(SystemExit) as exc_info:
                        run_interactive(tmpdir)
                    assert exc_info.value.code == 130
            finally:
                shutdown_event.clear()

    def test_shutdown_event(self, capsys):
        """shutdown_eventが設定された場合"""
        from dupdel.constants import shutdown_event

        with tempfile.TemporaryDirectory() as tmpdir:
            shutdown_event.set()
            try:
                with patch("dupdel.ui._list_dup_cand", return_value=[]):
                    run_interactive(tmpdir)
                captured = capsys.readouterr()
                assert "中断しました" in captured.out
            finally:
                shutdown_event.clear()

    def test_with_candidates_confirmed(self, capsys):
        """削除候補があり確認された場合"""
        from dupdel.constants import shutdown_event

        shutdown_event.clear()
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.ts"
            test_file.write_text("content")

            sm = difflib.SequenceMatcher(None, "test.ts", "test.ts")
            dup_cand = (
                FileInfo(
                    path=str(test_file),
                    name="test.ts",
                    basename="test.ts",
                    size=7,
                    mtime=1000.0,
                    index=1,
                    sm=sm,
                ),
                FileInfo(
                    path=str(test_file),
                    name="test.ts",
                    basename="test.ts",
                    size=7,
                    mtime=1001.0,
                    index=2,
                    sm=sm,
                ),
            )

            with patch("dupdel.ui._list_dup_cand", return_value=[dup_cand]):
                with patch("dupdel.ui._exec_delete", return_value=None):
                    run_interactive(tmpdir)
            captured = capsys.readouterr()
            assert "削除の最終確認" in captured.out
