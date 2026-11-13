#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json

def extract_top_bottom_clusters_by_count(json_filepath, output_prefix):
    """
    JSONファイルからテキスト数が多い/少ないクラスタを抽出
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

    # テキスト数でソート（降順）
    all_clusters.sort(key=lambda x: x['text_count'], reverse=True)

    # 上位10個を取得
    top_10 = all_clusters[:10]

    # テキスト数が1のクラスタを全て取得
    count_1_clusters = [c for c in all_clusters if c['text_count'] == 1]

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

    # テキスト数1のクラスタをJSON形式で整形（平均類似度でソート）
    count_1_formatted = []
    # 平均類似度でソート（降順）
    count_1_clusters.sort(key=lambda x: x['average_similarity'], reverse=True)

    for i, cluster in enumerate(count_1_clusters, 1):
        count_1_formatted.append({
            'rank_by_similarity': i,
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
            'source_file': json_filepath,
            'sorting_criteria': 'text_count',
            'count_1_clusters_total': len(count_1_clusters)
        },
        'top_10_clusters_by_count': top_10_formatted,
        'all_count_1_clusters': count_1_formatted
    }

    # JSONファイルに出力
    output_json_path = f'{output_prefix}_by_count.json'
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    # コンソールに表示
    print(f"\n{'='*90}")
    print(f"Dataset: {output_prefix}")
    print(f"Total clusters: {len(all_clusters)}")
    print(f"Count-1 clusters: {len(count_1_clusters)}")
    print(f"Sorting by: Text Count")
    print(f"{'='*90}")

    print(f"\n上位10クラスタ (テキスト数が多い):")
    print(f"{'Rank':<6} {'Category':<15} {'Cluster':<10} {'Count':<7} {'Avg Sim':<10} {'Concept':<40}")
    print("-" * 90)
    for cluster in top_10_formatted:
        print(f"{cluster['rank']:<6} {cluster['category']:<15} {cluster['cluster_id']:<10} "
              f"{cluster['statistics']['text_count']:<7} "
              f"{cluster['statistics']['average_similarity']:<10.4f} "
              f"{cluster['concept_name'][:40]:<40}")

    print(f"\nテキスト数=1のクラスタ (全{len(count_1_clusters)}件、平均類似度でソート):")
    print(f"{'Rank':<6} {'Category':<15} {'Cluster':<10} {'Avg Sim':<10} {'Concept':<50}")
    print("-" * 93)
    for cluster in count_1_formatted[:20]:  # 最初の20件だけ表示
        print(f"{cluster['rank_by_similarity']:<6} {cluster['category']:<15} {cluster['cluster_id']:<10} "
              f"{cluster['statistics']['average_similarity']:<10.4f} "
              f"{cluster['concept_name'][:50]:<50}")

    if len(count_1_formatted) > 20:
        print(f"... (残り{len(count_1_formatted) - 20}件)")

    print(f"\n出力ファイル:")
    print(f"  - {output_json_path}")

    return output_data


# メイン処理
if __name__ == "__main__":
    base_path = '/Users/mana/Desktop/AudioInterview/data'

    # Matsushitaを分析
    print("\n" + "=" * 90)
    print("Matsushita Dataset Analysis - Sorted by Text Count")
    print("=" * 90)
    matsushita_data = extract_top_bottom_clusters_by_count(
        f'{base_path}/cluster_quality_matsushita.json',
        f'{base_path}/matsushita_clusters'
    )

    # Uchidaを分析
    print("\n" + "=" * 90)
    print("Uchida Dataset Analysis - Sorted by Text Count")
    print("=" * 90)
    uchida_data = extract_top_bottom_clusters_by_count(
        f'{base_path}/cluster_quality_uchida.json',
        f'{base_path}/uchida_clusters'
    )

    print("\n" + "=" * 90)
    print("Analysis Complete!")
    print("=" * 90)
