import json
from datetime import datetime

# 統合されたデータファイルを読み込む
input_file = '/Users/mana/Desktop/AudioInterview/data/merged_interviews_by_username.json'

with open(input_file, 'r', encoding='utf-8') as f:
    data = json.load(f)

# 詳細な集計結果を格納
detailed_results = []
total_interviews = 0
total_messages = 0

for user_name, interviews in data.items():
    user_total_messages = 0
    interview_details = []

    for idx, interview in enumerate(interviews, 1):
        # dataフィールドから会話のやりとりをカウント
        conversation_data = interview.get('data', [])
        message_count = len(conversation_data)
        user_total_messages += message_count
        total_messages += message_count

        # ユーザーとアシスタントのメッセージ数をそれぞれカウント
        user_messages = sum(1 for msg in conversation_data if msg.get('role') == 'user')
        assistant_messages = sum(1 for msg in conversation_data if msg.get('role') == 'assistant')

        interview_details.append({
            'interview_number': idx,
            'session_id': interview.get('session_id', 'N/A'),
            'total_messages': message_count,
            'user_messages': user_messages,
            'assistant_messages': assistant_messages,
            'conversation_turns': min(user_messages, assistant_messages)  # 往復数
        })

    total_interviews += len(interviews)

    detailed_results.append({
        'user_name': user_name,
        'interview_count': len(interviews),
        'total_messages': user_total_messages,
        'average_messages_per_interview': round(user_total_messages / len(interviews), 2) if interviews else 0,
        'interviews': interview_details
    })

# インタビュー数の多い順にソート
detailed_results.sort(key=lambda x: x['interview_count'], reverse=True)

# JSON形式で詳細結果を出力
output_detailed_json = '/Users/mana/Desktop/AudioInterview/data/interview_detailed_summary.json'
summary = {
    'timestamp': datetime.now().isoformat(),
    'total_users': len(detailed_results),
    'total_interviews': total_interviews,
    'total_messages': total_messages,
    'average_messages_per_interview': round(total_messages / total_interviews, 2) if total_interviews > 0 else 0,
    'users': detailed_results
}

with open(output_detailed_json, 'w', encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

# テキストファイルで詳細サマリーを出力
output_detailed_txt = '/Users/mana/Desktop/AudioInterview/data/interview_detailed_summary.txt'
with open(output_detailed_txt, 'w', encoding='utf-8') as f:
    f.write('=' * 80 + '\n')
    f.write('インタビューデータ詳細集計結果\n')
    f.write(f'集計日時: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
    f.write('=' * 80 + '\n\n')

    f.write('【全体サマリー】\n')
    f.write(f'  総ユーザー数: {len(detailed_results)}人\n')
    f.write(f'  総インタビュー数: {total_interviews}件\n')
    f.write(f'  総メッセージ数: {total_messages}件\n')
    f.write(f'  1インタビューあたりの平均メッセージ数: {summary["average_messages_per_interview"]}件\n')
    f.write('\n' + '=' * 80 + '\n\n')

    f.write(f'{"ユーザー名":<15} {"インタビュー数":>8} {"総メッセージ数":>10} {"平均メッセージ数":>12}\n')
    f.write('-' * 80 + '\n')

    for result in detailed_results:
        f.write(f'{result["user_name"]:<15} '
                f'{result["interview_count"]:>8}件 '
                f'{result["total_messages"]:>10}件 '
                f'{result["average_messages_per_interview"]:>12}件\n')

    f.write('\n' + '=' * 80 + '\n\n')

    # 各ユーザーの詳細
    f.write('【各ユーザーの詳細】\n\n')
    for result in detailed_results:
        f.write(f'\n■ {result["user_name"]} (インタビュー数: {result["interview_count"]}件)\n')
        f.write('-' * 80 + '\n')
        f.write(f'  {"No.":>3} {"総メッセージ":>10} {"ユーザー":>8} {"AI":>8} {"往復数":>8}  Session ID\n')
        f.write('-' * 80 + '\n')

        for interview in result['interviews']:
            session_id = interview['session_id'][:40] + '...' if len(interview['session_id']) > 40 else interview['session_id']
            f.write(f'  {interview["interview_number"]:>3} '
                    f'{interview["total_messages"]:>10}件 '
                    f'{interview["user_messages"]:>8}件 '
                    f'{interview["assistant_messages"]:>8}件 '
                    f'{interview["conversation_turns"]:>8}回  '
                    f'{session_id}\n')

        f.write('\n')

# コンソールに表示
print('=' * 80)
print('インタビューデータ詳細集計結果')
print('=' * 80)
print()
print('【全体サマリー】')
print(f'  総ユーザー数: {len(detailed_results)}人')
print(f'  総インタビュー数: {total_interviews}件')
print(f'  総メッセージ数: {total_messages}件')
print(f'  1インタビューあたりの平均メッセージ数: {summary["average_messages_per_interview"]}件')
print()
print('=' * 80)
print()
print(f'{"ユーザー名":<15} {"インタビュー数":>8} {"総メッセージ数":>10} {"平均メッセージ数":>12}')
print('-' * 80)

for result in detailed_results:
    print(f'{result["user_name"]:<15} '
          f'{result["interview_count"]:>8}件 '
          f'{result["total_messages"]:>10}件 '
          f'{result["average_messages_per_interview"]:>12}件')

print('=' * 80)
print()
print(f'詳細テキスト出力: {output_detailed_txt}')
print(f'詳細JSON出力: {output_detailed_json}')
print()
print('※ 詳細ファイルには各インタビューごとの会話往復数も含まれています')
