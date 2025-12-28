# 🗑️ dupdel

[![Test Status](https://github.com/kimata/dupdel/actions/workflows/test.yml/badge.svg)](https://github.com/kimata/dupdel/actions/workflows/test.yml)
[![Test Report](https://img.shields.io/badge/test-report-blue)](https://kimata.github.io/dupdel/report.html)
[![Coverage Report](https://img.shields.io/badge/coverage-report-blue)](https://kimata.github.io/dupdel/coverage/)

類似したファイル名を持つ重複ファイルの削除を支援するツール

## 📋 概要

同じディレクトリ内にある、名前が似ているファイルを検出し、対話的に削除できます。
録画ファイルなど、同一番組の重複ファイルを整理するのに便利です。

### 主な特徴

- 🔍 **類似ファイル名検出** - ファイル名の類似度を計算して重複候補を抽出
- 💬 **対話的な削除確認** - 1件ずつ確認しながら削除候補を選択
- 🎨 **差分ハイライト** - ファイル名の差異をカラーで表示
- ⚡ **並列処理** - 大量のファイルも高速に比較
- 🛡️ **安全な削除** - ファイルはゴミ箱に移動（完全削除ではない）
- ⏸️ **中断・再開対応** - Ctrl-C で安全に中断可能

### 検出ロジック

以下の条件を満たすファイルペアを重複候補として検出します：

- 同じディレクトリ内に存在
- ファイル名の類似度が 85% 以上
- サイズ差が 40% 未満
- 話数の違い（第1話 vs 第2話など）は除外
- 「前編」「後編」の違いは除外

## 🖥️ 動作環境

Python 3.10 以上が必要です。

## 🚀 セットアップ

### uv を使用（推奨）

```bash
# uv のインストール（未インストールの場合）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 依存関係のインストール
uv sync
```

## 💻 実行方法

```bash
# 基本的な使い方
uv run python src/app.py /path/to/directory

# デバッグモード（フォルダ毎の候補数を表示）
uv run python src/app.py --stats /path/to/directory
```

### 操作方法

重複候補が見つかると、以下のように表示されます：

```
───────────────────────────────────────────────────
[  1/10] 📊 類似度: 92%
        📐 サイズ差: 12.3 MB (0.4%)

  📁 古: recordings/番組名 第1話.ts
  📄 新: recordings/[無]番組名 第1話.ts

🤔 同一？(後者が削除候補) [y/n/q]:
```

- `y` - 削除候補に追加
- `n` - スキップ
- `q` - 質問を終了して削除確認へ

削除確認フェーズでは：

- `y` - 削除を実行
- `n` - スキップ
- `a` - 以降すべて削除

### 削除先

削除されたファイルは `/storage/.recycle` に移動されます（完全削除ではありません）。

## 📁 コード構造

```
src/
├── app.py              # エントリポイント
└── dupdel/
    ├── __init__.py     # パッケージ初期化
    ├── constants.py    # 定数・型定義
    ├── text.py         # テキスト表示ユーティリティ
    ├── core.py         # ファイル比較コアロジック
    └── ui.py           # UI/インタラクション
```

## 📝 ライセンス

Apache License Version 2.0

---

<div align="center">

[🐛 Issue 報告](https://github.com/kimata/dupdel/issues)

</div>
