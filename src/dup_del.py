#!/usr/bin/env python3

"""
ファイル名が似ているファイルを削除するスクリプトです．

Usage:
  dup_del.py [--stats] PATH

Options:
  PATH      チェック対象のフォルダ
  --stats   フォルダ毎の質問リスト数を表示（デバッグ用）
"""

import difflib
import multiprocessing as mp
import os
import re
import shutil
import sys
import threading
import unicodedata
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import enlighten
from docopt import docopt

# 定数
SIZE_TH = 200 * 1024 * 1024
MATCH_TH = 0.85
IGNORE_PAT = r"[\d_ 　🈑🈞字再前後\[\]]"

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

# 型エイリアス
FileInfo = dict[str, Any]
DupCand = list[FileInfo]

# グローバル停止フラグ
shutdown_event = threading.Event()


def get_term_width() -> int:
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


def blinking_input(prompt: str = "") -> str:
    """点滅するアンダースコアカーソル付きで入力を待つ"""
    # プロンプトと点滅する _ を表示
    sys.stdout.write(f"{prompt}{BLINK_ON}_{COLOR_RESET}")
    sys.stdout.flush()

    # ステータスバーとの間に空行を作る
    sys.stdout.write("\n")
    sys.stdout.flush()

    # カーソルを1行上に戻し、プロンプトの末尾（_ の位置）に移動
    visible_width = get_visible_width(prompt)
    sys.stdout.write("\033[1A")  # 1行上へ
    if visible_width > 0:
        sys.stdout.write(f"\033[{visible_width}C")  # 右へ移動（_ の位置）
    sys.stdout.flush()

    # 入力を取得（ユーザーの入力が _ を上書きする）
    return input()


@dataclass
class PrecomputedFileInfo:
    """事前計算済みファイル情報"""

    path: str
    dir_path: str  # ファイルのディレクトリパス
    name: str  # ファイル名
    rel_name: str  # 相対パス
    normalized: str  # 正規化済み名前（IGNORE_PAT 除去）
    size: int
    mtime: float
    index: int


