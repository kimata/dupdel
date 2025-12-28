"""テキスト表示ユーティリティ（全角文字対応）"""

import difflib
import re
import shutil
import unicodedata

from .constants import (
    COLOR_DIM,
    COLOR_DIFF_DELETE,
    COLOR_DIFF_INSERT,
    COLOR_DIFF_REPLACE,
    COLOR_RESET,
    IGNORE_PAT,
)


def get_term_width() -> int:
    """ターミナルの幅を取得"""
    return shutil.get_terminal_size().columns


def get_visible_width(text: str) -> int:
    """ANSIエスケープシーケンスを除いた表示上の幅を返す（全角文字は2）"""
    ansi_escape = re.compile(r"\033\[[0-9;]*m")
    clean_text = ansi_escape.sub("", text)

    width = 0
    for char in clean_text:
        east_asian_width = unicodedata.east_asian_width(char)
        if east_asian_width in ("F", "W", "A"):  # Full-width, Wide, Ambiguous
            width += 2
        else:
            width += 1
    return width


def pad_to_width(text: str, width: int, align: str = "left") -> str:
    """文字列を指定した表示幅にパディング（全角文字対応）"""
    current_width = get_visible_width(text)
    padding = width - current_width
    if padding <= 0:
        return text
    if align == "right":
        return " " * padding + text
    return text + " " * padding


def truncate_to_width(text: str, max_width: int) -> str:
    """文字列を指定した表示幅に収まるように末尾を省略"""
    if get_visible_width(text) <= max_width:
        return text

    # 末尾から削って収まるようにする
    result = text
    while get_visible_width(result) > max_width - 3:  # "..." の分
        result = result[:-1]
    return result + "..."


def build_diff_text(text: str, sm: difflib.SequenceMatcher, mode: int, max_width: int) -> str:
    """差分を着色した文字列を構築（表示幅制限付き）"""
    result = []
    current_width = 0

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        s = text[i1:i2] if mode == 0 else text[j1:j2]

        # この部分を追加すると幅を超えるかチェック
        for char in s:
            char_width = 2 if unicodedata.east_asian_width(char) in ("F", "W", "A") else 1
            if current_width + char_width > max_width - 3:  # "..." の分
                result.append(f"{COLOR_RESET}...")
                return "".join(result)

            # 色を適用
            if tag == "equal":
                result.append(char)
            elif re.fullmatch(IGNORE_PAT + "+", char):
                result.append(f"{COLOR_DIM}{char}{COLOR_RESET}")
            elif tag == "delete":
                result.append(f"{COLOR_DIFF_DELETE}{char}{COLOR_RESET}")
            elif tag == "replace":
                result.append(f"{COLOR_DIFF_REPLACE}{char}{COLOR_RESET}")
            elif tag == "insert":
                result.append(f"{COLOR_DIFF_INSERT}{char}{COLOR_RESET}")
            else:  # pragma: no cover
                result.append(char)

            current_width += char_width

    return "".join(result)
