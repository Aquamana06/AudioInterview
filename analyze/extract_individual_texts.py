#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json

def extract_top_bottom_individual_texts(json_filepath, output_prefix):
    """
    個々のテキストの類似度で上位・下位を抽出
    """
    # JSONファイルを読み込む
    with open(json_filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # すべてのテキストと類似度を収集
    all_texts_data = []

    for category, category_data in data.items():
        if 'baseline_clusters' in category_data:
            for cluster_id, cluster_info in category_data['baseline_clusters'].items():
                concept_name = cluster_info.get('concept_name', '')
                texts = cluster_info.get('texts', [])
                similarities = cluster_info.get('similarities', [])

                # テキストと類似度をペアにして追加
                for text, similarity in zip(texts, similarities):
                    all_texts_data.append({
                        'category': category,
                        'cluster_id': cluster_id,
                        'concept_name': concept_name,
                        'text': text,
                        'similarity': similarity
                    })

    # 類似度でソート（降順）
    all_texts_data.sort(key=lambda x: x['similarity'], reverse=True)

    # 上位10個と下位10個を取得
    top_10 = all_texts_data[:10]
    bottom_10 = all_texts_data[-10:]

    # JSON形式で整形
    top_10_formatted = []
    for i, item in enumerate(top_10, 1):
        top_10_formatted.append({
            'rank': i,
            'similarity': round(item['similarity'], 4),
            'text': item['text'],
            'cluster_info': {
                'category': item['category'],
                'cluster_id': item['cluster_id'],
                'concept_name': item['concept_name']
            }
        })

    bottom_10_formatted = []
    for i, item in enumerate(bottom_10, 1):
        bottom_10_formatted.append({
            'rank': len(all_texts_data) - 10 + i,
            'similarity': round(item['similarity'], 4),
            'text': item['text'],
            'cluster_info': {
                'category': item['category'],
                'cluster_id': item['cluster_id'],
                'concept_name': item['concept_name']
            }
        })

    # 統合されたJSONを作成
    output_data = {
        'dataset_info': {
            'total_texts': len(all_texts_data),
            'source_file': json_filepath
        },
        'top_10_texts_by_similarity': top_10_formatted,
        'bottom_10_texts_by_similarity': bottom_10_formatted
    }

    # JSONファイルに出力
    output_json_path = f'{output_prefix}_individual_texts.json'
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    # コンソールに表示
    print(f"\n{'='*100}")
    print(f"Dataset: {output_prefix}")
    print(f"Total individual texts: {len(all_texts_data)}")
    print(f"{'='*100}")

    print(f"\n上位10テキスト (類似度が最も高い):")
    print(f"{'Rank':<6} {'Similarity':<12} {'Concept':<35} {'Text':<50}")
    print("-" * 105)
    for item in top_10_formatted:
        text_preview = item['text'][:50] + '...' if len(item['text']) > 50 else item['text']
        concept_preview = item['cluster_info']['concept_name'][:35]
        print(f"{item['rank']:<6} {item['similarity']:<12.4f} {concept_preview:<35} {text_preview:<50}")

    print(f"\n下位10テキスト (類似度が最も低い):")
    print(f"{'Rank':<6} {'Similarity':<12} {'Concept':<35} {'Text':<50}")
    print("-" * 105)
    for item in bottom_10_formatted:
        text_preview = item['text'][:50] + '...' if len(item['text']) > 50 else item['text']
        concept_preview = item['cluster_info']['concept_name'][:35]
        print(f"{item['rank']:<6} {item['similarity']:<12.4f} {concept_preview:<35} {text_preview:<50}")

    print(f"\n出力ファイル:")
    print(f"  - {output_json_path}")

    return output_data


# メイン処理
if __name__ == "__main__":
    base_path = '/Users/mana/Desktop/AudioInterview/data'

    # Matsushitaを分析
    print("\n" + "=" * 100)
    print("Matsushita Dataset - Individual Text Analysis")
    print("=" * 100)
    matsushita_data = extract_top_bottom_individual_texts(
        f'{base_path}/cluster_quality_matsushita.json',
        f'{base_path}/matsushita_clusters'
    )

    # Uchidaを分析
    print("\n" + "=" * 100)
    print("Uchida Dataset - Individual Text Analysis")
    print("=" * 100)
    uchida_data = extract_top_bottom_individual_texts(
        f'{base_path}/cluster_quality_uchida.json',
        f'{base_path}/uchida_clusters'
    )

    print("\n" + "=" * 100)
    print("Analysis Complete!")
    print("=" * 100)
