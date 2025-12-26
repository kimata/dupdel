"""dupdel - 類似ファイル名の重複ファイル削除支援ツール"""

from .constants import MATCH_TH, SIZE_TH, TRASH_DIR
from .core import PrecomputedFileInfo, find_dup_candidates_parallel, list_files
from .ui import run_interactive, run_stats_mode

__all__ = [
    "MATCH_TH",
    "SIZE_TH",
    "TRASH_DIR",
    "PrecomputedFileInfo",
    "find_dup_candidates_parallel",
    "list_files",
    "run_interactive",
    "run_stats_mode",
]
