import json

# Load the data
with open('/Users/mana/Desktop/AudioInterview/data/cluster_quality_uchida_0.35.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 1. Generate clusters_analysis.json (top and bottom by avg_similarity)
clusters_for_analysis = []
for cluster_id, cluster_info in data.items():
    clusters_for_analysis.append({
        'cluster_id': cluster_id,
        'concept_name': cluster_info['concept_name'],
        'text_count': cluster_info['text_count'],
        'average_similarity': cluster_info['average_similarity'],
        'std_similarity': cluster_info['std_similarity'],
        'min_similarity': cluster_info['min_similarity'],
        'max_similarity': cluster_info['max_similarity'],
        'texts': cluster_info['texts'],
        'similarities': cluster_info['similarities']
    })

# Sort by average similarity
clusters_for_analysis.sort(key=lambda x: x['average_similarity'], reverse=True)

# Create analysis file
analysis_output = {
    "dataset_info": {
        "total_clusters": len(data),
        "source_file": "cluster_quality_uchida_0.35.json"
    },
    "top_10_clusters": [],
    "bottom_10_clusters": []
}

# Top 10
for rank, cluster in enumerate(clusters_for_analysis[:10], start=1):
    analysis_output["top_10_clusters"].append({
        "rank": rank,
        "cluster_id": cluster['cluster_id'],
        "concept_name": cluster['concept_name'],
        "statistics": {
            "text_count": cluster['text_count'],
            "average_similarity": round(cluster['average_similarity'], 4),
            "std_similarity": round(cluster['std_similarity'], 4),
            "min_similarity": round(cluster['min_similarity'], 4),
            "max_similarity": round(cluster['max_similarity'], 4)
        },
        "texts": cluster['texts'],
        "similarities": [round(s, 4) for s in cluster['similarities']]
    })

# Bottom 10
for rank, cluster in enumerate(clusters_for_analysis[-10:], start=len(clusters_for_analysis)-9):
    analysis_output["bottom_10_clusters"].append({
        "rank": rank,
        "cluster_id": cluster['cluster_id'],
        "concept_name": cluster['concept_name'],
        "statistics": {
            "text_count": cluster['text_count'],
            "average_similarity": round(cluster['average_similarity'], 4),
            "std_similarity": round(cluster['std_similarity'], 4),
            "min_similarity": round(cluster['min_similarity'], 4),
            "max_similarity": round(cluster['max_similarity'], 4)
        },
        "texts": cluster['texts'],
        "similarities": [round(s, 4) for s in cluster['similarities']]
    })

with open('/Users/mana/Desktop/AudioInterview/data/uchida_0.35_clusters_analysis.json', 'w', encoding='utf-8') as f:
    json.dump(analysis_output, f, ensure_ascii=False, indent=2)

print(f"✓ Created uchida_0.35_clusters_analysis.json")
print(f"  Total clusters: {len(data)}")
print(f"  Top cluster avg similarity: {clusters_for_analysis[0]['average_similarity']:.4f}")
print(f"  Bottom cluster avg similarity: {clusters_for_analysis[-1]['average_similarity']:.4f}")

# 2. Generate clusters_by_count.json
clusters_by_count = sorted(clusters_for_analysis, key=lambda x: x['text_count'], reverse=True)
count_1_clusters = [c for c in clusters_for_analysis if c['text_count'] == 1]
count_1_clusters_sorted = sorted(count_1_clusters, key=lambda x: x['average_similarity'], reverse=True)

by_count_output = {
    "dataset_info": {
        "total_clusters": len(data),
        "source_file": "cluster_quality_uchida_0.35.json",
        "sorting_criteria": "text_count",
        "count_1_clusters_total": len(count_1_clusters)
    },
    "top_10_clusters_by_count": [],
    "all_count_1_clusters": []
}

# Top 10 by count
for rank, cluster in enumerate(clusters_by_count[:10], start=1):
    by_count_output["top_10_clusters_by_count"].append({
        "rank": rank,
        "cluster_id": cluster['cluster_id'],
        "concept_name": cluster['concept_name'],
        "statistics": {
            "text_count": cluster['text_count'],
            "average_similarity": round(cluster['average_similarity'], 4),
            "std_similarity": round(cluster['std_similarity'], 4),
            "min_similarity": round(cluster['min_similarity'], 4),
            "max_similarity": round(cluster['max_similarity'], 4)
        },
        "texts": cluster['texts'],
        "similarities": [round(s, 4) for s in cluster['similarities']]
    })

# All count-1 clusters sorted by similarity
for rank, cluster in enumerate(count_1_clusters_sorted, start=1):
    by_count_output["all_count_1_clusters"].append({
        "rank_by_similarity": rank,
        "cluster_id": cluster['cluster_id'],
        "concept_name": cluster['concept_name'],
        "statistics": {
            "text_count": cluster['text_count'],
            "average_similarity": round(cluster['average_similarity'], 4),
            "std_similarity": round(cluster['std_similarity'], 4),
            "min_similarity": round(cluster['min_similarity'], 4),
            "max_similarity": round(cluster['max_similarity'], 4)
        },
        "texts": cluster['texts'],
        "similarities": [round(s, 4) for s in cluster['similarities']]
    })

with open('/Users/mana/Desktop/AudioInterview/data/uchida_0.35_clusters_by_count.json', 'w', encoding='utf-8') as f:
    json.dump(by_count_output, f, ensure_ascii=False, indent=2)

print(f"\n✓ Created uchida_0.35_clusters_by_count.json")
print(f"  Count-1 clusters: {len(count_1_clusters)}")
print(f"  Max text count: {clusters_by_count[0]['text_count']}")

# 3. Generate individual_texts.json
all_texts = []
for cluster_id, cluster_info in data.items():
    for i, (text, similarity) in enumerate(zip(cluster_info['texts'], cluster_info['similarities'])):
        all_texts.append({
            'text': text,
            'similarity': similarity,
            'cluster_id': cluster_id,
            'concept_name': cluster_info['concept_name']
        })

all_texts_sorted = sorted(all_texts, key=lambda x: x['similarity'], reverse=True)

individual_output = {
    "dataset_info": {
        "total_texts": len(all_texts),
        "source_file": "cluster_quality_uchida_0.35.json"
    },
    "top_10_texts_by_similarity": [],
    "bottom_10_texts_by_similarity": []
}

# Top 10 texts
for rank, text_info in enumerate(all_texts_sorted[:10], start=1):
    individual_output["top_10_texts_by_similarity"].append({
        "rank": rank,
        "similarity": round(text_info['similarity'], 4),
        "text": text_info['text'],
        "cluster_info": {
            "cluster_id": text_info['cluster_id'],
            "concept_name": text_info['concept_name']
        }
    })

# Bottom 10 texts
for rank, text_info in enumerate(all_texts_sorted[-10:], start=len(all_texts_sorted)-9):
    individual_output["bottom_10_texts_by_similarity"].append({
        "rank": rank,
        "similarity": round(text_info['similarity'], 4),
        "text": text_info['text'],
        "cluster_info": {
            "cluster_id": text_info['cluster_id'],
            "concept_name": text_info['concept_name']
        }
    })

with open('/Users/mana/Desktop/AudioInterview/data/uchida_0.35_clusters_individual_texts.json', 'w', encoding='utf-8') as f:
    json.dump(individual_output, f, ensure_ascii=False, indent=2)

print(f"\n✓ Created uchida_0.35_clusters_individual_texts.json")
print(f"  Total individual texts: {len(all_texts)}")
print(f"  Highest similarity: {all_texts_sorted[0]['similarity']:.4f}")
print(f"  Lowest similarity: {all_texts_sorted[-1]['similarity']:.4f}")

# 4. Generate low_similarity_sample.json
threshold = 0.3
low_similarity_texts = [t for t in all_texts if t['similarity'] < threshold]
low_similarity_texts_sorted = sorted(low_similarity_texts, key=lambda x: x['similarity'])

sample_size = min(100, len(low_similarity_texts))
sampled_texts = low_similarity_texts_sorted[:sample_size]

low_sim_output = {
    "dataset_info": {
        "threshold": threshold,
        "total_low_similarity_texts": len(low_similarity_texts),
        "sample_size": sample_size,
        "source_file": "cluster_quality_uchida_0.35.json"
    },
    "sampled_low_similarity_texts": []
}

for sample_id, text_info in enumerate(sampled_texts, start=1):
    low_sim_output["sampled_low_similarity_texts"].append({
        "sample_id": sample_id,
        "similarity": round(text_info['similarity'], 4),
        "text": text_info['text'],
        "cluster_info": {
            "cluster_id": text_info['cluster_id'],
            "concept_name": text_info['concept_name']
        }
    })

with open('/Users/mana/Desktop/AudioInterview/data/uchida_0.35_clusters_low_similarity_sample.json', 'w', encoding='utf-8') as f:
    json.dump(low_sim_output, f, ensure_ascii=False, indent=2)

print(f"\n✓ Created uchida_0.35_clusters_low_similarity_sample.json")
print(f"  Threshold: {threshold}")
print(f"  Total low similarity texts: {len(low_similarity_texts)}")
print(f"  Sample size: {sample_size}")

print("\n" + "="*60)
print("All analysis files created successfully!")
print("="*60)
