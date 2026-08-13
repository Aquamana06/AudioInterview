#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import random

def extract_low_similarity_texts(json_filepath, output_prefix, threshold=0.3, sample_size=100):
    """
    類似度が閾値未満のテキストをランダムサンプリング
    """
    # JSONファイルを読み込む
    with open(json_filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 類似度が閾値未満のテキストを収集
    low_similarity_texts = []

    for category, category_data in data.items():
        if 'baseline_clusters' in category_data:
            for cluster_id, cluster_info in category_data['baseline_clusters'].items():
                concept_name = cluster_info.get('concept_name', '')
                texts = cluster_info.get('texts', [])
                similarities = cluster_info.get('similarities', [])

                # テキストと類似度をペアにして追加
                for text, similarity in zip(texts, similarities):
                    if similarity < threshold:
                        low_similarity_texts.append({
                            'category': category,
                            'cluster_id': cluster_id,
                            'concept_name': concept_name,
                            'text': text,
                            'similarity': similarity
                        })

    # 類似度でソート（昇順）
    low_similarity_texts.sort(key=lambda x: x['similarity'])

    # サンプリング数を調整
    actual_sample_size = min(sample_size, len(low_similarity_texts))

    # ランダムサンプリング
    random.seed(42)  # 再現性のためのシード
    sampled_texts = random.sample(low_similarity_texts, actual_sample_size)

    # サンプリング結果を類似度でソート
    sampled_texts.sort(key=lambda x: x['similarity'])

    # JSON形式で整形
    sampled_formatted = []
    for i, item in enumerate(sampled_texts, 1):
        sampled_formatted.append({
            'sample_id': i,
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
            'threshold': threshold,
            'total_low_similarity_texts': len(low_similarity_texts),
            'sample_size': actual_sample_size,
            'source_file': json_filepath
        },
        'sampled_low_similarity_texts': sampled_formatted
    }

    # JSONファイルに出力
    output_json_path = f'{output_prefix}_low_similarity_sample.json'
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    # コンソールに表示
    print(f"\n{'='*100}")
    print(f"Dataset: {output_prefix}")
    print(f"Threshold: similarity < {threshold}")
    print(f"Total texts below threshold: {len(low_similarity_texts)}")
    print(f"Sample size: {actual_sample_size}")
    print(f"{'='*100}")

    print(f"\nサンプル統計:")
    if sampled_formatted:
        similarities = [item['similarity'] for item in sampled_formatted]
        print(f"  最小類似度: {min(similarities):.4f}")
        print(f"  最大類似度: {max(similarities):.4f}")
        print(f"  平均類似度: {sum(similarities)/len(similarities):.4f}")

    print(f"\n最初の10件:")
    print(f"{'ID':<6} {'Similarity':<12} {'Concept':<35} {'Text':<50}")
    print("-" * 105)
    for item in sampled_formatted[:10]:
        text_preview = item['text'][:50] + '...' if len(item['text']) > 50 else item['text']
        concept_preview = item['cluster_info']['concept_name'][:35]
        print(f"{item['sample_id']:<6} {item['similarity']:<12.4f} {concept_preview:<35} {text_preview:<50}")

    print(f"\n出力ファイル:")
    print(f"  - {output_json_path}")

    return output_data


# メイン処理
if __name__ == "__main__":
    base_path = '/Users/mana/Desktop/AudioInterview/data'

    # Matsushitaを分析
    print("\n" + "=" * 100)
    print("Matsushita Dataset - Low Similarity Text Sampling")
    print("=" * 100)
    matsushita_data = extract_low_similarity_texts(
        f'{base_path}/cluster_quality_matsushita.json',
        f'{base_path}/matsushita_clusters',
        threshold=0.3,
        sample_size=100
    )

    # Uchidaを分析
    print("\n" + "=" * 100)
    print("Uchida Dataset - Low Similarity Text Sampling")
    print("=" * 100)
    uchida_data = extract_low_similarity_texts(
        f'{base_path}/cluster_quality_uchida.json',
        f'{base_path}/uchida_clusters',
        threshold=0.3,
        sample_size=100
    )

    print("\n" + "=" * 100)
    print("Analysis Complete!")
    print("=" * 100)
