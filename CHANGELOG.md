# Changelog

このプロジェクトのすべての注目すべき変更はこのファイルに記載されます。

フォーマットは [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に基づいています。

## [Unreleased]

## [0.1.1] - 2026-01-24

### 🔄 Changed

- キャッシュ DB の保存先をカレントディレクトリ（`.dupdel_cache.db`）に変更
- `FileInfo`, `DupCand` 等の型を `dict[str, Any]` から dataclass に変更
- ユーザー入力の正規化を入力取得関数内で行うように統一
- 例外処理を具体的な例外型（`ValueError`, `RuntimeError`）に変更
- パス操作を `os.path` から `pathlib.Path` に統一

### 🗑️ Removed

- 本番コードから `assert` 文を削除

## [0.1.0] - 2026-01-23

### ✨ Added

- 類似ファイル名の重複ファイル検出機能（difflib による類似度計算）
- インタラクティブな削除確認 UI（enlighten によるプログレス表示）
- 削除履歴のキャッシュ管理（SQLite）
- 並列処理による高速なファイル比較
- `--stats` オプションによるフォルダ毎の統計表示
- ファイル名の差分箇所を着色表示
- 長いファイル名を端末幅に収まるように省略
- 隠しフォルダ・ファイルを処理対象から自動除外
- 比較対象を同一ディレクトリ内のファイルに限定

[Unreleased]: https://github.com/kimata/dupdel/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/kimata/dupdel/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/kimata/dupdel/releases/tag/v0.1.0
