import json
from datetime import datetime

# 詳細データファイルを読み込む
input_file = '/Users/mana/Desktop/AudioInterview/data/interview_detailed_summary.json'

with open(input_file, 'r', encoding='utf-8') as f:
    data = json.load(f)

# ユーザーサマリーだけを抽出
user_summary_list = []

for user in data['users']:
    user_summary = {
        'user_name': user['user_name'],
        'interview_count': user['interview_count'],
        'total_messages': user['total_messages'],
        'average_messages_per_interview': user['average_messages_per_interview']
    }
    user_summary_list.append(user_summary)

# サマリーデータを作成
summary_data = {
    'timestamp': datetime.now().isoformat(),
    'total_users': data['total_users'],
    'total_interviews': data['total_interviews'],
    'total_messages': data['total_messages'],
    'average_messages_per_interview': data['average_messages_per_interview'],
    'users': user_summary_list
}

# JSON形式で出力
output_json = '/Users/mana/Desktop/AudioInterview/data/user_summary_only.json'
with open(output_json, 'w', encoding='utf-8') as f:
    json.dump(summary_data, f, ensure_ascii=False, indent=2)

# CSV形式でも出力
output_csv = '/Users/mana/Desktop/AudioInterview/data/user_summary_only.csv'
with open(output_csv, 'w', encoding='utf-8') as f:
    f.write('ユーザー名,インタビュー数,総メッセージ数,平均メッセージ数\n')
    for user in user_summary_list:
        f.write(f'{user["user_name"]},{user["interview_count"]},{user["total_messages"]},{user["average_messages_per_interview"]}\n')

print('ユーザーサマリーを抽出しました')
print(f'\nJSON出力: {output_json}')
print(f'CSV出力: {output_csv}')
print(f'\n総ユーザー数: {len(user_summary_list)}人')
