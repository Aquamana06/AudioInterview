#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
from collections import defaultdict

def load_id_mapping(id_list_path):
    """id_list.csvからマッピングを読み込む"""
    id_to_name = {}
    with open(id_list_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            user_id = row['ID (user_id)'].strip()
            alphabet = row['アルファベット'].strip()
            id_to_name[user_id] = alphabet if alphabet != '-' else user_id
    return id_to_name

def count_messages_per_user(filepath):
    """各ユーザーのメッセージ数をカウント"""
    user_counts = defaultdict(int)
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            user_id = row['user_id']
            user_counts[user_id] += 1
    return user_counts

# メイン処理
base_path = '/Users/mana/Desktop/AudioInterview/data'

# IDマッピングを読み込む
id_mapping = load_id_mapping(f'{base_path}/id_list.csv')

# 各データセットのカウント
uchida_counts = count_messages_per_user(f'{base_path}/list_raw_uchida.csv')
matsushita_counts = count_messages_per_user(f'{base_path}/list_raw_matsushita.csv')

# 全ユーザーのリストを作成
all_users = set(uchida_counts.keys()) | set(matsushita_counts.keys())

# ユーザー名ごとに集計（同じアルファベットを統合）
name_data = defaultdict(lambda: {'uchida': 0, 'matsushita': 0, 'user_ids': []})

for user_id in all_users:
    user_name = id_mapping.get(user_id, user_id)
    uchida_count = uchida_counts.get(user_id, 0)
    matsushita_count = matsushita_counts.get(user_id, 0)

    name_data[user_name]['uchida'] += uchida_count
    name_data[user_name]['matsushita'] += matsushita_count
    name_data[user_name]['user_ids'].append(user_id)

# 結果を整理
results = []
for user_name, data in name_data.items():
    results.append({
        'user_name': user_name,
        'uchida': data['uchida'],
        'matsushita': data['matsushita'],
        'total': data['uchida'] + data['matsushita']
    })

# ユーザー名でソート
results.sort(key=lambda x: x['user_name'])

# CSVに出力
output_path = f'{base_path}/comparison_summary.csv'
with open(output_path, 'w', encoding='utf-8', newline='') as f:
    fieldnames = ['user_name', 'uchida', 'matsushita', 'total']
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(results)

# コンソールに表示
print("\n" + "=" * 70)
print("データ件数比較: Uchida vs Matsushita")
print("=" * 70)
print(f"{'User':<15} {'Uchida':<12} {'Matsushita':<12} {'Total':<10}")
print("-" * 70)

for r in results:
    print(f"{r['user_name']:<15} {r['uchida']:<12} {r['matsushita']:<12} {r['total']:<10}")

print("-" * 70)
uchida_total = sum(r['uchida'] for r in results)
matsushita_total = sum(r['matsushita'] for r in results)
grand_total = sum(r['total'] for r in results)
print(f"{'合計':<15} {uchida_total:<12} {matsushita_total:<12} {grand_total:<10}")
print("=" * 70)

print(f"\n出力ファイル: {output_path}")
