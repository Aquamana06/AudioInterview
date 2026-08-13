import json
from datetime import datetime

# 統合されたデータファイルを読み込む
input_file = '/Users/mana/Desktop/AudioInterview/data/merged_interviews_by_username.json'

with open(input_file, 'r', encoding='utf-8') as f:
    data = json.load(f)

# カウント結果を格納
count_results = []
total_interviews = 0

for user_name, interviews in data.items():
    count = len(interviews)
    total_interviews += count
    count_results.append({
        'user_name': user_name,
        'interview_count': count
    })

# インタビュー数の多い順にソート
count_results.sort(key=lambda x: x['interview_count'], reverse=True)

# テキストファイルとして出力
output_txt = '/Users/mana/Desktop/AudioInterview/data/interview_count_summary.txt'
with open(output_txt, 'w', encoding='utf-8') as f:
    f.write('=' * 50 + '\n')
    f.write('インタビューデータ数集計結果\n')
    f.write(f'集計日時: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
    f.write('=' * 50 + '\n\n')

    f.write(f'{"ユーザー名":<20} {"インタビュー数":>10}\n')
    f.write('-' * 50 + '\n')

    for result in count_results:
        f.write(f'{result["user_name"]:<20} {result["interview_count"]:>10}件\n')

    f.write('-' * 50 + '\n')
    f.write(f'{"合計":<20} {total_interviews:>10}件\n')
    f.write(f'{"ユニークなユーザー数":<20} {len(count_results):>10}人\n')
    f.write('=' * 50 + '\n')

# JSONファイルとしても出力
output_json = '/Users/mana/Desktop/AudioInterview/data/interview_count_summary.json'
summary = {
    'timestamp': datetime.now().isoformat(),
    'total_users': len(count_results),
    'total_interviews': total_interviews,
    'users': count_results
}

with open(output_json, 'w', encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

# コンソールにも表示
print('=' * 50)
print('インタビューデータ数集計結果')
print('=' * 50)
print()
print(f'{"ユーザー名":<20} {"インタビュー数":>10}')
print('-' * 50)

for result in count_results:
    print(f'{result["user_name"]:<20} {result["interview_count"]:>10}件')

print('-' * 50)
print(f'{"合計":<20} {total_interviews:>10}件')
print(f'{"ユニークなユーザー数":<20} {len(count_results):>10}人')
print('=' * 50)
print()
print(f'テキスト出力: {output_txt}')
print(f'JSON出力: {output_json}')
