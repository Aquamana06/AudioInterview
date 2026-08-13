import json
import csv
from collections import defaultdict

# CSVファイルから対応表を読み込む
mapping_file = '/Users/mana/Desktop/AudioInterview/data/user_ABC.csv'
user_name_to_abc = {}

with open(mapping_file, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        user_name = row['user_name'].strip()
        abc_id = row['Interviewee_ABC'].strip()
        user_name_to_abc[user_name] = abc_id

print(f"対応表を読み込みました: {len(user_name_to_abc)}件")

# 統合済みデータを読み込む
input_file = '/Users/mana/Desktop/AudioInterview/data/merged_interviews_by_username.json'

with open(input_file, 'r', encoding='utf-8') as f:
    data_by_username = json.load(f)

# ABC IDごとにデータを再統合
data_by_abc_id = defaultdict(list)

for user_name, interviews in data_by_username.items():
    # user_nameからABC IDを取得
    abc_id = user_name_to_abc.get(user_name)

    if abc_id is None:
        print(f"警告: '{user_name}'は対応表に見つかりませんでした。スキップします。")
        continue

    # 各インタビューから必要なフィールドだけを抽出（timestampを除外）
    for interview in interviews:
        # dataフィールドからtimestampを削除
        cleaned_data = []
        for message in interview.get('data', []):
            cleaned_message = {
                'role': message.get('role'),
                'content': message.get('content')
            }
            cleaned_data.append(cleaned_message)

        simplified_interview = {
            'user_id': abc_id,  # ABC IDを使用
            'session_id': interview.get('session_id'),
            'data': cleaned_data
        }
        data_by_abc_id[abc_id].append(simplified_interview)

# 通常のdictに変換してソート
result = {}
for abc_id in sorted(data_by_abc_id.keys()):
    result[abc_id] = data_by_abc_id[abc_id]

# 結果を出力
output_file = '/Users/mana/Desktop/AudioInterview/data/merged_interviews_by_abc_id.json'
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

# 統計情報を表示
print('\n' + '=' * 80)
print('統合結果:')
print('=' * 80)
print(f'\n総ABC ID数: {len(result)}')
print(f'総インタビュー数: {sum(len(interviews) for interviews in result.values())}')

print('\n各ABC IDごとのインタビュー数:')
for abc_id in sorted(result.keys()):
    print(f'  {abc_id}: {len(result[abc_id])}件')

print(f'\n出力ファイル: {output_file}')
print('\n※ timestampは削除されています')
