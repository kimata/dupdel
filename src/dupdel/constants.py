"""定数・型定義・グローバル状態"""

import difflib
import threading
from dataclasses import dataclass

# 閾値
SIZE_TH = 200 * 1024 * 1024  # サイズ差警告閾値 (200MB)
MATCH_TH = 0.85  # ファイル名類似度閾値

# 無視するパターン:
# - \d: 数字
# - _ 　: アンダースコア、半角/全角スペース
# - 🈑🈞字再前後: 放送局記号・字幕表記
# - []: 角括弧
IGNORE_PAT = r"[\d_ 　🈑🈞字再前後\[\]]"

# 削除先（ゴミ箱）
TRASH_DIR = "/storage/.recycle"

# ANSI256 カラー（黒背景に合う落ち着いた色）
COLOR_TITLE = "\033[38;5;67m"  # スチールブルー
COLOR_SUCCESS = "\033[38;5;72m"  # シアングリーン
COLOR_WARNING = "\033[38;5;180m"  # ライトサーモン
COLOR_ERROR = "\033[38;5;167m"  # インディアンレッド
COLOR_DIM = "\033[38;5;242m"  # ミディアムグレー
COLOR_RESET = "\033[0m"
BLINK_ON = "\033[5m"  # 点滅開始

# 差分表示用カラー
COLOR_DIFF_DELETE = "\033[38;5;174m"  # ライトピンク
COLOR_DIFF_REPLACE = "\033[38;5;114m"  # ペールグリーン
COLOR_DIFF_INSERT = "\033[38;5;110m"  # ライトスカイブルー


# 型定義
@dataclass
class FileInfo:
    """重複候補のファイル情報"""

    path: str
    name: str  # 相対パス
    basename: str  # ファイル名
    size: int
    mtime: float
    index: int
    sm: difflib.SequenceMatcher


DupCand = tuple[FileInfo, FileInfo]  # (古いファイル, 新しいファイル)


@dataclass
class DirStats:
    """ディレクトリ統計情報"""

    rel_path: str
    file_count: int
    pairs: int
    candidates: int


# グローバル停止フラグ
shutdown_event = threading.Event()
