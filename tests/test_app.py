"""app.py のユニットテスト"""

import tempfile
from unittest.mock import patch

import pytest


class TestMain:
    """main 関数のテスト"""

    def test_interactive_mode(self):
        """対話モードの実行"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("sys.argv", ["app.py", tmpdir]):
                with patch("app.run_interactive") as mock_run:
                    from app import main

                    main()
                    mock_run.assert_called_once_with(tmpdir)

    def test_stats_mode(self):
        """統計モードの実行"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("sys.argv", ["app.py", "--stats", tmpdir]):
                with patch("app.run_stats_mode") as mock_run:
                    from app import main

                    main()
                    mock_run.assert_called_once_with(tmpdir)
