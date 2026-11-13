#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
uchida_0.35.json用の分析スクリプト
baseline_clustersとnew_clustersの両方を含めて分析
"""

import json
import random

def load_all_clusters(json_filepath):
    """baseline_clustersとnew_clustersの両方を読み込む"""
    with open(json_filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    all_clusters = []

    for category in ['action', 'background_factor']:
        if category not in data:
            continue

        category_data = data[category]

        # baseline_clustersを追加
        if 'baseline_clusters' in category_data:
            for cluster_id, cluster_info in category_data['baseline_clusters'].items():
                all_clusters.append({
                    'category': category,
                    'cluster_type': 'baseline',
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

        # new_clustersを追加
        if 'new_clusters' in category_data:
            for cluster_id, cluster_info in category_data['new_clusters'].items():
                all_clusters.append({
                    'category': category,
                    'cluster_type': 'new',
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

    return all_clusters


def create_analysis_file(all_clusters, output_path, source_file):
    """平均類似度でソートした分析ファイルを作成"""
    all_clusters.sort(key=lambda x: x['average_similarity'], reverse=True)

    output_data = {
        'dataset_info': {
            'total_clusters': len(all_clusters),
            'source_file': source_file,
            'includes_new_clusters': True,
            'baseline_count': len([c for c in all_clusters if c['cluster_type'] == 'baseline']),
            'new_count': len([c for c in all_clusters if c['cluster_type'] == 'new'])
        },
        'top_10_clusters': [],
        'bottom_10_clusters': []
    }

    # Top 10
    for rank, cluster in enumerate(all_clusters[:10], start=1):
        output_data['top_10_clusters'].append({
            'rank': rank,
            'category': cluster['category'],
            'cluster_type': cluster['cluster_type'],
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

    # Bottom 10
    for rank, cluster in enumerate(all_clusters[-10:], len(all_clusters)-9):
        output_data['bottom_10_clusters'].append({
            'rank': rank,
            'category': cluster['category'],
            'cluster_type': cluster['cluster_type'],
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

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Created: {output_path}")
    print(f"  Total clusters: {len(all_clusters)} (baseline: {output_data['dataset_info']['baseline_count']}, new: {output_data['dataset_info']['new_count']})")
    print(f"  Top similarity: {all_clusters[0]['average_similarity']:.4f}")
    print(f"  Bottom similarity: {all_clusters[-1]['average_similarity']:.4f}")


def create_by_count_file(all_clusters, output_path, source_file):
    """テキスト数でソートした分析ファイルを作成"""
    clusters_by_count = sorted(all_clusters, key=lambda x: x['text_count'], reverse=True)
    count_1_clusters = [c for c in all_clusters if c['text_count'] == 1]
    count_1_clusters_sorted = sorted(count_1_clusters, key=lambda x: x['average_similarity'], reverse=True)

    output_data = {
        'dataset_info': {
            'total_clusters': len(all_clusters),
            'source_file': source_file,
            'sorting_criteria': 'text_count',
            'count_1_clusters_total': len(count_1_clusters),
            'includes_new_clusters': True,
            'baseline_count': len([c for c in all_clusters if c['cluster_type'] == 'baseline']),
            'new_count': len([c for c in all_clusters if c['cluster_type'] == 'new'])
        },
        'top_10_clusters_by_count': [],
        'all_count_1_clusters': []
    }

    # Top 10 by count
    for rank, cluster in enumerate(clusters_by_count[:10], start=1):
        output_data['top_10_clusters_by_count'].append({
            'rank': rank,
            'category': cluster['category'],
            'cluster_type': cluster['cluster_type'],
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

    # All count-1 clusters
    for rank, cluster in enumerate(count_1_clusters_sorted, start=1):
        output_data['all_count_1_clusters'].append({
            'rank_by_similarity': rank,
            'category': cluster['category'],
            'cluster_type': cluster['cluster_type'],
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

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Created: {output_path}")
    print(f"  Total clusters: {len(all_clusters)}")
    print(f"  Count-1 clusters: {len(count_1_clusters)}")
    print(f"  Max text count: {clusters_by_count[0]['text_count']}")


def create_individual_texts_file(all_clusters, output_path, source_file):
    """個々のテキストの類似度分析ファイルを作成"""
    all_texts = []
    for cluster in all_clusters:
        for text, similarity in zip(cluster['texts'], cluster['similarities']):
            all_texts.append({
                'text': text,
                'similarity': similarity,
                'category': cluster['category'],
                'cluster_type': cluster['cluster_type'],
                'cluster_id': cluster['cluster_id'],
                'concept_name': cluster['concept_name']
            })

    all_texts_sorted = sorted(all_texts, key=lambda x: x['similarity'], reverse=True)

    output_data = {
        'dataset_info': {
            'total_texts': len(all_texts),
            'source_file': source_file,
            'includes_new_clusters': True
        },
        'top_10_texts_by_similarity': [],
        'bottom_10_texts_by_similarity': []
    }

    # Top 10
    for rank, text_info in enumerate(all_texts_sorted[:10], start=1):
        output_data['top_10_texts_by_similarity'].append({
            'rank': rank,
            'similarity': round(text_info['similarity'], 4),
            'text': text_info['text'],
            'cluster_info': {
                'category': text_info['category'],
                'cluster_type': text_info['cluster_type'],
                'cluster_id': text_info['cluster_id'],
                'concept_name': text_info['concept_name']
            }
        })

    # Bottom 10
    for rank, text_info in enumerate(all_texts_sorted[-10:], len(all_texts_sorted)-9):
        output_data['bottom_10_texts_by_similarity'].append({
            'rank': rank,
            'similarity': round(text_info['similarity'], 4),
            'text': text_info['text'],
            'cluster_info': {
                'category': text_info['category'],
                'cluster_type': text_info['cluster_type'],
                'cluster_id': text_info['cluster_id'],
                'concept_name': text_info['concept_name']
            }
        })

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Created: {output_path}")
    print(f"  Total texts: {len(all_texts)}")
    print(f"  Highest similarity: {all_texts_sorted[0]['similarity']:.4f}")
    print(f"  Lowest similarity: {all_texts_sorted[-1]['similarity']:.4f}")


def create_low_similarity_file(all_clusters, output_path, source_file, threshold=0.3, sample_size=100):
    """低類似度テキストのサンプリングファイルを作成"""
    all_texts = []
    for cluster in all_clusters:
        for text, similarity in zip(cluster['texts'], cluster['similarities']):
            if similarity < threshold:
                all_texts.append({
                    'text': text,
                    'similarity': similarity,
                    'category': cluster['category'],
                    'cluster_type': cluster['cluster_type'],
                    'cluster_id': cluster['cluster_id'],
                    'concept_name': cluster['concept_name']
                })

    all_texts_sorted = sorted(all_texts, key=lambda x: x['similarity'])
    actual_sample_size = min(sample_size, len(all_texts))

    # ランダムサンプリングではなく、最初の100件を取る（最も類似度が低い順）
    sampled_texts = all_texts_sorted[:actual_sample_size]

    output_data = {
        'dataset_info': {
            'threshold': threshold,
            'total_low_similarity_texts': len(all_texts),
            'sample_size': actual_sample_size,
            'source_file': source_file,
            'includes_new_clusters': True
        },
        'sampled_low_similarity_texts': []
    }

    for sample_id, text_info in enumerate(sampled_texts, start=1):
        output_data['sampled_low_similarity_texts'].append({
            'sample_id': sample_id,
            'similarity': round(text_info['similarity'], 4),
            'text': text_info['text'],
            'cluster_info': {
                'category': text_info['category'],
                'cluster_type': text_info['cluster_type'],
                'cluster_id': text_info['cluster_id'],
                'concept_name': text_info['concept_name']
            }
        })

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Created: {output_path}")
    print(f"  Threshold: {threshold}")
    print(f"  Total low similarity texts: {len(all_texts)}")
    print(f"  Sample size: {actual_sample_size}")


# メイン処理
if __name__ == "__main__":
    base_path = '/Users/mana/Desktop/AudioInterview/data'
    input_file = f'{base_path}/cluster_quality_uchida_0.35.json'
    output_prefix = f'{base_path}/uchida_0.35_clusters'

    print("\n" + "=" * 100)
    print("Uchida 0.35 Dataset Analysis (Including both baseline_clusters and new_clusters)")
    print("=" * 100)

    # Load all clusters
    all_clusters = load_all_clusters(input_file)

    # 1. Analysis by average similarity
    create_analysis_file(all_clusters, f'{output_prefix}_analysis.json', 'cluster_quality_uchida_0.35.json')

    # 2. Analysis by text count
    create_by_count_file(all_clusters, f'{output_prefix}_by_count.json', 'cluster_quality_uchida_0.35.json')

    # 3. Individual texts analysis
    create_individual_texts_file(all_clusters, f'{output_prefix}_individual_texts.json', 'cluster_quality_uchida_0.35.json')

    # 4. Low similarity texts
    create_low_similarity_file(all_clusters, f'{output_prefix}_low_similarity_sample.json', 'cluster_quality_uchida_0.35.json')

    print("\n" + "=" * 100)
    print("Analysis Complete! All files created successfully.")
    print("=" * 100)
