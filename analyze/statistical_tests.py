#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import statistics
import math

def load_cluster_data(json_filepath):
    """クラスタデータを読み込む"""
    with open(json_filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    text_counts = []
    avg_similarities = []
    categories = []

    for category, category_data in data.items():
        if 'baseline_clusters' in category_data:
            for cluster_id, cluster_info in category_data['baseline_clusters'].items():
                text_counts.append(cluster_info.get('text_count', 0))
                avg_similarities.append(cluster_info.get('average_similarity', 0))
                categories.append(category)

    return {
        'text_counts': text_counts,
        'avg_similarities': avg_similarities,
        'categories': categories
    }


def mann_whitney_u_test(sample1, sample2):
    """
    Mann-Whitney U検定（ノンパラメトリック）
    2つのサンプルの分布が異なるかを検定
    """
    n1 = len(sample1)
    n2 = len(sample2)

    # 全データを結合してランク付け
    combined = [(val, 1) for val in sample1] + [(val, 2) for val in sample2]
    combined.sort(key=lambda x: x[0])

    # ランクを計算（同順位の場合は平均ランクを使用）
    ranks = []
    i = 0
    while i < len(combined):
        j = i
        # 同じ値を持つ要素を見つける
        while j < len(combined) and combined[j][0] == combined[i][0]:
            j += 1
        # 平均ランクを計算（ランクは1から始まる）
        avg_rank = (i + 1 + j) / 2
        for k in range(i, j):
            ranks.append((combined[k][1], avg_rank))
        i = j

    # 各グループのランク合計を計算
    rank_sum1 = sum(rank for group, rank in ranks if group == 1)
    rank_sum2 = sum(rank for group, rank in ranks if group == 2)

    # U統計量を計算
    u1 = rank_sum1 - n1 * (n1 + 1) / 2
    u2 = rank_sum2 - n2 * (n2 + 1) / 2

    # 小さい方のU統計量を使用
    u = min(u1, u2)

    # Z統計量を計算（正規近似）
    mean_u = n1 * n2 / 2
    std_u = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)

    if std_u == 0:
        z = 0
    else:
        z = (u - mean_u) / std_u

    # p値の近似（両側検定）
    # 正規分布の累積分布関数の近似
    p_value = 2 * (1 - normal_cdf(abs(z)))

    return {
        'U': u,
        'Z': z,
        'p_value': p_value,
        'n1': n1,
        'n2': n2
    }


def normal_cdf(z):
    """標準正規分布の累積分布関数の近似"""
    # エラー関数を使った近似
    return 0.5 * (1 + erf(z / math.sqrt(2)))


def erf(x):
    """エラー関数の近似（Abramowitz and Stegun formula）"""
    # 定数
    a1 =  0.254829592
    a2 = -0.284496736
    a3 =  1.421413741
    a4 = -1.453152027
    a5 =  1.061405429
    p  =  0.3275911

    # 符号を保存
    sign = 1 if x >= 0 else -1
    x = abs(x)

    # Abramowitz and Stegun formula
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)

    return sign * y


def welch_t_test(sample1, sample2):
    """
    Welchのt検定（等分散を仮定しない）
    """
    n1 = len(sample1)
    n2 = len(sample2)

    mean1 = statistics.mean(sample1)
    mean2 = statistics.mean(sample2)

    var1 = statistics.variance(sample1) if n1 > 1 else 0
    var2 = statistics.variance(sample2) if n2 > 1 else 0

    # Welchのt統計量
    if var1 / n1 + var2 / n2 == 0:
        t = 0
        df = n1 + n2 - 2
    else:
        t = (mean1 - mean2) / math.sqrt(var1 / n1 + var2 / n2)

        # Welch-Satterthwaite自由度
        numerator = (var1 / n1 + var2 / n2) ** 2
        denominator = (var1 / n1) ** 2 / (n1 - 1) + (var2 / n2) ** 2 / (n2 - 1)
        df = numerator / denominator if denominator > 0 else n1 + n2 - 2

    # p値の近似（両側検定、正規近似）
    z = abs(t)
    p_value = 2 * (1 - normal_cdf(z))

    return {
        't': t,
        'df': df,
        'p_value': p_value,
        'mean1': mean1,
        'mean2': mean2,
        'var1': var1,
        'var2': var2
    }


def cohens_d(sample1, sample2):
    """Cohen's d効果量を計算"""
    mean1 = statistics.mean(sample1)
    mean2 = statistics.mean(sample2)

    n1 = len(sample1)
    n2 = len(sample2)

    var1 = statistics.variance(sample1) if n1 > 1 else 0
    var2 = statistics.variance(sample2) if n2 > 1 else 0

    # プールされた標準偏差
    pooled_std = math.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))

    if pooled_std == 0:
        return 0

    d = (mean1 - mean2) / pooled_std
    return d


