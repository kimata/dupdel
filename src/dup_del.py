#!/usr/bin/env python3

"""
ファイル名が似ているファイルを削除するスクリプトです．

Usage:
  dup_del.py PATH

Options:
  PATH: チェック対象のフォルダ
"""

from docopt import docopt

import os
import re
import itertools
import shutil
import difflib
import pprint

SIZE_TH = 200 * 1024 * 1024
MATCH_TH = 0.85
IGNORE_PAT = "[\d_ 　🈑🈞字再\[\]]"

TRASH_DIR = "/storage/.recycle"


def list_file(dir_path):
    file_name_list = os.listdir(dir_path)

    # NOTE: 古いファイル順にする
    file_name_list.sort(
        key=lambda file_name: os.path.getmtime(os.path.join(dir_path, file_name)),
    )

    return list(
        filter(
            lambda file_name: os.path.isfile(os.path.join(dir_path, file_name)),
            file_name_list,
        )
    )


def print_diff_text(text, sm, mode):
    for (
        tag,
        i1,
        i2,
        j1,
        j2,
    ) in sm.get_opcodes():
        if mode == 0:
            str = text[i1:i2]
        else:
            str = text[j1:j2]

        if tag == "delete":
            print("\033[0;31m{str}\033[0m".format(str=str), end="")
        elif tag == "replace":
            print("\033[1;32m{str}\033[0m".format(str=str), end="")
        elif tag == "insert":
            print("\033[1;34m{str}\033[0m".format(str=str), end="")
        elif tag == "equal":
            print("{str}".format(str=str), end="")
    print("")


def print_dup_cand(dup_cand, index, total):
    print(
        "[{index:3d} / {total:3d}] 類似度：{ratio}%".format(
            index=index, total=total, ratio=round(dup_cand[0]["sm"].ratio() * 100)
        )
    )

    size_diff = abs(dup_cand[0]["size"] - dup_cand[1]["size"])
    if size_diff > SIZE_TH:
        print("\033[1;31m", end="")

    print(
        "サイズ違い: {diff:.1f} MB, {ratio:.1f} %)".format(
            diff=size_diff / 1024 / 1024,
            ratio=100 * size_diff / max(dup_cand[0]["size"], dup_cand[1]["size"]),
        )
    )

    if size_diff > SIZE_TH:
        print("\033[0m", end="")

    print_diff_text(dup_cand[0]["name"], dup_cand[0]["sm"], 0)
    print_diff_text(dup_cand[1]["name"], dup_cand[1]["sm"], 1)


def list_dup_cand(dir_path):
    file_name_list = list_file(dir_path)

    done_hash = {}
    dup_cand_list = []
    for i, file_name_1 in enumerate(file_name_list):
        for file_name_2 in file_name_list[i:-1]:
            if file_name_1 == file_name_2 or file_name_1 in done_hash:
                continue
            # NOTE: 一旦，比較対象にしたくない文字を除外して比較
            sm_judge = difflib.SequenceMatcher(
                None,
                re.sub(IGNORE_PAT, "", file_name_1),
                re.sub(IGNORE_PAT, "", file_name_2),
            )
            dup_cand = []
            for file_name in [file_name_1, file_name_2]:
                file_path = os.path.join(dir_path, file_name)
                dup_cand.append(
                    {
                        "name": file_name,
                        "size": os.path.getsize(file_path),
                        "mtime": os.stat(file_path).st_mtime,
                    }
                )

            dup_cand.sort(key=lambda file_info: file_info["mtime"])

            # NOTE: オリジナルの文字列で再度比較
            sm = difflib.SequenceMatcher(
                None,
                dup_cand[0]["name"],
                dup_cand[1]["name"],
            )
            dup_cand[0]["sm"] = sm
            dup_cand[1]["sm"] = sm

            if (sm_judge.ratio() > MATCH_TH) and (
                (
                    100
                    * abs(dup_cand[0]["size"] - dup_cand[1]["size"])
                    / max(dup_cand[0]["size"], dup_cand[1]["size"])
                    < 40
                )
            ):
                print("--------------------------------------------------")
                print_dup_cand(dup_cand, i + 1, len(file_name_list))

                ans = input("同一？ (y/n/q) ")

                if ans.lower() == "y":
                    dup_cand_list.append(dup_cand)
                if ans.lower() == "q":
                    return dup_cand_list

                # NOTE: 古い側のファイルのみチェック済みにする
                done_hash[file_name_1] = 1
    return dup_cand_list


def exec_delete(dup_cand_list, target_dir_path, trash_dir_path):
    os.makedirs(trash_dir_path, exist_ok=True)
    process_all = False
    for i, dup_cand in enumerate(dup_cand_list):
        print("--------------------------------------------------")
        print_dup_cand(dup_cand, i + 1, len(dup_cand_list))

        if not os.path.isfile(os.path.join(target_dir_path, dup_cand[1]["name"])):
            continue
        if not process_all:
            ans = input("\033[0;32m後者を削除しますか？(y/n/a) \033[0m")

        if ans.lower() == "y" or ans.lower() == "a" or process_all:
            shutil.move(
                os.path.join(target_dir_path, dup_cand[1]["name"]),
                os.path.join(trash_dir_path, dup_cand[1]["name"]),
            )
            print("削除しました．")

        if ans.lower() == "a":
            process_all = True


args = docopt(__doc__)

target_dir_path = args["PATH"]

print("\033[1;32m次ののフォルダに対して重複チェックを開始します．\033[0m")
print(target_dir_path)
print()

dup_cand_list = list_dup_cand(target_dir_path)
print()
print("\033[0;33m削除してよいか最終チェックをお願いします．\033[0m")
print()

exec_delete(dup_cand_list, target_dir_path, TRASH_DIR)
