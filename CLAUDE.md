# CLAUDE.md

このファイルは、Claude Code がこのリポジトリで作業する際のガイダンスを提供します。

## プロジェクト概要

`dupdel` は類似ファイル名の重複ファイルを検出・削除するための CLI ツールです。同じディレクトリ内にある類似した名前のファイルを検出し、インタラクティブに削除を支援します。

### 主な機能

- 類似ファイル名の自動検出（difflib による類似度計算）
- インタラクティブな削除確認 UI（enlighten によるプログレス表示）
- 削除履歴のキャッシュ管理（SQLite）
- 並列処理による高速なファイル比較

## 重要な注意事項

### 外部ライブラリ (my_lib) の変更

- `my_lib` のソースコードは `../my-py-lib` に存在する
- リファクタリング等で `my_lib` の修正が必要な場合：
    1. **必ず事前に何を変更したいか説明し、確認を取ること**
    2. `../my-py-lib` で修正を行い、commit & push する
    3. このリポジトリの `pyproject.toml` のコミットハッシュを更新する
    4. `uv sync` を実行して依存関係を更新する

### プロジェクト設定ファイルの変更

- `pyproject.toml` をはじめとする一般的なプロジェクト管理ファイルは `../py-project` で管理している
- 設定ファイルを変更したい場合：
    1. **必ず事前に何を変更したいか説明し、確認を取ること**
    2. `../py-project` を使って更新する
    3. **このリポジトリの設定ファイルを直接編集しないこと**

### ドキュメントの更新

- コードを更新した際は、`README.md` や `CLAUDE.md` を更新する必要がないか検討すること
- 特に以下の場合は更新を検討：
    - 新機能の追加
    - コマンドオプションの変更
    - アーキテクチャの変更

## 開発コマンド

### 依存関係

```bash
# 依存関係のインストール
uv sync

# 依存関係の更新
uv sync --upgrade
```

### アプリケーション実行

```bash
# 通常実行
uv run python src/app.py PATH

# 統計モード（デバッグ用）
uv run python src/app.py --stats PATH
```

### テスト

```bash
# 全テスト実行（並列）
uv run pytest

# 単一テストファイル実行
uv run pytest tests/test_core.py

# 特定テスト実行
uv run pytest tests/test_core.py::test_function_name

# カバレッジレポート
# テスト実行時に自動生成 → reports/coverage/
```

### コード品質

```bash
# 型チェック（3つのツール）
uv run mypy src/
uv run pyright src/
uv run ty check src/

# リンター
uv run ruff check src/

# フォーマッター
uv run ruff format src/
```

## アーキテクチャ

```
src/
├── app.py              # CLI エントリーポイント（docopt）
└── dupdel/
    ├── __init__.py     # パッケージ初期化・公開 API
    ├── constants.py    # 定数・型定義・グローバル状態
    ├── core.py         # ファイル比較コアロジック（並列処理）
    ├── ui.py           # UI/インタラクション処理（enlighten）
    ├── cache.py        # キャッシュ管理（SQLite）
    └── text.py         # テキスト処理ユーティリティ

tests/
├── test_app.py         # CLI テスト
├── test_core.py        # コアロジックテスト
├── test_ui.py          # UI テスト
├── test_cache.py       # キャッシュテスト
├── test_text.py        # テキスト処理テスト
└── test_typecheck.py   # 型チェックテスト

reports/                # テスト実行時に自動生成（.gitignore 対象）
├── pytest.html         # HTML テストレポート
└── coverage/           # カバレッジレポート
```

### 主要な型

- `FileInfo` - 重複候補のファイル情報（dataclass）
- `DupCand` - 重複候補ペア（古いファイル, 新しいファイル）
- `PrecomputedFileInfo` - 事前計算済みファイル情報（比較処理用）

### 処理フロー

1. `list_files()` - 対象ディレクトリのファイル一覧を取得
2. `precompute_file_info()` - ファイル情報を事前計算
3. `find_dup_candidates_parallel()` - 並列処理で重複候補を検出
4. `run_interactive()` - インタラクティブに削除確認