# メイン処理
if __name__ == "__main__":
    base_path = '/Users/mana/Desktop/AudioInterview/data'

    print("\n" + "=" * 80)
    print("統計的有意差検定")
    print("=" * 80 + "\n")

    # データ読み込み
    matsushita_data = load_cluster_data(f'{base_path}/cluster_quality_matsushita.json')
    uchida_data = load_cluster_data(f'{base_path}/cluster_quality_uchida.json')

    print("データセット概要:")
    print("-" * 80)
    print(f"Matsushita (Full): {len(matsushita_data['text_counts'])} clusters")
    print(f"Uchida: {len(uchida_data['text_counts'])} clusters")
    print()

    # 1. クラスタあたりのテキスト数の比較
    print("【1】クラスタあたりのテキスト数の比較")
    print("-" * 80)

    mat_counts = matsushita_data['text_counts']
    uch_counts = uchida_data['text_counts']

    print(f"Matsushita (Full): Mean={statistics.mean(mat_counts):.2f}, SD={statistics.stdev(mat_counts):.2f}")
    print(f"Uchida: Mean={statistics.mean(uch_counts):.2f}, SD={statistics.stdev(uch_counts):.2f}")
    print()

    # Welchのt検定
    t_result = welch_t_test(mat_counts, uch_counts)
    print("Welch's t-test:")
    print(f"  t = {t_result['t']:.4f}, df = {t_result['df']:.2f}")
    print(f"  p-value = {t_result['p_value']:.4f}")
    print(f"  結果: {'有意差あり (p < 0.05)' if t_result['p_value'] < 0.05 else '有意差なし (p >= 0.05)'}")
    print()

    # Mann-Whitney U検定
    u_result = mann_whitney_u_test(mat_counts, uch_counts)
    print("Mann-Whitney U test (ノンパラメトリック):")
    print(f"  U = {u_result['U']:.4f}, Z = {u_result['Z']:.4f}")
    print(f"  p-value = {u_result['p_value']:.4f}")
    print(f"  結果: {'有意差あり (p < 0.05)' if u_result['p_value'] < 0.05 else '有意差なし (p >= 0.05)'}")
    print()

    # 効果量
    d = cohens_d(mat_counts, uch_counts)
    print(f"Cohen's d (効果量): {d:.4f}")
    effect_interpretation = "小" if abs(d) < 0.5 else ("中" if abs(d) < 0.8 else "大")
    print(f"  解釈: {effect_interpretation}サイズの効果")
    print()

    # 2. 平均類似度の比較
    print("\n【2】平均類似度の比較")
    print("-" * 80)

    mat_sims = matsushita_data['avg_similarities']
    uch_sims = uchida_data['avg_similarities']

    print(f"Matsushita (Full): Mean={statistics.mean(mat_sims):.4f}, SD={statistics.stdev(mat_sims):.4f}")
    print(f"Uchida: Mean={statistics.mean(uch_sims):.4f}, SD={statistics.stdev(uch_sims):.4f}")
    print()

    # Welchのt検定
    t_result_sim = welch_t_test(mat_sims, uch_sims)
    print("Welch's t-test:")
    print(f"  t = {t_result_sim['t']:.4f}, df = {t_result_sim['df']:.2f}")
    print(f"  p-value = {t_result_sim['p_value']:.4f}")
    print(f"  結果: {'有意差あり (p < 0.05)' if t_result_sim['p_value'] < 0.05 else '有意差なし (p >= 0.05)'}")
    print()

    # Mann-Whitney U検定
    u_result_sim = mann_whitney_u_test(mat_sims, uch_sims)
    print("Mann-Whitney U test (ノンパラメトリック):")
    print(f"  U = {u_result_sim['U']:.4f}, Z = {u_result_sim['Z']:.4f}")
    print(f"  p-value = {u_result_sim['p_value']:.4f}")
    print(f"  結果: {'有意差あり (p < 0.05)' if u_result_sim['p_value'] < 0.05 else '有意差なし (p >= 0.05)'}")
    print()

    # 効果量
    d_sim = cohens_d(mat_sims, uch_sims)
    print(f"Cohen's d (効果量): {d_sim:.4f}")
    effect_interpretation_sim = "小" if abs(d_sim) < 0.5 else ("中" if abs(d_sim) < 0.8 else "大")
    print(f"  解釈: {effect_interpretation_sim}サイズの効果")
    print()

    # 結果をJSONに保存
    results = {
        'text_count_comparison': {
            'matsushita_mean': statistics.mean(mat_counts),
            'uchida_mean': statistics.mean(uch_counts),
            'welch_t_test': {
                't': t_result['t'],
                'df': t_result['df'],
                'p_value': t_result['p_value'],
                'significant': t_result['p_value'] < 0.05
            },
            'mann_whitney_u_test': {
                'U': u_result['U'],
                'Z': u_result['Z'],
                'p_value': u_result['p_value'],
                'significant': u_result['p_value'] < 0.05
            },
            'cohens_d': d
        },
        'similarity_comparison': {
            'matsushita_mean': statistics.mean(mat_sims),
            'uchida_mean': statistics.mean(uch_sims),
            'welch_t_test': {
                't': t_result_sim['t'],
                'df': t_result_sim['df'],
                'p_value': t_result_sim['p_value'],
                'significant': t_result_sim['p_value'] < 0.05
            },
            'mann_whitney_u_test': {
                'U': u_result_sim['U'],
                'Z': u_result_sim['Z'],
                'p_value': u_result_sim['p_value'],
                'significant': u_result_sim['p_value'] < 0.05
            },
            'cohens_d': d_sim
        }
    }

    output_path = f'{base_path}/statistical_test_results.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("=" * 80)
    print(f"結果をJSONに保存: {output_path}")
    print("=" * 80)