def count_valid_comparisons(file_infos: list[PrecomputedFileInfo]) -> int:
    """有効な比較ペア数をカウント（同じディレクトリのみ）"""
    # ディレクトリごとのファイル数をカウント
    dir_counts = Counter(info.dir_path for info in file_infos)

    # 各ディレクトリ内の比較ペア数を合計: n*(n-1)/2
    total = sum(count * (count - 1) // 2 for count in dir_counts.values())
    return total


def precompute_file_info(
    file_path_list: list[str], dir_path: str, manager: enlighten.Manager | None = None
) -> list[PrecomputedFileInfo]:
    """ファイル情報を事前計算"""
    result = []
    progress_bar = None
    if manager is not None:
        progress_bar = manager.counter(
            total=len(file_path_list),
            desc="⚙️  前処理",
            unit="件",
            bar_format="{desc}{desc_pad}{percentage:3.0f}%|{bar}| {count:,d}/{total:,d} {unit} [{elapsed}<{eta}]",
        )

    for i, path in enumerate(file_path_list):
        if shutdown_event.is_set():
            break
        try:
            name = os.path.basename(path)
            stat = os.stat(path)
            result.append(
                PrecomputedFileInfo(
                    path=path,
                    dir_path=os.path.dirname(path),
                    name=name,
                    rel_name=os.path.relpath(path, dir_path),
                    normalized=re.sub(IGNORE_PAT, "", name),
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    index=i + 1,
                )
            )
        except OSError:
            pass
        finally:
            if progress_bar is not None:
                progress_bar.update()

    if progress_bar is not None:
        progress_bar.close()

    return result


def _compare_pair(
    info1: PrecomputedFileInfo, info2: PrecomputedFileInfo, match_th: float
) -> DupCand | None:
    """2つのファイルを比較し、重複候補であれば返す"""
    # 長さベースの事前フィルタ
    len1, len2 = len(info1.normalized), len(info2.normalized)
    if len1 > 0 and len2 > 0:
        length_ratio = min(len1, len2) / max(len1, len2)
        if length_ratio < 0.5:
            return None

    # quick_ratio による高速フィルタ
    sm_judge = difflib.SequenceMatcher(None, info1.normalized, info2.normalized)
    if sm_judge.quick_ratio() <= match_th:
        return None
    if sm_judge.ratio() <= match_th:
        return None

    # 前後チェック
    if has_zengo_diff(info1.name, info2.name):
        return None

    # 話数チェック
    if has_episode_number_diff(info1.name, info2.name):
        return None

    # サイズ差チェック
    max_size = max(info1.size, info2.size)
    if max_size > 0:
        size_diff_ratio = 100 * abs(info1.size - info2.size) / max_size
        if size_diff_ratio >= 40:
            return None

    # 重複候補を作成（古い方を先に）
    if info1.mtime <= info2.mtime:
        older, newer = info1, info2
    else:
        older, newer = info2, info1

    sm = difflib.SequenceMatcher(None, older.name, newer.name)

    return [
        {
            "path": older.path,
            "name": older.rel_name,
            "size": older.size,
            "mtime": older.mtime,
            "index": older.index,
            "sm": sm,
        },
        {
            "path": newer.path,
            "name": newer.rel_name,
            "size": newer.size,
            "mtime": newer.mtime,
            "index": newer.index,
            "sm": sm,
        },
    ]


# ワーカープロセス用のグローバル変数
_worker_file_infos: list[PrecomputedFileInfo] = []
_worker_n: int = 0


def _init_worker(file_infos: list[PrecomputedFileInfo]) -> None:
    """ワーカープロセスの初期化（データを一度だけ転送）"""
    global _worker_file_infos, _worker_n
    _worker_file_infos = file_infos
    _worker_n = len(file_infos)


def _worker_compare_range(args: tuple[int, int, float]) -> tuple[list[DupCand], int]:
    """ワーカー: 指定範囲のファイルを全後続ファイルと比較"""
    start_idx, end_idx, match_th = args
    results: list[DupCand] = []
    valid_comparison_count = 0

    for i in range(start_idx, end_idx):
        info1 = _worker_file_infos[i]
        for j in range(i + 1, _worker_n):
            info2 = _worker_file_infos[j]
            # 同じディレクトリのファイルのみ比較
            if info1.dir_path != info2.dir_path:
                continue
            valid_comparison_count += 1
            result = _compare_pair(info1, info2, match_th)
            if result is not None:
                results.append(result)

    return results, valid_comparison_count


def find_dup_candidates_parallel(
    file_infos: list[PrecomputedFileInfo],
    progress_callback: Any,
    num_workers: int | None = None,
) -> list[DupCand]:
    """並列処理で重複候補を探す"""
    n = len(file_infos)
    if n < 2:
        return []

    if num_workers is None:
        num_workers = min(mp.cpu_count(), 8)

    # タスクを細かく分割（0.5%刻みで進捗更新、最低200タスク）
    total_comparisons = n * (n - 1) // 2
    min_tasks = max(200, num_workers * 50)
    # 1タスクあたり最大50万比較に制限（大規模データでも頻繁に更新）
    max_comparisons_per_task = 500_000
    target_per_task = min(max_comparisons_per_task, max(1, total_comparisons // min_tasks))

    # 開始インデックスごとの比較数: n-1, n-2, ..., 1
    tasks: list[tuple[int, int, float]] = []
    current_start = 0
    current_count = 0

    for i in range(n - 1):
        current_count += n - 1 - i
        if current_count >= target_per_task or i == n - 2:
            tasks.append((current_start, i + 1, MATCH_TH))
            current_start = i + 1
            current_count = 0

    if not tasks:
        tasks.append((0, n - 1, MATCH_TH))

    all_results: list[DupCand] = []

    # initializer でファイル情報を一度だけ各ワーカーに転送
    with ProcessPoolExecutor(
        max_workers=num_workers,
        initializer=_init_worker,
        initargs=(file_infos,),
    ) as executor:
        futures = {executor.submit(_worker_compare_range, task): task for task in tasks}

        for future in as_completed(futures):
            if shutdown_event.is_set():
                executor.shutdown(wait=False, cancel_futures=True)
                break

            results, comparisons = future.result()
            all_results.extend(results)

            # 進捗コールバック
            progress_callback(comparisons, len(results))

    return all_results


def get_mtime_safe(path: str) -> float:
    """ファイルの更新時刻を取得（エラー時は0を返す）"""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


def list_file(dir_path: str, manager: enlighten.Manager) -> list[str]:
    counter = manager.counter(
        desc="📂 ファイル一覧",
        unit="件",
    )

    file_path_list = []
    for root, dirs, files in os.walk(dir_path):
        # 隠しディレクトリをスキップ
        dirs[:] = [d for d in dirs if not d.startswith(".")]

        if shutdown_event.is_set():
            break
        for name in files:
            if shutdown_event.is_set():
                break
            # 隠しファイルをスキップ
            if name.startswith("."):
                continue
            path = os.path.join(root, name)
            try:
                if os.path.isfile(path):
                    file_path_list.append(path)
                    counter.update()
            except OSError:
                continue

    if not shutdown_event.is_set():
        counter.desc = "📂 ソート中"
        counter.refresh()
        file_path_list.sort(key=get_mtime_safe)

    counter.close()
    return file_path_list


def print_diff_text(text: str, sm: difflib.SequenceMatcher, mode: int) -> None:
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        s = text[i1:i2] if mode == 0 else text[j1:j2]

        if tag == "equal":
            print(s, end="")
        elif re.fullmatch(IGNORE_PAT + "+", s):
            print(f"{COLOR_DIM}{s}{COLOR_RESET}", end="")
        elif tag == "delete":
            print(f"{COLOR_DIFF_DELETE}{s}{COLOR_RESET}", end="")
        elif tag == "replace":
            print(f"{COLOR_DIFF_REPLACE}{s}{COLOR_RESET}", end="")
        elif tag == "insert":
            print(f"{COLOR_DIFF_INSERT}{s}{COLOR_RESET}", end="")
    print()


def print_dup_cand(dup_cand: DupCand, index: int, total: int) -> None:
    ratio = round(dup_cand[0]["sm"].ratio() * 100)
    ratio_color = COLOR_SUCCESS if ratio >= 95 else COLOR_WARNING if ratio >= 90 else COLOR_DIM

    print(f"\n{'─' * get_term_width()}")
    print(f"[{index:3d}/{total:3d}] {ratio_color}📊 類似度: {ratio}%{COLOR_RESET}")

    size_diff = abs(dup_cand[0]["size"] - dup_cand[1]["size"])
    max_size = max(dup_cand[0]["size"], dup_cand[1]["size"])
    size_ratio = 100 * size_diff / max_size if max_size > 0 else 0

    size_color = COLOR_ERROR if size_diff > SIZE_TH else COLOR_DIM
    print(f"        {size_color}📐 サイズ差: {size_diff / 1024 / 1024:.1f} MB ({size_ratio:.1f}%){COLOR_RESET}")

    print(f"\n  📁 古: ", end="")
    print_diff_text(dup_cand[0]["name"], dup_cand[0]["sm"], 0)
    print(f"  📄 新: ", end="")
    print_diff_text(dup_cand[1]["name"], dup_cand[1]["sm"], 1)


def has_zengo_diff(name1: str, name2: str) -> bool:
    """「前」と「後」の差分があるかチェック"""
    sm = difflib.SequenceMatcher(None, name1, name2)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace":
            s1 = name1[i1:i2]
            s2 = name2[j1:j2]
            if ("前" in s1 and "後" in s2) or ("後" in s1 and "前" in s2):
                return True
    return False


def expand_to_digit_group(name: str, start: int, end: int) -> tuple[int, int]:
    """差分位置を数字グループ全体に拡張"""
    while start > 0 and name[start - 1].isdigit():
        start -= 1
    while end < len(name) and name[end].isdigit():
        end += 1
    return start, end


def has_episode_number_diff(name1: str, name2: str) -> bool:
    """話数のような数字差分があるかチェック（例：第1話 vs 第2話、#01 vs #02）"""
    sm = difflib.SequenceMatcher(None, name1, name2, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace":
            if not any(c.isdigit() for c in name1[i1:i2]):
                continue
            if not any(c.isdigit() for c in name2[j1:j2]):
                continue

            exp_start1, exp_end1 = expand_to_digit_group(name1, i1, i2)
            exp_start2, exp_end2 = expand_to_digit_group(name2, j1, j2)

            exp_s1 = name1[exp_start1:exp_end1]
            exp_s2 = name2[exp_start2:exp_end2]

            if exp_s1.isdigit() and exp_s2.isdigit():
                before_digits = 0
                for c in reversed(name1[:exp_start1]):
                    if c.isdigit():
                        before_digits += 1
                    else:
                        break

                after_digits = 0
                for c in name1[exp_end1:]:
                    if c.isdigit():
                        after_digits += 1
                    else:
                        break

                if before_digits <= 1 and after_digits <= 1:
                    return True
    return False


def list_dup_cand(dir_path: str, manager: enlighten.Manager) -> list[DupCand]:
    # ステータスバー（上から順に表示されるよう、下から作成）
    tool_status = manager.status_bar(
        status_format="🔍 dupdel:{fill}{status}{fill}",
        color="bold_bright_white_on_lightslategray",
        justify=enlighten.Justify.CENTER,
        status="重複ファイルを調べています...",
    )
    dir_status = manager.status_bar(
        status_format=f"📂 対象: {dir_path}",
        justify=enlighten.Justify.LEFT,
    )

    # メインスレッドでファイル一覧を取得
    file_path_list = list_file(dir_path, manager)

    if shutdown_event.is_set():
        tool_status.close()
        dir_status.close()
        return []

    # ファイル情報を事前計算（プログレスバー付き）
    file_infos = precompute_file_info(file_path_list, dir_path, manager)

    total_files = len(file_infos)
    if total_files < 2:
        tool_status.close()
        dir_status.close()
        return []

    # 有効な比較ペア数をカウント（同じディレクトリまたは親子関係のみ）
    tool_status.update(status="比較対象をカウント中...")
    total_comparisons = count_valid_comparisons(file_infos)

    if total_comparisons == 0:
        tool_status.update(status="✨ 比較対象がありませんでした")
        tool_status.close()
        dir_status.close()
        return []

    tool_status.update(status="重複ファイルを調べています...")

    # ステータスライン（下から順に積み上げ: 下に来るものから作成）
    compare_bar = manager.counter(
        total=total_comparisons,
        desc="🔍 比較",
        unit="組",
        bar_format="{desc}{desc_pad}{percentage:3.0f}%|{bar}| {count:,d}/{total:,d} {unit} [{elapsed}<{eta}]",
    )
    question_counter = manager.counter(
        desc="❓ 質問リスト",
        unit="件",
        counter_format="{desc}{desc_pad}{count:,d} {unit}",
    )
    delete_counter = manager.counter(
        desc="🗑️  削除候補",
        unit="件",
        counter_format="{desc}{desc_pad}{count:,d} {unit}",
    )

    pending_questions: list[DupCand] = []
    dup_cand_list: list[DupCand] = []
    qa_bar: enlighten.Counter | None = None

    def progress_callback(comparisons: int, found: int) -> None:
        """並列処理からの進捗コールバック"""
        if shutdown_event.is_set():
            return
        compare_bar.count = compare_bar.count + comparisons
        compare_bar.refresh()
        question_counter.count = question_counter.count + found
        question_counter.refresh()

    try:
        # フェーズ1: 並列で比較処理（完了まで待機）
        num_workers = min(mp.cpu_count(), 8)
        pending_questions = find_dup_candidates_parallel(
            file_infos, progress_callback, num_workers
        )

        # 最終進捗を表示
        compare_bar.count = total_comparisons
        compare_bar.refresh()
        question_counter.count = len(pending_questions)
        question_counter.refresh()

        if shutdown_event.is_set():
            return dup_cand_list

        # 質問がない場合
        if not pending_questions:
            tool_status.update(status="✨ 重複候補は見つかりませんでした")
            return dup_cand_list

        # フェーズ2: 質問に回答（Q&Aプログレスバー表示）
        tool_status.update(status="🤔 削除して良いか確認お願いします")
        question_counter.close()
        qa_bar = manager.counter(
            total=len(pending_questions),
            desc="💬 回答",
            unit="件",
            bar_format="{desc}{desc_pad}{percentage:3.0f}%|{bar}| {count:,d}/{total:,d} {unit} [{elapsed}<{eta}]",
        )

        for i, dup_cand in enumerate(pending_questions, 1):
            if shutdown_event.is_set():
                break

            print_dup_cand(dup_cand, i, len(pending_questions))

            print()  # ステータスバーとの間に空行
            ans = blinking_input(f"{COLOR_TITLE}🤔 同一？(後者が削除候補) [y/n/q]: {COLOR_RESET}")

            assert qa_bar is not None
            qa_bar.update()
            if ans.lower() == "y":
                dup_cand_list.append(dup_cand)
                delete_counter.count = len(dup_cand_list)
                delete_counter.refresh()
                print(f"{COLOR_SUCCESS}✅ 削除候補に追加{COLOR_RESET}")
            elif ans.lower() == "q":
                break
            else:
                print(f"{COLOR_DIM}⏭️  スキップ{COLOR_RESET}")

            print()  # ステータスバーとの間に空行

    except KeyboardInterrupt:
        if handle_interrupt(manager):
            shutdown_event.set()
        else:
            raise

    finally:
        tool_status.close()
        dir_status.close()
        compare_bar.close()
        try:
            question_counter.close()
        except Exception:
            pass
        if qa_bar is not None:
            qa_bar.close()
        delete_counter.close()

    return dup_cand_list


def exec_delete(dup_cand_list: list[DupCand], trash_dir_path: str, manager: enlighten.Manager) -> None:
    if not dup_cand_list:
        print(f"\n{COLOR_DIM}📭 削除候補がありません{COLOR_RESET}")
        return

    os.makedirs(trash_dir_path, exist_ok=True)
    process_all = False

    progress = manager.counter(
        total=len(dup_cand_list),
        desc="🗑️  削除確認",
        unit="件",
    )

    deleted_count = 0

    for dup_cand in dup_cand_list:
        progress.update()
        print_dup_cand(dup_cand, progress.count, len(dup_cand_list))

        src_path = dup_cand[1]["path"]

        if not os.path.isfile(src_path):
            print(f"{COLOR_WARNING}⚠️  ファイルが見つかりません{COLOR_RESET}")
            continue

        should_delete = process_all
        if not process_all:
            sys.stdout.write("\n")  # ステータスバーとの間に空行
            sys.stdout.flush()
            ans = blinking_input(f"{COLOR_ERROR}🗑️  後者を削除しますか？[y/n/a]: {COLOR_RESET}").lower()
            should_delete = ans in ("y", "a")
            if ans == "a":
                process_all = True
                print(f"{COLOR_WARNING}⚡ 以降すべて削除します{COLOR_RESET}")

        if should_delete:
            dst_path = os.path.join(trash_dir_path, os.path.basename(src_path))
            shutil.move(src_path, dst_path)
            deleted_count += 1
            print(f"{COLOR_SUCCESS}🗑️  削除しました{COLOR_RESET}")

    progress.close()
    print(f"\n{'─' * 50}")
    print(f"{COLOR_SUCCESS}🎉 完了: {deleted_count} 件のファイルを削除しました{COLOR_RESET}")


def handle_interrupt(manager: enlighten.Manager | None = None) -> bool:
    """Ctrl-C が押された時の処理。終了する場合は True を返す"""
    try:
        sys.stdout.write("\n\n")  # ステータスバーとの間に空行
        sys.stdout.flush()
        ans = blinking_input(f"{COLOR_WARNING}⏸️  中断しますか？ [y/N]: {COLOR_RESET}").strip().lower()
        if ans == "y":
            print(f"{COLOR_DIM}👋 終了処理中...{COLOR_RESET}")
            shutdown_event.set()
            if manager:
                manager.stop()
            return True
        print(f"{COLOR_DIM}▶️  継続します{COLOR_RESET}")
        return False
    except (KeyboardInterrupt, EOFError):
        print(f"\n{COLOR_DIM}👋 終了処理中...{COLOR_RESET}")
        shutdown_event.set()
        if manager:
            manager.stop()
        return True


def run_stats_mode(dir_path: str) -> None:
    """フォルダ毎の質問リスト数を表示（デバッグ用）"""
    print(f"📊 統計モード: {dir_path}")
    print()

    # ファイル一覧を取得
    print("📂 ファイル一覧を取得中...")
    file_path_list = []
    for root, dirs, files in os.walk(dir_path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if name.startswith("."):
                continue
            path = os.path.join(root, name)
            if os.path.isfile(path):
                file_path_list.append(path)

    print(f"   合計: {len(file_path_list)} ファイル")
    print()

    # ファイル情報を事前計算
    print("⚙️  ファイル情報を計算中...")
    file_infos = precompute_file_info(file_path_list, dir_path, manager=None)

    # ディレクトリ毎にグループ化
    dir_to_infos: dict[str, list[PrecomputedFileInfo]] = {}
    for info in file_infos:
        if info.dir_path not in dir_to_infos:
            dir_to_infos[info.dir_path] = []
        dir_to_infos[info.dir_path].append(info)

    print(f"   合計: {len(dir_to_infos)} ディレクトリ")
    print()

    # ディレクトリ毎に重複候補を数える
    print("🔍 重複候補をカウント中...")
    results: list[tuple[str, int, int, int]] = []  # (dir, file_count, pairs, candidates)

    # ファイル数が多い順にソート（進捗がわかりやすいように）
    sorted_dirs = sorted(dir_to_infos.items(), key=lambda x: len(x[1]), reverse=True)
    processed = 0

    for dir_path_key, infos in sorted_dirs:
        processed += 1
        if len(infos) < 2:
            continue

        rel_path = os.path.relpath(dir_path_key, dir_path)
        pairs_total = len(infos) * (len(infos) - 1) // 2
        print(f"   [{processed}/{len(dir_to_infos)}] {rel_path} ({len(infos)} files, {pairs_total} pairs)...", end="", flush=True)

        candidates = 0
        pairs_checked = 0
        for i in range(len(infos)):
            for j in range(i + 1, len(infos)):
                pairs_checked += 1
                result = _compare_pair(infos[i], infos[j], MATCH_TH)
                if result is not None:
                    candidates += 1

        print(f" → {candidates} 候補")

        if candidates > 0:
            results.append((rel_path, len(infos), pairs_checked, candidates))

    # 候補数でソート
    results.sort(key=lambda x: x[3], reverse=True)

    col_width = 40
    print()
    print("=" * 80)
    print(f"{pad_to_width('ディレクトリ', col_width)} {'ファイル数':>10} {'比較ペア':>10} {'候補数':>10}")
    print("=" * 80)

    total_candidates = 0
    for rel_path, file_count, pairs, candidates in results:
        total_candidates += candidates
        # 長いパスは表示幅で省略
        display_path = rel_path
        while get_visible_width(display_path) > col_width - 3:
            display_path = display_path[1:]
        if display_path != rel_path:
            display_path = "..." + display_path
        print(f"{pad_to_width(display_path, col_width)} {file_count:>10} {pairs:>10} {candidates:>10}")

    print("=" * 80)
    print(f"{pad_to_width('合計', col_width)} {'':>10} {'':>10} {total_candidates:>10}")


def main() -> None:
    assert __doc__ is not None
    args = docopt(__doc__)

    target_dir_path = args["PATH"]

    # 統計モード
    if args["--stats"]:
        run_stats_mode(target_dir_path)
        return

    manager = enlighten.Manager()

    try:
        dup_cand_list = list_dup_cand(target_dir_path, manager)

        if shutdown_event.is_set():
            print(f"\n{COLOR_WARNING}⏹️  中断しました{COLOR_RESET}")
            return

        if dup_cand_list:
            print(f"\n{COLOR_WARNING}{'─' * 50}{COLOR_RESET}")
            print(f"{COLOR_WARNING}⚠️  削除の最終確認{COLOR_RESET}")
            print(f"{COLOR_WARNING}{'─' * 50}{COLOR_RESET}")
            exec_delete(dup_cand_list, TRASH_DIR, manager)
        else:
            print(f"\n{COLOR_DIM}✨ 重複候補は見つかりませんでした{COLOR_RESET}")

    except KeyboardInterrupt:
        if handle_interrupt(manager):
            print(f"\n{COLOR_WARNING}⏹️  中断しました{COLOR_RESET}")
            sys.exit(130)
    finally:
        manager.stop()


if __name__ == "__main__":
    main()
