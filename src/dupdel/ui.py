"""UI/インタラクション処理"""

import contextlib
import multiprocessing as mp
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import enlighten

from .cache import cache_pair, get_pair_key, init_cache_db, load_cached_pairs
from .constants import (
    BLINK_ON,
    COLOR_DIM,
    COLOR_ERROR,
    COLOR_RESET,
    COLOR_SUCCESS,
    COLOR_TITLE,
    COLOR_WARNING,
    MATCH_TH,
    SIZE_TH,
    TRASH_DIR,
    DirStats,
    DupCand,
    shutdown_event,
)
from .core import (
    PrecomputedFileInfo,
    compare_pair,
    count_valid_comparisons,
    find_dup_candidates_parallel,
    list_files,
    precompute_file_info,
    sort_files_by_mtime,
)
from .text import (
    build_diff_text,
    get_term_width,
    get_visible_width,
    pad_to_width,
    truncate_to_width,
)


def _blinking_input(prompt: str = "") -> str:
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
    return input().strip().lower()


def _print_dup_cand(dup_cand: DupCand, index: int, total: int) -> None:
    """重複候補を表示"""
    ratio = round(dup_cand[0].sm.ratio() * 100)
    ratio_color = COLOR_SUCCESS if ratio >= 95 else COLOR_WARNING if ratio >= 90 else COLOR_DIM

    print(f"\n{'─' * get_term_width()}")
    print(f"[{index:3d}/{total:3d}] {ratio_color}📊 類似度: {ratio}%{COLOR_RESET}")

    size_diff = abs(dup_cand[0].size - dup_cand[1].size)
    max_size = max(dup_cand[0].size, dup_cand[1].size)
    size_ratio = 100 * size_diff / max_size if max_size > 0 else 0

    size_color = COLOR_ERROR if size_diff > SIZE_TH else COLOR_DIM
    print(
        f"        {size_color}📐 サイズ差: {size_diff / 1024 / 1024:.1f} MB ({size_ratio:.1f}%){COLOR_RESET}"
    )

    # ファイル名を表示幅に収める（ステータスバーに上書きされないように）
    term_width = get_term_width()
    prefix_width = get_visible_width("  📁 古: ")
    max_name_width = term_width - prefix_width - 1

    # ディレクトリ部分を取得（同じディレクトリなので共通）
    parent = Path(dup_cand[0].name).parent
    dir_part = str(parent) if str(parent) != "." else ""
    if dir_part:
        dir_prefix = dir_part + "/"
        dir_prefix_width = get_visible_width(dir_prefix)
        # ディレクトリパスが長すぎる場合は省略
        max_dir_width = max_name_width // 2
        if dir_prefix_width > max_dir_width:
            dir_prefix = truncate_to_width(dir_prefix, max_dir_width)
            dir_prefix_width = get_visible_width(dir_prefix)
    else:
        dir_prefix = ""
        dir_prefix_width = 0

    # ベースネーム部分を差分着色で表示
    sm = dup_cand[0].sm
    basename_max_width = max(20, max_name_width - dir_prefix_width)  # 最低20文字は確保
    name_old = dir_prefix + build_diff_text(dup_cand[0].basename, sm, 0, basename_max_width)
    name_new = dir_prefix + build_diff_text(dup_cand[1].basename, sm, 1, basename_max_width)

    print(f"\n  📁 古: {name_old}")
    print(f"  📄 新: {name_new}")


def _confirm_quit() -> bool:
    """Ctrl-C が押された時に終了するか確認。終了する場合は True を返す"""
    try:
        sys.stdout.write("\n\n")  # ステータスバーとの間に空行
        sys.stdout.flush()
        ans = _blinking_input(f"{COLOR_WARNING}⏸️  中断しますか？ [y/N]: {COLOR_RESET}")
    except (KeyboardInterrupt, EOFError):
        print(f"\n{COLOR_DIM}👋 終了処理中...{COLOR_RESET}")
        return True
    if ans == "y":
        print(f"{COLOR_DIM}👋 終了処理中...{COLOR_RESET}")
        return True
    print(f"{COLOR_DIM}▶️  継続します{COLOR_RESET}")
    return False