## コーディング規約

### 型安全性

- **dataclass 優先**: 構造化データには `dataclass` を使用する
- **`dict[str, Any]` 禁止**: 型が不明な辞書は使わない。代わりに dataclass や TypedDict を使う
- **Union 型の適切な使用**: `| None` は戻り値が存在しない可能性がある場合にのみ使用

```python
# 良い例
@dataclass
class FileInfo:
    path: str
    size: int

# 悪い例
FileInfo = dict[str, Any]
```

### パス操作

- `pathlib.Path` を使用する
- `os.walk` は引き続き使用可（`pathlib` に直接の代替がないため）

### コールバック

- `Callable[[int], None] | None` パターンは適切に使用可能

### コードスタイル

- **空文字チェック**: `not s` を使用（`s == ""` ではなく）
- **例外処理**: `except Exception` は避け、具体的な例外を指定
- **入力正規化**: ユーザー入力は取得関数内で `.strip().lower()` を適用し、呼び出し側での処理を不要にする
- **assert 禁止**: 本番コードで `assert` を使用しない。明示的な `if` チェックを使用する

### インポート

- **collections.abc 優先**: `Callable`, `Iterator` 等は `collections.abc` からインポート（PEP 585）

### 戻り値の型

- **複数の値を返す場合**: 2要素以上の意味のある組み合わせは dataclass を使用
- **単純なペア**: `tuple[str, str]` のような同種データのペアは tuple のまま許容

### 内部ユーティリティ関数

- テストやデバッグで使用する内部関数は `_` プレフィックスで明示
- 未使用に見える `_` プレフィックス関数でも、テストで使用している場合は削除しない

### Protocol の使用

- 外部ライブラリとの相互作用が多い場合は Protocol 化を避ける
- `Callable` で十分表現できる場合は Protocol 化しない

### リファクタリング方針

以下の改善は、メリットがデメリットを上回らないため実施しない:

- **マジックナンバーの過度な定数化**: 変更頻度が低く関数内で完結する値は局所性を優先
- **過剰な抽象化**: 類似コードでも目的が異なる場合は統一しない
- **PEP 8 厳格適用**: bar_format 等の長い文字列は可読性を優先

### 調査時の判断基準

リファクタリング調査では、以下の基準で改善の要否を判断する:

1. **影響範囲**: 変更箇所が2-3箇所のみなら統一・抽象化のメリットは限定的
2. **コスト対効果**: 改善コスト（コード変更量、テスト修正）がメリットを上回らないこと
3. **局所性**: 関数内で完結する値は定数化より局所性を優先
4. **既存ガイドライン**: CLAUDE.md の既存方針との整合性を確認

### my_lib 活用ガイドライン

| モジュール                 | 活用判断 | 理由                               |
| -------------------------- | -------- | ---------------------------------- |
| `my_lib.sqlite_util`       | 不要     | ローカルツールにはオーバースペック |
| `my_lib.graceful_shutdown` | 不要     | enlighten との互換性問題           |
| `my_lib.config`            | 不要     | シンプル CLI ツール設計に反する    |

## 開発ワークフロー規約

### コミット時の注意

- 今回のセッションで作成し、プロジェクトが機能するのに必要なファイル以外は git add しないこと
- 気になる点がある場合は追加して良いか質問すること

### バグ修正の原則

- 憶測に基づいて修正しないこと
- 必ず原因を論理的に確定させた上で修正すること
- 「念のため」の修正でコードを複雑化させないこと

### コード修正時の確認事項

- 関連するテストも修正すること
- 関連するドキュメントも更新すること
- mypy, pyright, ty がパスすることを確認すること

### リリース時の注意

- タグを打つ際は `CHANGELOG.md` を更新すること
- 変更内容を適切なカテゴリ（Added, Changed, Fixed, Removed 等）に分類して記載する
