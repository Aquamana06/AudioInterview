#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import statistics

def calculate_overall_statistics(json_filepath, dataset_name):
    """
    データセット全体の統計を計算
    """
    # JSONファイルを読み込む
    with open(json_filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # すべてのクラスタの平均類似度を収集
    all_avg_similarities = []
    all_text_counts = []

    for category, category_data in data.items():
        if 'baseline_clusters' in category_data:
            for cluster_id, cluster_info in category_data['baseline_clusters'].items():
                avg_sim = cluster_info.get('average_similarity', 0)
                text_count = cluster_info.get('text_count', 0)
                all_avg_similarities.append(avg_sim)
                all_text_counts.append(text_count)

    # パーセンタイルの計算
    all_avg_similarities_sorted = sorted(all_avg_similarities)
    all_text_counts_sorted = sorted(all_text_counts)

    def percentile(data, p):
        n = len(data)
        k = (n - 1) * p / 100
        f = int(k)
        c = f + 1
        if c >= n:
            return data[-1]
        d0 = data[f]
        d1 = data[c]
        return d0 + (d1 - d0) * (k - f)

    # 全体統計を計算
    overall_stats = {
        'dataset_name': dataset_name,
        'total_clusters': len(all_avg_similarities),
        'total_texts': sum(all_text_counts),
        'average_similarity': {
            'mean': statistics.mean(all_avg_similarities),
            'std': statistics.stdev(all_avg_similarities) if len(all_avg_similarities) > 1 else 0,
            'median': statistics.median(all_avg_similarities),
            'min': min(all_avg_similarities),
            'max': max(all_avg_similarities),
            'percentile_25': percentile(all_avg_similarities_sorted, 25),
            'percentile_75': percentile(all_avg_similarities_sorted, 75)
        },
        'text_count': {
            'mean': statistics.mean(all_text_counts),
            'std': statistics.stdev(all_text_counts) if len(all_text_counts) > 1 else 0,
            'median': statistics.median(all_text_counts),
            'min': min(all_text_counts),
            'max': max(all_text_counts),
            'percentile_25': percentile(all_text_counts_sorted, 25),
            'percentile_75': percentile(all_text_counts_sorted, 75)
        }
    }

    return overall_stats, all_avg_similarities, all_text_counts


# メイン処理
if __name__ == "__main__":
    base_path = '/Users/mana/Desktop/AudioInterview/data'

    # Matsushitaを分析
    print("\n" + "=" * 80)
    print("Overall Statistics Analysis")
    print("=" * 80)

    matsushita_stats, matsushita_sims, matsushita_counts = calculate_overall_statistics(
        f'{base_path}/cluster_quality_matsushita.json',
        'Matsushita'
    )

    uchida_stats, uchida_sims, uchida_counts = calculate_overall_statistics(
        f'{base_path}/cluster_quality_uchida.json',
        'Uchida'
    )

    # 比較結果を表示
    print("\n" + "-" * 80)
    print("MATSUSHITA Dataset")
    print("-" * 80)
    print(f"Total clusters: {matsushita_stats['total_clusters']}")
    print(f"Total texts: {matsushita_stats['total_texts']}")
    print()
    print("Average Similarity (across all clusters):")
    print(f"  Mean:       {matsushita_stats['average_similarity']['mean']:.4f}")
    print(f"  Std Dev:    {matsushita_stats['average_similarity']['std']:.4f}")
    print(f"  Median:     {matsushita_stats['average_similarity']['median']:.4f}")
    print(f"  Min:        {matsushita_stats['average_similarity']['min']:.4f}")
    print(f"  Max:        {matsushita_stats['average_similarity']['max']:.4f}")
    print(f"  25th %ile:  {matsushita_stats['average_similarity']['percentile_25']:.4f}")
    print(f"  75th %ile:  {matsushita_stats['average_similarity']['percentile_75']:.4f}")
    print()
    print("Text Count per Cluster:")
    print(f"  Mean:       {matsushita_stats['text_count']['mean']:.2f}")
    print(f"  Std Dev:    {matsushita_stats['text_count']['std']:.2f}")
    print(f"  Median:     {matsushita_stats['text_count']['median']:.0f}")
    print(f"  Min:        {matsushita_stats['text_count']['min']}")
    print(f"  Max:        {matsushita_stats['text_count']['max']}")

    print("\n" + "-" * 80)
    print("UCHIDA Dataset")
    print("-" * 80)
    print(f"Total clusters: {uchida_stats['total_clusters']}")
    print(f"Total texts: {uchida_stats['total_texts']}")
    print()
    print("Average Similarity (across all clusters):")
    print(f"  Mean:       {uchida_stats['average_similarity']['mean']:.4f}")
    print(f"  Std Dev:    {uchida_stats['average_similarity']['std']:.4f}")
    print(f"  Median:     {uchida_stats['average_similarity']['median']:.4f}")
    print(f"  Min:        {uchida_stats['average_similarity']['min']:.4f}")
    print(f"  Max:        {uchida_stats['average_similarity']['max']:.4f}")
    print(f"  25th %ile:  {uchida_stats['average_similarity']['percentile_25']:.4f}")
    print(f"  75th %ile:  {uchida_stats['average_similarity']['percentile_75']:.4f}")
    print()
    print("Text Count per Cluster:")
    print(f"  Mean:       {uchida_stats['text_count']['mean']:.2f}")
    print(f"  Std Dev:    {uchida_stats['text_count']['std']:.2f}")
    print(f"  Median:     {uchida_stats['text_count']['median']:.0f}")
    print(f"  Min:        {uchida_stats['text_count']['min']}")
    print(f"  Max:        {uchida_stats['text_count']['max']}")

    # 比較サマリー
    print("\n" + "=" * 80)
    print("COMPARISON SUMMARY")
    print("=" * 80)
    print(f"{'Metric':<40} {'Matsushita':<20} {'Uchida':<20}")
    print("-" * 80)
    print(f"{'Total Clusters':<40} {matsushita_stats['total_clusters']:<20} {uchida_stats['total_clusters']:<20}")
    print(f"{'Total Texts':<40} {matsushita_stats['total_texts']:<20} {uchida_stats['total_texts']:<20}")
    print(f"{'Avg Similarity (Mean)':<40} {matsushita_stats['average_similarity']['mean']:<20.4f} {uchida_stats['average_similarity']['mean']:<20.4f}")
    print(f"{'Avg Similarity (Std Dev)':<40} {matsushita_stats['average_similarity']['std']:<20.4f} {uchida_stats['average_similarity']['std']:<20.4f}")
    print(f"{'Texts per Cluster (Mean)':<40} {matsushita_stats['text_count']['mean']:<20.2f} {uchida_stats['text_count']['mean']:<20.2f}")
    print(f"{'Texts per Cluster (Std Dev)':<40} {matsushita_stats['text_count']['std']:<20.2f} {uchida_stats['text_count']['std']:<20.2f}")

    # JSONに出力
    output_data = {
        'matsushita': matsushita_stats,
        'uchida': uchida_stats,
        'comparison': {
            'similarity_difference': {
                'mean_diff': matsushita_stats['average_similarity']['mean'] - uchida_stats['average_similarity']['mean'],
                'std_diff': matsushita_stats['average_similarity']['std'] - uchida_stats['average_similarity']['std']
            },
            'text_count_difference': {
                'mean_diff': matsushita_stats['text_count']['mean'] - uchida_stats['text_count']['mean'],
                'std_diff': matsushita_stats['text_count']['std'] - uchida_stats['text_count']['std']
            }
        }
    }

    output_path = f'{base_path}/overall_statistics.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\n出力ファイル: {output_path}")
    print("=" * 80)
