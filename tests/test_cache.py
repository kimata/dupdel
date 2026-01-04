#!/usr/bin/env python3
"""
cache.py のユニットテスト
"""
# ruff: noqa: S101

import os
import tempfile

import pytest

# テスト用にキャッシュDBパスを一時ディレクトリに変更
import dupdel.cache as cache_module


@pytest.fixture
def temp_cache_db(tmp_path):
    """一時的なキャッシュDBを使用するフィクスチャ"""
    original_path = cache_module._CACHE_DB_PATH
    cache_module._CACHE_DB_PATH = str(tmp_path / "test_cache.db")
    yield cache_module._CACHE_DB_PATH
    cache_module._CACHE_DB_PATH = original_path


class TestCacheDb:
    """キャッシュDB操作のテスト"""

    def test_init_cache_db(self, temp_cache_db):
        """DB初期化"""
        cache_module.init_cache_db()
        assert os.path.exists(temp_cache_db)

    def test_cache_pair(self, temp_cache_db):
        """ペアをキャッシュに追加"""
        cache_module.init_cache_db()
        cache_module._clear_cache()

        cache_module._cache_pair("/path/to/file1.ts", "/path/to/file2.ts")

        assert cache_module._get_cached_count() == 1

    def test_is_pair_cached_positive(self, temp_cache_db):
        """キャッシュ済みペアの確認（存在する）"""
        cache_module.init_cache_db()
        cache_module._clear_cache()

        cache_module._cache_pair("/path/to/file1.ts", "/path/to/file2.ts")

        assert (
            cache_module.is_pair_cached("/path/to/file1.ts", "/path/to/file2.ts")
            is True
        )

    def test_is_pair_cached_negative(self, temp_cache_db):
        """キャッシュ済みペアの確認（存在しない）"""
        cache_module.init_cache_db()
        cache_module._clear_cache()

        assert (
            cache_module.is_pair_cached("/path/to/file1.ts", "/path/to/file2.ts")
            is False
        )

    def test_is_pair_cached_reverse_order(self, temp_cache_db):
        """逆順でもキャッシュ済みと判定される"""
        cache_module.init_cache_db()
        cache_module._clear_cache()

        cache_module._cache_pair("/path/to/file1.ts", "/path/to/file2.ts")

        # 逆順でも検出できる
        assert (
            cache_module.is_pair_cached("/path/to/file2.ts", "/path/to/file1.ts")
            is True
        )

    def test_cache_pairs_bulk(self, temp_cache_db):
        """一括キャッシュ追加"""
        cache_module.init_cache_db()
        cache_module._clear_cache()

        pairs = [
            ("/path/to/a1.ts", "/path/to/a2.ts"),
            ("/path/to/b1.ts", "/path/to/b2.ts"),
            ("/path/to/c1.ts", "/path/to/c2.ts"),
        ]
        saved = cache_module.cache_pairs_bulk(pairs)

        assert saved == 3
        assert cache_module._get_cached_count() == 3

    def test_cache_pairs_bulk_empty(self, temp_cache_db):
        """空リストの一括キャッシュ"""
        cache_module.init_cache_db()
        cache_module._clear_cache()

        saved = cache_module.cache_pairs_bulk([])

        assert saved == 0
        assert cache_module._get_cached_count() == 0

    def test_clear_cache(self, temp_cache_db):
        """キャッシュクリア"""
        cache_module.init_cache_db()

        cache_module._cache_pair("/path/to/file1.ts", "/path/to/file2.ts")
        assert cache_module._get_cached_count() == 1

        cache_module._clear_cache()
        assert cache_module._get_cached_count() == 0

    def test_duplicate_cache_pair(self, temp_cache_db):
        """重複するペアの追加（上書き）"""
        cache_module.init_cache_db()
        cache_module._clear_cache()

        cache_module._cache_pair("/path/to/file1.ts", "/path/to/file2.ts")
        cache_module._cache_pair("/path/to/file1.ts", "/path/to/file2.ts")

        # 重複しても1件のまま
        assert cache_module._get_cached_count() == 1