def _list_dup_cand(dir_path: str, manager: enlighten.Manager) -> list[DupCand]:
    """重複候補を対話的に選択

    Returns:
        削除候補リスト
    """
    # キャッシュDBを初期化
    init_cache_db()

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

    # ファイル一覧取得
    counter = manager.counter(desc="📂 ファイル一覧", unit="件")

    def on_file_found(_: int) -> None:
        counter.update()

    file_path_list = list_files(dir_path, on_file_found)

    if shutdown_event.is_set():
        counter.close()
        tool_status.close()
        dir_status.close()
        return []

    counter.desc = "📂 ソート中"
    counter.refresh()
    file_path_list = sort_files_by_mtime(file_path_list)
    counter.close()

    # ファイル情報を事前計算（プログレスバー付き）
    progress_bar = manager.counter(
        total=len(file_path_list),
        desc="⚙️  前処理",
        unit="件",
        bar_format="{desc}{desc_pad}{percentage:3.0f}%|{bar}| {count:,d}/{total:,d} {unit} [{elapsed}<{eta}]",
    )

    def on_precompute(_: int) -> None:
        progress_bar.update()

    file_infos = precompute_file_info(file_path_list, dir_path, on_precompute)
    progress_bar.close()

    total_files = len(file_infos)
    if total_files < 2:
        tool_status.close()
        dir_status.close()
        return []

    # 有効な比較ペア数をカウント
    tool_status.update(status="比較対象をカウント中...")
    total_comparisons = count_valid_comparisons(file_infos)

    if total_comparisons == 0:
        tool_status.update(status="✨ 比較対象がありませんでした")
        tool_status.close()
        dir_status.close()
        return []

    tool_status.update(status="重複ファイルを調べています...")

    # プログレスバー
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

    dup_cand_list: list[DupCand] = []

    def progress_callback(comparisons: int, found: int) -> None:
        """並列処理からの進捗コールバック"""
        if shutdown_event.is_set():
            return
        compare_bar.count = compare_bar.count + comparisons
        compare_bar.refresh()
        question_counter.count = question_counter.count + found
        question_counter.refresh()

    try:
        # フェーズ1: 並列で比較処理
        num_workers = min(mp.cpu_count(), 8)
        pending_questions = find_dup_candidates_parallel(file_infos, progress_callback, num_workers)

        if shutdown_event.is_set():
            # スキャンが中断された: ここまでの結果で続行するか確認
            sys.stdout.write("\n\n")
            sys.stdout.flush()
            try:
                ans = _blinking_input(
                    f"{COLOR_WARNING}⏸️  スキャンを中断しました。"
                    f"ここまでの結果 ({len(pending_questions)} 件) で続行しますか？ [y/N]: {COLOR_RESET}"
                )
            except (KeyboardInterrupt, EOFError):
                ans = ""
            if ans != "y":
                return dup_cand_list
            shutdown_event.clear()
            print(f"{COLOR_DIM}▶️  ここまでの結果で継続します{COLOR_RESET}")
        else:
            # 最終進捗を表示
            compare_bar.count = total_comparisons
            compare_bar.refresh()

        # キャッシュ済みペアを除外（一括読み込みしてメモリ上で照合）
        cached_pairs = load_cached_pairs()
        filtered_questions = [
            dup_cand
            for dup_cand in pending_questions
            if get_pair_key(dup_cand[0].path, dup_cand[1].path) not in cached_pairs
        ]
        cached_count = len(pending_questions) - len(filtered_questions)
        pending_questions = filtered_questions

        question_counter.count = len(pending_questions)
        question_counter.refresh()

        if cached_count > 0:
            print(f"\n{COLOR_DIM}📦 キャッシュ済み: {cached_count} 件をスキップ{COLOR_RESET}")

        # 質問がない場合
        if not pending_questions:
            tool_status.update(status="✨ 重複候補は見つかりませんでした")
            return dup_cand_list

        # フェーズ2: 質問に回答
        tool_status.update(status="🤔 削除して良いか確認お願いします")
        with contextlib.suppress(ValueError, RuntimeError):
            question_counter.close()
        _ask_questions(pending_questions, dup_cand_list, delete_counter, manager)

    finally:
        tool_status.close()
        dir_status.close()
        compare_bar.close()
        with contextlib.suppress(ValueError, RuntimeError):
            question_counter.close()
        delete_counter.close()

    return dup_cand_list


