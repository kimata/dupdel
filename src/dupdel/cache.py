"""キャッシュ管理（SQLite）"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# キャッシュDBのパス（カレントディレクトリに保存）
_CACHE_DB_PATH = ".dupdel_cache.db"


def _normalize_path(path: str) -> str:
    """パスを正規化（絶対パスに変換）"""
    return str(Path(path).resolve())


def _get_pair_key(path1: str, path2: str) -> tuple[str, str]:
    """2つのパスをソートして一意なペアキーを生成"""
    p1, p2 = _normalize_path(path1), _normalize_path(path2)
    return (p1, p2) if p1 < p2 else (p2, p1)


@contextmanager
def _get_connection() -> Iterator[sqlite3.Connection]:
    """データベース接続を取得"""
    conn = sqlite3.connect(_CACHE_DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def init_cache_db() -> None:
    """キャッシュDBを初期化"""
    with _get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS skipped_pairs (
                path1 TEXT NOT NULL,
                path2 TEXT NOT NULL,
                skipped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (path1, path2)
            )
        """
        )
        conn.commit()


def is_pair_cached(path1: str, path2: str) -> bool:
    """ペアがキャッシュ済み（スキップ済み）かチェック"""
    key = _get_pair_key(path1, path2)
    with _get_connection() as conn:
        cursor = conn.execute(
            "SELECT 1 FROM skipped_pairs WHERE path1 = ? AND path2 = ?",
            key,
        )
        return cursor.fetchone() is not None


def _cache_pair(path1: str, path2: str) -> None:
    """ペアをキャッシュに追加"""
    key = _get_pair_key(path1, path2)
    with _get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO skipped_pairs (path1, path2) VALUES (?, ?)",
            key,
        )
        conn.commit()


def cache_pairs_bulk(pairs: list[tuple[str, str]]) -> int:
    """複数のペアを一括でキャッシュに追加"""
    if not pairs:
        return 0
    keys = [_get_pair_key(p1, p2) for p1, p2 in pairs]
    with _get_connection() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO skipped_pairs (path1, path2) VALUES (?, ?)",
            keys,
        )
        conn.commit()
    return len(keys)


def _get_cached_count() -> int:
    """キャッシュ済みペア数を取得"""
    with _get_connection() as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM skipped_pairs")
        result = cursor.fetchone()
        return result[0] if result else 0


def _clear_cache() -> None:
    """キャッシュをクリア"""
    with _get_connection() as conn:
        conn.execute("DELETE FROM skipped_pairs")
        conn.commit()
