#!/usr/bin/env python3

"""
類似ファイル名の重複ファイル削除を支援するツールです。

Usage:
  app.py [--stats] PATH

Options:
  PATH      チェック対象のフォルダ
  --stats   フォルダ毎の質問リスト数を表示（デバッグ用）
"""

from docopt import docopt

from dupdel import run_interactive, run_stats_mode


def main() -> None:
    assert __doc__ is not None
    args = docopt(__doc__)

    target_dir_path = args["PATH"]

    if args["--stats"]:
        run_stats_mode(target_dir_path)
    else:
        run_interactive(target_dir_path)


if __name__ == "__main__":
    main()