def _ask_questions(
    pending_questions: list[DupCand],
    dup_cand_list: list[DupCand],
    delete_counter: enlighten.Counter,
    manager: enlighten.Manager,
) -> None:
    """重複候補を1件ずつ確認し、削除候補を dup_cand_list に追加する

    Ctrl-C で中断確認を行い、「継続」なら同じ質問を再表示する。
    「n」= 重複ではない、は確定情報なので即座にキャッシュへ保存する。
    """
    qa_bar = manager.counter(
        total=len(pending_questions),
        desc="💬 回答",
        unit="件",
        bar_format="{desc}{desc_pad}{percentage:3.0f}%|{bar}| {count:,d}/{total:,d} {unit} [{elapsed}<{eta}]",
    )

    try:
        index = 0
        total = len(pending_questions)
        while index < total:
            if shutdown_event.is_set():
                break

            dup_cand = pending_questions[index]
            _print_dup_cand(dup_cand, index + 1, total)

            print()  # ステータスバーとの間に空行
            prompt = f"{COLOR_TITLE}🤔 同一？(後者が削除候補) [y/n/q]: {COLOR_RESET}"
            try:
                ans = _blinking_input(prompt)
            except (KeyboardInterrupt, EOFError):
                if _confirm_quit():
                    shutdown_event.set()
                    break
                print()  # 同じ質問を再表示して継続
                continue

            index += 1
            qa_bar.update()
            if ans == "y":
                dup_cand_list.append(dup_cand)
                delete_counter.count = len(dup_cand_list)
                delete_counter.refresh()
                print(f"{COLOR_SUCCESS}✅ 削除候補に追加{COLOR_RESET}")
            elif ans == "q":
                break
            else:
                # 「n」= 重複ではない、は確定情報なので即座にキャッシュへ保存する
                cache_pair(dup_cand[0].path, dup_cand[1].path)
                print(f"{COLOR_DIM}⏭️  スキップ{COLOR_RESET}")

            print()  # ステータスバーとの間に空行
    finally:
        qa_bar.close()


def _resolve_trash_path(trash_dir_path: str, src_path: Path) -> Path:
    """ゴミ箱内の移動先パスを決定

    同名ファイルが既に存在する場合は連番を付与し、上書きによる消失を防ぐ。
    """
    dst_path = Path(trash_dir_path) / src_path.name
    seq = 1
    while dst_path.exists():
        dst_path = Path(trash_dir_path) / f"{src_path.stem} ({seq}){src_path.suffix}"
        seq += 1
    return dst_path


def _exec_delete(dup_cand_list: list[DupCand], trash_dir_path: str, manager: enlighten.Manager) -> None:
    """削除を実行"""
    if not dup_cand_list:
        print(f"\n{COLOR_DIM}📭 削除候補がありません{COLOR_RESET}")
        return

    try:
        Path(trash_dir_path).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"{COLOR_ERROR}❌ ゴミ箱ディレクトリを作成できません: {e}{COLOR_RESET}")
        return

    process_all = False
    deleted_count = 0
    failed_count = 0

    progress = manager.counter(
        total=len(dup_cand_list),
        desc="🗑️  削除確認",
        unit="件",
    )

    for dup_cand in dup_cand_list:
        progress.update()
        _print_dup_cand(dup_cand, progress.count, len(dup_cand_list))

        src_path = Path(dup_cand[1].path)

        if not src_path.is_file():
            print(f"{COLOR_WARNING}⚠️  ファイルが見つかりません{COLOR_RESET}")
            continue

        should_delete = process_all
        if not process_all:
            while True:
                sys.stdout.write("\n")  # ステータスバーとの間に空行
                sys.stdout.flush()
                try:
                    ans = _blinking_input(f"{COLOR_ERROR}🗑️  後者を削除しますか？[y/n/a]: {COLOR_RESET}")
                except (KeyboardInterrupt, EOFError):
                    if _confirm_quit():
                        shutdown_event.set()
                        progress.close()
                        print(
                            f"\n{COLOR_WARNING}⏹️  中断: "
                            f"ここまでに {deleted_count} 件削除しました{COLOR_RESET}"
                        )
                        return
                    continue  # 同じ確認を再表示して継続
                break
            should_delete = ans in ("y", "a")
            if ans == "a":
                process_all = True
                print(f"{COLOR_WARNING}⚡ 以降すべて削除します{COLOR_RESET}")

        if should_delete:
            dst_path = _resolve_trash_path(trash_dir_path, src_path)
            try:
                shutil.move(src_path, dst_path)
            except OSError as e:
                # 1件の失敗（ディスク満杯・権限など）で全体を止めない
                failed_count += 1
                print(f"{COLOR_ERROR}❌ 移動に失敗しました: {e}{COLOR_RESET}")
                continue
            deleted_count += 1
            print(f"{COLOR_SUCCESS}🗑️  削除しました{COLOR_RESET}")

    progress.close()
    print(f"\n{'─' * 50}")
    print(f"{COLOR_SUCCESS}🎉 完了: {deleted_count} 件のファイルを削除しました{COLOR_RESET}")
    if failed_count > 0:
        print(f"{COLOR_ERROR}⚠️  {failed_count} 件の移動に失敗しました{COLOR_RESET}")


