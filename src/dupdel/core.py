"""ファイル比較コアロジック"""

import difflib
import multiprocessing as mp
import os
import re
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from .constants import IGNORE_PAT, MATCH_TH, DupCand, FileInfo, shutdown_event


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
    file_path_list: list[str],
    dir_path: str,
    progress_callback: Callable[[int], None] | None = None,
) -> list[PrecomputedFileInfo]:
    """ファイル情報を事前計算"""
    result = []

    for i, path in enumerate(file_path_list):
        if shutdown_event.is_set():
            break
        try:
            p = Path(path)
            stat = p.stat()
            name = p.name
            result.append(
                PrecomputedFileInfo(
                    path=path,
                    dir_path=str(p.parent),
                    name=name,
                    rel_name=str(p.relative_to(dir_path)),
                    normalized=re.sub(IGNORE_PAT, "", name),
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    index=i + 1,
                )
            )
        except OSError:
            pass
        finally:
            if progress_callback is not None:
                progress_callback(1)

    return result


def _has_zengo_diff(name1: str, name2: str) -> bool:
    """「前」と「後」の差分があるかチェック"""
    sm = difflib.SequenceMatcher(None, name1, name2)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace":
            s1 = name1[i1:i2]
            s2 = name2[j1:j2]
            if ("前" in s1 and "後" in s2) or ("後" in s1 and "前" in s2):
                return True
    return False


def _expand_to_digit_group(name: str, start: int, end: int) -> tuple[int, int]:
    """差分位置を数字グループ全体に拡張"""
    while start > 0 and name[start - 1].isdigit():
        start -= 1
    while end < len(name) and name[end].isdigit():
        end += 1
    return start, end


def _find_digit_group_in_range(name: str, start: int, end: int) -> tuple[int, int] | None:
    """指定範囲内の数字を含む数字グループを見つける"""
    # 範囲内で最初の数字を見つける
    digit_pos = -1
    for i in range(start, end):
        if i < len(name) and name[i].isdigit():
            digit_pos = i
            break

    if digit_pos == -1:
        return None

    # その位置から数字グループを拡張
    group_start = digit_pos
    group_end = digit_pos + 1

    while group_start > 0 and name[group_start - 1].isdigit():
        group_start -= 1
    while group_end < len(name) and name[group_end].isdigit():
        group_end += 1

    return group_start, group_end


def _has_episode_number_diff(name1: str, name2: str) -> bool:
    """話数のような数字差分があるかチェック（例：第1話 vs 第2話、#01 vs #02、#11 vs #1）"""
    sm = difflib.SequenceMatcher(None, name1, name2, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace":
            if not any(c.isdigit() for c in name1[i1:i2]):
                continue
            if not any(c.isdigit() for c in name2[j1:j2]):
                continue

            # 差分範囲内の数字を含む数字グループを見つける
            group1 = _find_digit_group_in_range(name1, i1, i2)
            group2 = _find_digit_group_in_range(name2, j1, j2)

            if group1 is None or group2 is None:  # pragma: no cover (数字存在確認後なので到達不可)
                continue

            exp_s1 = name1[group1[0] : group1[1]]
            exp_s2 = name2[group2[0] : group2[1]]

            # 差分を含む数字グループ全体が2桁以下の場合のみエピソード番号と判定
            if len(exp_s1) <= 2 and len(exp_s2) <= 2:
                return True

        elif tag == "delete":
            # 削除された部分に数字が含まれる場合（例: #11 → #1）
            if not any(c.isdigit() for c in name1[i1:i2]):
                continue

            group1 = _find_digit_group_in_range(name1, i1, i2)
            if group1 is None:  # pragma: no cover (数字存在確認後なので到達不可)
                continue

            exp_s1 = name1[group1[0] : group1[1]]

            # 対応する位置の name2 側の数字グループも確認
            exp_start2, exp_end2 = _expand_to_digit_group(name2, j1, j1)
            exp_s2 = name2[exp_start2:exp_end2]

            if (not exp_s2 or exp_s2.isdigit()) and len(exp_s1) <= 2 and len(exp_s2) <= 2:
                return True

        elif tag == "insert":
            # 挿入された部分に数字が含まれる場合（例: #1 → #11）
            if not any(c.isdigit() for c in name2[j1:j2]):
                continue

            group2 = _find_digit_group_in_range(name2, j1, j2)
            if group2 is None:  # pragma: no cover (数字存在確認後なので到達不可)
                continue

            exp_s2 = name2[group2[0] : group2[1]]

            # 対応する位置の name1 側の数字グループも確認
            exp_start1, exp_end1 = _expand_to_digit_group(name1, i1, i1)
            exp_s1 = name1[exp_start1:exp_end1]

            if (not exp_s1 or exp_s1.isdigit()) and len(exp_s1) <= 2 and len(exp_s2) <= 2:
                return True

    return False


def compare_pair(info1: PrecomputedFileInfo, info2: PrecomputedFileInfo, match_th: float) -> DupCand | None:
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
    if _has_zengo_diff(info1.name, info2.name):
        return None

    # 話数チェック
    if _has_episode_number_diff(info1.name, info2.name):
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

    return (
        FileInfo(
            path=older.path,
            name=older.rel_name,
            basename=older.name,
            size=older.size,
            mtime=older.mtime,
            index=older.index,
            sm=sm,
        ),
        FileInfo(
            path=newer.path,
            name=newer.rel_name,
            basename=newer.name,
            size=newer.size,
            mtime=newer.mtime,
            index=newer.index,
            sm=sm,
        ),
    )


# ワーカープロセス用のグローバル変数
_worker_file_infos: list[PrecomputedFileInfo] = []
_worker_n: int = 0


def _init_worker(
    file_infos: list[PrecomputedFileInfo],
) -> None:  # pragma: no cover (別プロセスで実行)
    """ワーカープロセスの初期化（データを一度だけ転送）"""
    global _worker_file_infos, _worker_n
    _worker_file_infos = file_infos
    _worker_n = len(file_infos)


def _worker_compare_range(
    args: tuple[int, int, float],
) -> tuple[list[DupCand], int]:  # pragma: no cover (別プロセスで実行)
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
            result = compare_pair(info1, info2, match_th)
            if result is not None:
                results.append(result)

    return results, valid_comparison_count


def find_dup_candidates_parallel(
    file_infos: list[PrecomputedFileInfo],
    progress_callback: Callable[[int, int], None],
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

    if not tasks:  # pragma: no cover (n>=2でforループが必ず実行されるため到達不可)
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


def _get_mtime_safe(path: str) -> float:
    """ファイルの更新時刻を取得（エラー時は0を返す）"""
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0


def list_files(
    dir_path: str,
    progress_callback: Callable[[int], None] | None = None,
) -> list[str]:
    """ディレクトリ内のファイル一覧を取得（隠しファイル除外）"""
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
            p = Path(root) / name
            try:
                if p.is_file():
                    file_path_list.append(str(p))
                    if progress_callback is not None:
                        progress_callback(1)
            except OSError:
                continue

    return file_path_list


def sort_files_by_mtime(file_path_list: list[str]) -> list[str]:
    """ファイルリストを更新時刻でソート"""
    return sorted(file_path_list, key=_get_mtime_safe)
