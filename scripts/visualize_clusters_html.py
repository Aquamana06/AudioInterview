#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json

def create_html_visualization(json_filepath, output_html_path, dataset_name):
    """
    HTMLとJavaScriptでクラスタのヒートマップを作成
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
                    'concept_name': cluster_info.get('concept_name', ''),
                    'avg_similarity': cluster_info.get('average_similarity', 0)
                })

    # クラスタIDでソート
    clusters_data.sort(key=lambda x: x['cluster_id'])

    # 統計計算
    text_counts = [c['text_count'] for c in clusters_data]
    max_count = max(text_counts)
    min_count = min(text_counts)
    avg_count = sum(text_counts) / len(text_counts)

    # HTMLテンプレート
    html_template = f"""
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{dataset_name} - Cluster Visualization</title>
    <style>
        body {{
            font-family: 'Arial', 'Helvetica', sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background-color: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            text-align: center;
            margin-bottom: 10px;
        }}
        .stats {{
            background-color: #f8f9fa;
            padding: 20px;
            border-radius: 5px;
            margin-bottom: 30px;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }}
        .stat-item {{
            background-color: white;
            padding: 15px;
            border-radius: 5px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        .stat-label {{
            font-size: 12px;
            color: #666;
            margin-bottom: 5px;
        }}
        .stat-value {{
            font-size: 24px;
            font-weight: bold;
            color: #007bff;
        }}
        .heatmap {{
            display: grid;
            grid-template-columns: repeat(20, 1fr);
            gap: 2px;
            margin-bottom: 30px;
        }}
        .cluster-cell {{
            aspect-ratio: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            border-radius: 3px;
            cursor: pointer;
            transition: transform 0.2s;
            font-size: 10px;
            position: relative;
        }}
        .cluster-cell:hover {{
            transform: scale(1.1);
            z-index: 10;
            box-shadow: 0 4px 8px rgba(0,0,0,0.3);
        }}
        .cluster-id {{
            font-weight: bold;
            font-size: 9px;
        }}
        .cluster-count {{
            font-size: 8px;
        }}
        .tooltip {{
            display: none;
            position: absolute;
            background-color: rgba(0,0,0,0.9);
            color: white;
            padding: 10px;
            border-radius: 5px;
            z-index: 1000;
            max-width: 300px;
            font-size: 12px;
            pointer-events: none;
        }}
        .legend {{
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 20px 0;
            gap: 20px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .color-box {{
            width: 30px;
            height: 20px;
            border-radius: 3px;
            border: 1px solid #ccc;
        }}
        .bar-chart {{
            margin: 30px 0;
        }}
        .bar {{
            height: 25px;
            margin: 2px 0;
            border-radius: 3px;
            display: flex;
            align-items: center;
            padding-left: 5px;
            font-size: 11px;
            color: white;
            transition: all 0.2s;
        }}
        .bar:hover {{
            opacity: 0.8;
            transform: translateX(5px);
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{dataset_name} - Cluster Visualization</h1>

        <div class="stats">
            <div class="stat-item">
                <div class="stat-label">Total Clusters</div>
                <div class="stat-value">{len(clusters_data)}</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Average Text Count</div>
                <div class="stat-value">{avg_count:.2f}</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Max Text Count</div>
                <div class="stat-value">{max_count}</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Min Text Count</div>
                <div class="stat-value">{min_count}</div>
            </div>
        </div>

        <h2 style="margin-top: 40px; color: #333;">Cluster Heatmap</h2>
        <p style="color: #666; font-size: 14px;">各セルはクラスタを表し、色の濃さはテキスト数を示します。クラスタにマウスオーバーで詳細情報を表示。</p>

        <div class="legend">
            <div class="legend-item">
                <div class="color-box" style="background: linear-gradient(to right, #e3f2fd, #1976d2);"></div>
                <span>Text Count: Low → High</span>
            </div>
            <div class="legend-item">
                <div class="color-box" style="background-color: #42a5f5; border: 2px solid #1976d2;"></div>
                <span>Action</span>
            </div>
            <div class="legend-item">
                <div class="color-box" style="background-color: #ffa726; border: 2px solid #f57c00;"></div>
                <span>Background Factor</span>
            </div>
        </div>

        <div class="heatmap" id="heatmap"></div>
        <div class="tooltip" id="tooltip"></div>

        <h2 style="margin-top: 40px; color: #333;">Top 20 Clusters by Text Count</h2>
        <div class="bar-chart" id="barChart"></div>
    </div>

    <script>
        const clustersData = {json.dumps(clusters_data, ensure_ascii=False)};
        const maxCount = {max_count};

        // ヒートマップ作成
        const heatmap = document.getElementById('heatmap');
        const tooltip = document.getElementById('tooltip');

        clustersData.forEach(cluster => {{
            const cell = document.createElement('div');
            cell.className = 'cluster-cell';

            // 色の計算
            const intensity = cluster.text_count / maxCount;
            const baseColor = cluster.category === 'action' ?
                {{r: 66, g: 165, b: 245}} : // blue
                {{r: 255, g: 167, b: 38}};  // orange

            const r = Math.round(255 - (255 - baseColor.r) * intensity);
            const g = Math.round(255 - (255 - baseColor.g) * intensity);
            const b = Math.round(255 - (255 - baseColor.b) * intensity);

            cell.style.backgroundColor = `rgb(${{r}}, ${{g}}, ${{b}})`;

            // 境界線の色
            cell.style.border = cluster.category === 'action' ?
                '1px solid #1976d2' : '1px solid #f57c00';

            // テキスト色
            cell.style.color = intensity > 0.5 ? 'white' : '#333';

            cell.innerHTML = `
                <div class="cluster-id">${{cluster.cluster_id}}</div>
                <div class="cluster-count">${{cluster.text_count}}</div>
            `;

            // ツールチップ
            cell.addEventListener('mouseenter', (e) => {{
                tooltip.style.display = 'block';
                tooltip.innerHTML = `
                    <strong>Cluster ID:</strong> ${{cluster.cluster_id}}<br>
                    <strong>Category:</strong> ${{cluster.category}}<br>
                    <strong>Concept:</strong> ${{cluster.concept_name}}<br>
                    <strong>Text Count:</strong> ${{cluster.text_count}}<br>
                    <strong>Avg Similarity:</strong> ${{cluster.avg_similarity.toFixed(4)}}
                `;
            }});

            cell.addEventListener('mousemove', (e) => {{
                tooltip.style.left = e.pageX + 10 + 'px';
                tooltip.style.top = e.pageY + 10 + 'px';
            }});

            cell.addEventListener('mouseleave', () => {{
                tooltip.style.display = 'none';
            }});

            heatmap.appendChild(cell);
        }});

        // バーチャート作成（Top 20）
        const barChart = document.getElementById('barChart');
        const sortedClusters = [...clustersData].sort((a, b) => b.text_count - a.text_count).slice(0, 20);

        sortedClusters.forEach(cluster => {{
            const bar = document.createElement('div');
            bar.className = 'bar';
            const width = (cluster.text_count / maxCount) * 100;
            bar.style.width = width + '%';
            bar.style.backgroundColor = cluster.category === 'action' ? '#42a5f5' : '#ffa726';
            bar.innerHTML = `ID ${{cluster.cluster_id}}: ${{cluster.text_count}} texts - ${{cluster.concept_name.substring(0, 40)}}`;
            barChart.appendChild(bar);
        }});
    </script>
</body>
</html>
"""

    # HTMLファイルに書き込み
    with open(output_html_path, 'w', encoding='utf-8') as f:
        f.write(html_template)

    print(f'HTMLビジュアライゼーション作成完了: {output_html_path}')


# メイン処理
if __name__ == "__main__":
    base_path = '/Users/mana/Desktop/AudioInterview/data'

    print("\n" + "=" * 80)
    print("HTML Cluster Visualization")
    print("=" * 80 + "\n")

    # Matsushita Sampleを可視化
    print("Matsushita Sample Dataset:")
    create_html_visualization(
        f'{base_path}/cluster_quality_matsushita_sample.json',
        f'{base_path}/matsushita_sample_visualization.html',
        'Matsushita Sample'
    )

    # Uchidaを可視化
    print("\nUchida Dataset:")
    create_html_visualization(
        f'{base_path}/cluster_quality_uchida.json',
        f'{base_path}/uchida_visualization.html',
        'Uchida'
    )

    print("\n" + "=" * 80)
    print("完了！ブラウザでHTMLファイルを開いてください。")
    print("=" * 80)
