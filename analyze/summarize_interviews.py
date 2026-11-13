#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
from collections import defaultdict

def load_id_mapping(id_list_path):
    """
    id_list.csvからユーザーIDとアルファベットのマッピングを読み込む
    """
    id_to_name = {}

    with open(id_list_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            user_id = row['ID (user_id)'].strip()
            alphabet = row['アルファベット'].strip()
            id_to_name[user_id] = alphabet if alphabet != '-' else user_id

    return id_to_name

def analyze_interview_file(filepath, output_filepath, dataset_name, id_mapping):
    """
    インタビューファイルを分析して、各ユーザーのセッション数と文章数を集計
    """
    user_sessions = defaultdict(set)  # user_id -> set of interview_ids
    user_message_count = defaultdict(int)  # user_id -> message count

    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            user_id = row['user_id']
            interview_id = row['interview_id']

            # セッションを記録
            user_sessions[user_id].add(interview_id)
            # メッセージ数をカウント
            user_message_count[user_id] += 1

    # 結果をまとめる
    results = []
    for user_id in sorted(user_sessions.keys()):
        session_count = len(user_sessions[user_id])
        message_count = user_message_count[user_id]
        avg_messages = message_count / session_count if session_count > 0 else 0

        # id_mappingからユーザー名を取得
        user_name = id_mapping.get(user_id, user_id)

        results.append({
            'user_name': user_name,
            'user_id': user_id,
            'session_count': session_count,
            'message_count': message_count,
            'avg_messages_per_session': round(avg_messages, 2)
        })

    # CSVに出力
    with open(output_filepath, 'w', encoding='utf-8', newline='') as f:
        fieldnames = ['user_name', 'user_id', 'session_count', 'message_count', 'avg_messages_per_session']
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        writer.writeheader()
        writer.writerows(results)

    # サマリーを表示
    print(f"\n=== {dataset_name} Summary ===")
    print(f"Total unique users: {len(results)}")
    print(f"Total sessions: {sum(r['session_count'] for r in results)}")
    print(f"Total messages: {sum(r['message_count'] for r in results)}")
    print(f"Output file: {output_filepath}")

    # ユーザー詳細を表示
    print(f"\n{dataset_name} - User Details:")
    print(f"{'Name':<10} {'User ID':<40} {'Sessions':<10} {'Messages':<10} {'Avg/Session':<12}")
    print("-" * 92)
    for r in results:
        print(f"{r['user_name']:<10} {r['user_id']:<40} {r['session_count']:<10} {r['message_count']:<10} {r['avg_messages_per_session']:<12}")

    return results

# メイン処理
if __name__ == "__main__":
    base_path = '/Users/mana/Desktop/AudioInterview/data'

    # IDマッピングを読み込む
    id_mapping = load_id_mapping(f'{base_path}/id_list.csv')

    print("=== ID Mapping Loaded ===")
    print(f"Total mappings: {len(id_mapping)}")
    for user_id, name in sorted(id_mapping.items(), key=lambda x: x[1]):
        print(f"{name:<10} -> {user_id}")

    # Uchida データセットを分析
    uchida_results = analyze_interview_file(
        f'{base_path}/list_raw_uchida.csv',
        f'{base_path}/summary_uchida.csv',
        'Uchida Dataset',
        id_mapping
    )

    # Matsushita データセットを分析
    matsushita_results = analyze_interview_file(
        f'{base_path}/list_raw_matsushita.csv',
        f'{base_path}/summary_matsushita.csv',
        'Matsushita Dataset',
        id_mapping
    )

    print("\n" + "=" * 92)
    print("Analysis complete!")
    print("=" * 92)
