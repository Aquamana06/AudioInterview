#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import LinearSegmentedColormap
import numpy as np

# 日本語フォントの設定
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'Hiragino Sans', 'Yu Gothic', 'Meiryo', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

def visualize_cluster_heatmap(json_filepath, output_prefix, dataset_name):
    """
    クラスタのテキスト数をヒートマップとして視覚化
    """
    with open(json_filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # クラスタ情報を収集
    clusters_data = []

    for category, category_data in data.items():
        if 'baseline_clusters' in category_data:
            for cluster_id, cluster_info in category_data['baseline_clusters'].items():
                clusters_data.append({
                    'category': category,
                    'cluster_id': int(cluster_id),
                    'text_count': cluster_info.get('text_count', 0),
                    'concept_name': cluster_info.get('concept_name', '')[:30]
                })

    # クラスタIDでソート
    clusters_data.sort(key=lambda x: x['cluster_id'])

    # データを抽出
    cluster_ids = [c['cluster_id'] for c in clusters_data]
    text_counts = [c['text_count'] for c in clusters_data]
    categories = [c['category'] for c in clusters_data]

    # カテゴリ別に色分け
    category_colors = {
        'action': 'blue',
        'background_factor': 'orange'
    }
    colors = [category_colors.get(cat, 'gray') for cat in categories]

    # 図1: バーチャート（カテゴリ別色分け）
    fig, ax = plt.subplots(figsize=(20, 8))
    bars = ax.bar(range(len(cluster_ids)), text_counts, color=colors, alpha=0.7, edgecolor='black', linewidth=0.5)

    ax.set_xlabel('Cluster Index', fontsize=14)
    ax.set_ylabel('Text Count', fontsize=14)
    ax.set_title(f'{dataset_name} - Text Count per Cluster', fontsize=16, fontweight='bold')
    ax.grid(axis='y', alpha=0.3)

    # 凡例
    action_patch = mpatches.Patch(color='blue', label='Action', alpha=0.7)
    bg_patch = mpatches.Patch(color='orange', label='Background Factor', alpha=0.7)
    ax.legend(handles=[action_patch, bg_patch], loc='upper right', fontsize=12)

    # x軸のラベルを間引く
    step = max(1, len(cluster_ids) // 20)
    ax.set_xticks(range(0, len(cluster_ids), step))
    ax.set_xticklabels([str(cluster_ids[i]) for i in range(0, len(cluster_ids), step)], rotation=45)

    plt.tight_layout()
    output_path1 = f'{output_prefix}_barchart.png'
    plt.savefig(output_path1, dpi=300, bbox_inches='tight')
    plt.close()
    print(f'[1] バーチャート作成完了: {output_path1}')

    # 図2: ヒートマップ（グリッド形式）
    # クラスタを10x(n/10)のグリッドに配置
    n_clusters = len(clusters_data)
    cols = 20
    rows = (n_clusters + cols - 1) // cols

    # グリッド用のデータ作成
    grid_data = np.zeros((rows, cols))
    grid_labels = [['' for _ in range(cols)] for _ in range(rows)]

    for idx, cluster in enumerate(clusters_data):
        row = idx // cols
        col = idx % cols
        grid_data[row, col] = cluster['text_count']
        grid_labels[row][col] = str(cluster['cluster_id'])

    fig, ax = plt.subplots(figsize=(20, max(8, rows * 0.5)))

    # カスタムカラーマップ（白→青のグラデーション）
    cmap = LinearSegmentedColormap.from_list('custom', ['#ffffff', '#4a90e2', '#1a5490'])

    im = ax.imshow(grid_data, cmap=cmap, aspect='auto', interpolation='nearest')

    # カラーバー
    cbar = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label('Text Count', fontsize=12)

    # グリッドとラベル
    ax.set_xticks(np.arange(cols))
    ax.set_yticks(np.arange(rows))
    ax.set_xticklabels([str(i) for i in range(cols)])
    ax.set_yticklabels([str(i) for i in range(rows)])

    # クラスタIDを各セルに表示
    for i in range(rows):
        for j in range(cols):
            if grid_labels[i][j]:
                text_color = 'white' if grid_data[i, j] > np.max(grid_data) * 0.5 else 'black'
                ax.text(j, i, grid_labels[i][j], ha='center', va='center',
                       fontsize=6, color=text_color, fontweight='bold')

    ax.set_title(f'{dataset_name} - Cluster Heatmap (Cluster ID with Text Count)',
                 fontsize=16, fontweight='bold', pad=20)
    ax.set_xlabel('Column Index', fontsize=12)
    ax.set_ylabel('Row Index', fontsize=12)

    plt.tight_layout()
    output_path2 = f'{output_prefix}_heatmap.png'
    plt.savefig(output_path2, dpi=300, bbox_inches='tight')
    plt.close()
    print(f'[2] ヒートマップ作成完了: {output_path2}')

    # 図3: テキスト数の分布ヒストグラム
    fig, ax = plt.subplots(figsize=(12, 6))

    ax.hist(text_counts, bins=30, color='steelblue', alpha=0.7, edgecolor='black')
    ax.axvline(np.mean(text_counts), color='red', linestyle='--', linewidth=2, label=f'Mean: {np.mean(text_counts):.2f}')
    ax.axvline(np.median(text_counts), color='green', linestyle='--', linewidth=2, label=f'Median: {np.median(text_counts):.1f}')

    ax.set_xlabel('Text Count per Cluster', fontsize=14)
    ax.set_ylabel('Frequency', fontsize=14)
    ax.set_title(f'{dataset_name} - Distribution of Text Counts', fontsize=16, fontweight='bold')
    ax.legend(fontsize=12)
    ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    output_path3 = f'{output_prefix}_histogram.png'
    plt.savefig(output_path3, dpi=300, bbox_inches='tight')
    plt.close()
    print(f'[3] ヒストグラム作成完了: {output_path3}')

    # 統計サマリー
    print(f'\n統計サマリー ({dataset_name}):')
    print(f'  総クラスタ数: {n_clusters}')
    print(f'  平均テキスト数: {np.mean(text_counts):.2f}')
    print(f'  標準偏差: {np.std(text_counts):.2f}')
    print(f'  中央値: {np.median(text_counts):.1f}')
    print(f'  最小値: {np.min(text_counts)}')
    print(f'  最大値: {np.max(text_counts)}')
    print()


# メイン処理
if __name__ == "__main__":
    base_path = '/Users/mana/Desktop/AudioInterview/data'

    print("\n" + "=" * 80)
    print("Cluster Visualization")
    print("=" * 80 + "\n")

    # Matsushita Sampleを可視化
    print("Matsushita Sample Dataset:")
    print("-" * 80)
    visualize_cluster_heatmap(
        f'{base_path}/cluster_quality_matsushita_sample.json',
        f'{base_path}/matsushita_sample_visualization',
        'Matsushita Sample'
    )

    # Uchidaを可視化
    print("\nUchida Dataset:")
    print("-" * 80)
    visualize_cluster_heatmap(
        f'{base_path}/cluster_quality_uchida.json',
        f'{base_path}/uchida_visualization',
        'Uchida'
    )

    print("\n" + "=" * 80)
    print("すべての可視化が完了しました！")
    print("=" * 80)