def run_stats_mode(dir_path: str) -> None:
    """フォルダ毎の質問リスト数を表示（デバッグ用）"""
    print(f"📊 統計モード: {dir_path}")
    print()

    # ファイル一覧を取得
    print("📂 ファイル一覧を取得中...")
    file_path_list = list_files(dir_path)

    print(f"   合計: {len(file_path_list)} ファイル")
    print()

    # ファイル情報を事前計算
    print("⚙️  ファイル情報を計算中...")
    file_infos = precompute_file_info(file_path_list, dir_path)

    # ディレクトリ毎にグループ化
    dir_to_infos: defaultdict[str, list[PrecomputedFileInfo]] = defaultdict(list)
    for info in file_infos:
        dir_to_infos[info.dir_path].append(info)

    print(f"   合計: {len(dir_to_infos)} ディレクトリ")
    print()

    # ディレクトリ毎に重複候補を数える
    print("🔍 重複候補をカウント中...")
    results: list[DirStats] = []

    # ファイル数が多い順にソート（進捗がわかりやすいように）
    sorted_dirs = sorted(dir_to_infos.items(), key=lambda x: len(x[1]), reverse=True)
    processed = 0

    for dir_path_key, infos in sorted_dirs:
        processed += 1
        if len(infos) < 2:
            continue

        rel_path = str(Path(dir_path_key).relative_to(dir_path))
        pairs_total = len(infos) * (len(infos) - 1) // 2
        print(
            f"   [{processed}/{len(dir_to_infos)}] {rel_path} ({len(infos)} files, {pairs_total} pairs)...",
            end="",
            flush=True,
        )

        candidates = 0
        pairs_checked = 0
        for i in range(len(infos)):
            for j in range(i + 1, len(infos)):
                pairs_checked += 1
                result = compare_pair(infos[i], infos[j], MATCH_TH)
                if result is not None:
                    candidates += 1

        print(f" → {candidates} 候補")

        if candidates > 0:
            results.append(DirStats(rel_path, len(infos), pairs_checked, candidates))

    # 候補数でソート
    results.sort(key=lambda x: x.candidates, reverse=True)

    col_width = 40
    print()
    print("=" * 80)
    print(f"{pad_to_width('ディレクトリ', col_width)} {'ファイル数':>10} {'比較ペア':>10} {'候補数':>10}")
    print("=" * 80)

    total_candidates = 0
    for stats in results:
        total_candidates += stats.candidates
        # 長いパスは表示幅で省略
        display_path = stats.rel_path
        while get_visible_width(display_path) > col_width - 3:
            display_path = display_path[1:]
        if display_path != stats.rel_path:
            display_path = "..." + display_path
        print(
            f"{pad_to_width(display_path, col_width)} {stats.file_count:>10} {stats.pairs:>10} {stats.candidates:>10}"  # noqa: E501
        )

    print("=" * 80)
    print(f"{pad_to_width('合計', col_width)} {'':>10} {'':>10} {total_candidates:>10}")


def run_interactive(target_dir_path: str) -> None:
    """対話モードで実行"""
    manager = enlighten.Manager()

    try:
        dup_cand_list = _list_dup_cand(target_dir_path, manager)

        if shutdown_event.is_set():
            print(f"\n{COLOR_WARNING}⏹️  中断しました{COLOR_RESET}")
            return

        if dup_cand_list:
            print(f"\n{COLOR_WARNING}{'─' * 50}{COLOR_RESET}")
            print(f"{COLOR_WARNING}⚠️  削除の最終確認{COLOR_RESET}")
            print(f"{COLOR_WARNING}{'─' * 50}{COLOR_RESET}")
            _exec_delete(dup_cand_list, TRASH_DIR, manager)
        else:
            print(f"\n{COLOR_DIM}✨ 重複候補は見つかりませんでした{COLOR_RESET}")

    except KeyboardInterrupt:
        # 入力待ち以外の場所（ファイル走査中など）での Ctrl-C は即座に終了する
        shutdown_event.set()
        print(f"\n{COLOR_WARNING}⏹️  中断しました{COLOR_RESET}")
        sys.exit(130)
    finally:
        manager.stop()
