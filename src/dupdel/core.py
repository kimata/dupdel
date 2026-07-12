"""ファイル比較コアロジック"""

import difflib
import multiprocessing as mp
import os
import re
import signal
from collections import Counter, defaultdict
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


def _normalize_name(name: str) -> str:
    """比較用にファイル名を正規化する

    数字や記号のみの名前（例: 日付だけのファイル名）は正規化で情報がほぼ消えてしまい、
    無関係なファイル同士が完全一致扱いになるため、生の名前をそのまま使う。
    """
    normalized = re.sub(IGNORE_PAT, "", name)
    if len(normalized) < 4:  # 正規化後に情報がほぼ残らない場合
        return name
    return normalized


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
                    normalized=_normalize_name(name),
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
    """「前」と「後」の差分（前編/後編など）があるかチェック

    「午前」「午後」のような時刻表現の差分は前編/後編ではないため対象外。
    """
    sm = difflib.SequenceMatcher(None, name1, name2)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace":
            s1 = name1[i1:i2]
            s2 = name2[j1:j2]
            if ("前" in s1 and "後" in s2) or ("後" in s1 and "前" in s2):
                # 差分の前後1文字を含めて双方が「午前」「午後」なら時刻表現とみなす
                ctx1 = name1[max(0, i1 - 1) : i2 + 1]
                ctx2 = name2[max(0, j1 - 1) : j2 + 1]
                if ("午前" in ctx1 or "午後" in ctx1) and ("午前" in ctx2 or "午後" in ctx2):
                    continue
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
_worker_groups: list[list[PrecomputedFileInfo]] = []


def _init_worker(
    groups: list[list[PrecomputedFileInfo]],
) -> None:  # pragma: no cover (別プロセスで実行)
    """ワーカープロセスの初期化（データを一度だけ転送）"""
    global _worker_groups
    # 中断はメインプロセスが制御するため、ワーカーは SIGINT を無視する
    # （端末の Ctrl-C はプロセスグループ全体に届くため、放置するとワーカーが即死する）
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    _worker_groups = groups


def _worker_compare_range(
    args: tuple[int, int, int, float],
) -> tuple[list[DupCand], int]:  # pragma: no cover (別プロセスで実行)
    """ワーカー: グループ内の指定範囲のファイルを全後続ファイルと比較"""
    group_idx, start_idx, end_idx, match_th = args
    infos = _worker_groups[group_idx]
    group_size = len(infos)
    results: list[DupCand] = []
    comparison_count = 0

    for i in range(start_idx, end_idx):
        info1 = infos[i]
        for j in range(i + 1, group_size):
            comparison_count += 1
            result = compare_pair(info1, infos[j], match_th)
            if result is not None:
                results.append(result)

    return results, comparison_count


def find_dup_candidates_parallel(
    file_infos: list[PrecomputedFileInfo],
    progress_callback: Callable[[int, int], None],
    num_workers: int | None = None,
) -> list[DupCand]:
    """並列処理で重複候補を探す（同じディレクトリ内のみ比較）

    Ctrl-C で中断された場合は shutdown_event をセットし、
    それまでに見つかった候補を返す。
    """
    # 比較は同一ディレクトリ内のみなので、ディレクトリ毎にグループ化してから
    # タスク分割する（ツリー全体の総当たり走査を避ける）
    by_dir: defaultdict[str, list[PrecomputedFileInfo]] = defaultdict(list)
    for info in file_infos:
        by_dir[info.dir_path].append(info)
    groups = [infos for infos in by_dir.values() if len(infos) >= 2]

    total_comparisons = sum(len(g) * (len(g) - 1) // 2 for g in groups)
    if total_comparisons == 0:
        return []

    if num_workers is None:
        num_workers = min(mp.cpu_count(), 8)

    # タスクを細かく分割（0.5%刻みで進捗更新、最低200タスク）
    min_tasks = max(200, num_workers * 50)
    # 1タスクあたりの比較数を制限（進捗更新の頻度と Ctrl-C の応答性を確保）
    max_comparisons_per_task = 100_000
    target_per_task = min(max_comparisons_per_task, max(1, total_comparisons // min_tasks))

    # グループ毎に、開始インデックスの範囲でタスクを切り出す
    tasks: list[tuple[int, int, int, float]] = []
    for group_idx, infos in enumerate(groups):
        group_size = len(infos)
        current_start = 0
        current_count = 0
        for i in range(group_size - 1):
            current_count += group_size - 1 - i
            if current_count >= target_per_task or i == group_size - 2:
                tasks.append((group_idx, current_start, i + 1, MATCH_TH))
                current_start = i + 1
                current_count = 0

    all_results: list[DupCand] = []

    # スキャン中の SIGINT は shutdown_event をセットするだけにする。
    # KeyboardInterrupt 例外で Executor 内部の通信を巻き戻すと
    # シャットダウンがデッドロックすることがあるため、例外は使わない。
    def _on_sigint(_signum: int, _frame: object) -> None:  # pragma: no cover (シグナル経由で実行)
        shutdown_event.set()

    original_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _on_sigint)

    # initializer でファイル情報を一度だけ各ワーカーに転送
    executor = ProcessPoolExecutor(
        max_workers=num_workers,
        initializer=_init_worker,
        initargs=(groups,),
    )
    try:
        futures = [executor.submit(_worker_compare_range, task) for task in tasks]

        for future in as_completed(futures):
            if shutdown_event.is_set():
                break

            results, comparisons = future.result()
            all_results.extend(results)

            # 進捗コールバック
            progress_callback(comparisons, len(results))
    finally:
        # shutdown は1回だけ呼ぶ（2回呼ぶと cancel_futures フラグが上書きされ、
        # 管理スレッドが残タスクを処理し続けてしまう）
        executor.shutdown(wait=True, cancel_futures=shutdown_event.is_set())
        signal.signal(signal.SIGINT, original_handler)

    # as_completed は完了順のため、結果の順序を決定的にする
    all_results.sort(key=lambda cand: (cand[0].path, cand[1].path))

    return all_results


def _get_mtime_safe(path: str) -> float:
    """ファイルの更新時刻を取得

    エラー時は 0 を返す（読めないファイルは最古扱いとなり、
    ペア内では「古い方」= 削除候補でない側になる）。
    """
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
