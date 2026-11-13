#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json

def extract_top_bottom_clusters(json_filepath, output_prefix):
    """
    JSONファイルから平均類似度が高い/低いクラスタを抽出
    """
    # JSONファイルを読み込む
    with open(json_filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # すべてのクラスタを収集
    all_clusters = []

    for category, category_data in data.items():
        if 'baseline_clusters' in category_data:
            for cluster_id, cluster_info in category_data['baseline_clusters'].items():
                all_clusters.append({
                    'category': category,
                    'cluster_id': cluster_id,
                    'concept_name': cluster_info.get('concept_name', ''),
                    'text_count': cluster_info.get('text_count', 0),
                    'average_similarity': cluster_info.get('average_similarity', 0),
                    'std_similarity': cluster_info.get('std_similarity', 0),
                    'min_similarity': cluster_info.get('min_similarity', 0),
                    'max_similarity': cluster_info.get('max_similarity', 0),
                    'texts': cluster_info.get('texts', []),
                    'similarities': cluster_info.get('similarities', [])
                })

    # 平均類似度でソート
    all_clusters.sort(key=lambda x: x['average_similarity'], reverse=True)

    # 上位10個と下位10個を取得
    top_10 = all_clusters[:10]
    bottom_10 = all_clusters[-10:]

    # 上位10個をJSON形式で整形
    top_10_formatted = []
    for i, cluster in enumerate(top_10, 1):
        top_10_formatted.append({
            'rank': i,
            'category': cluster['category'],
            'cluster_id': cluster['cluster_id'],
            'concept_name': cluster['concept_name'],
            'statistics': {
                'text_count': cluster['text_count'],
                'average_similarity': round(cluster['average_similarity'], 4),
                'std_similarity': round(cluster['std_similarity'], 4),
                'min_similarity': round(cluster['min_similarity'], 4),
                'max_similarity': round(cluster['max_similarity'], 4)
            },
            'texts': cluster['texts'],
            'similarities': [round(s, 4) for s in cluster['similarities']]
        })

    # 下位10個をJSON形式で整形
    bottom_10_formatted = []
    for i, cluster in enumerate(bottom_10, 1):
        bottom_10_formatted.append({
            'rank': len(all_clusters) - 10 + i,
            'category': cluster['category'],
            'cluster_id': cluster['cluster_id'],
            'concept_name': cluster['concept_name'],
            'statistics': {
                'text_count': cluster['text_count'],
                'average_similarity': round(cluster['average_similarity'], 4),
                'std_similarity': round(cluster['std_similarity'], 4),
                'min_similarity': round(cluster['min_similarity'], 4),
                'max_similarity': round(cluster['max_similarity'], 4)
            },
            'texts': cluster['texts'],
            'similarities': [round(s, 4) for s in cluster['similarities']]
        })

    # 統合されたJSONを作成
    output_data = {
        'dataset_info': {
            'total_clusters': len(all_clusters),
            'source_file': json_filepath
        },
        'top_10_clusters': top_10_formatted,
        'bottom_10_clusters': bottom_10_formatted
    }

    # JSONファイルに出力
    output_json_path = f'{output_prefix}_analysis.json'
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    # コンソールに表示
    print(f"\n{'='*80}")
    print(f"Dataset: {output_prefix}")
    print(f"Total clusters: {len(all_clusters)}")
    print(f"{'='*80}")

    print(f"\n上位10クラスタ (平均類似度が高い):")
    print(f"{'Rank':<6} {'Category':<15} {'Cluster':<10} {'Avg Sim':<10} {'Count':<7} {'Concept':<40}")
    print("-" * 88)
    for cluster in top_10_formatted:
        print(f"{cluster['rank']:<6} {cluster['category']:<15} {cluster['cluster_id']:<10} "
              f"{cluster['statistics']['average_similarity']:<10.4f} "
              f"{cluster['statistics']['text_count']:<7} "
              f"{cluster['concept_name'][:40]:<40}")

    print(f"\n下位10クラスタ (平均類似度が低い):")
    print(f"{'Rank':<6} {'Category':<15} {'Cluster':<10} {'Avg Sim':<10} {'Count':<7} {'Concept':<40}")
    print("-" * 88)
    for cluster in bottom_10_formatted:
        print(f"{cluster['rank']:<6} {cluster['category']:<15} {cluster['cluster_id']:<10} "
              f"{cluster['statistics']['average_similarity']:<10.4f} "
              f"{cluster['statistics']['text_count']:<7} "
              f"{cluster['concept_name'][:40]:<40}")

    print(f"\n出力ファイル:")
    print(f"  - {output_json_path}")

    return output_data


# メイン処理
if __name__ == "__main__":
    base_path = '/Users/mana/Desktop/AudioInterview/data'

    # Matsushitaを分析
    print("\n" + "=" * 80)
    print("Matsushita Dataset Analysis")
    print("=" * 80)
    matsushita_data = extract_top_bottom_clusters(
        f'{base_path}/cluster_quality_matsushita.json',
        f'{base_path}/matsushita_clusters'
    )

    # Uchidaを分析
    print("\n" + "=" * 80)
    print("Uchida Dataset Analysis")
    print("=" * 80)
    uchida_data = extract_top_bottom_clusters(
        f'{base_path}/cluster_quality_uchida.json',
        f'{base_path}/uchida_clusters'
    )

    print("\n" + "=" * 80)
    print("Analysis Complete!")
    print("=" * 80)
