#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import os
import uuid

# Define the input files and their position/name mappings with UUIDs
files = [
    {
        'filename': '新潟_インタビューデータ.xlsx - 係長_佐藤剛さん.csv',
        'position': '係長',
        'name': '佐藤剛さん',
        'user_id': str(uuid.uuid4())
    },
    {
        'filename': '新潟_インタビューデータ.xlsx - 係長_斎藤さん.csv',
        'position': '係長',
        'name': '斎藤さん',
        'user_id': str(uuid.uuid4())
    },
    {
        'filename': '新潟_インタビューデータ.xlsx - 係長_小野さん.csv',
        'position': '係長',
        'name': '小野さん',
        'user_id': str(uuid.uuid4())
    },
    {
        'filename': '新潟_インタビューデータ.xlsx - 係長_富樫さん.csv',
        'position': '係長',
        'name': '富樫さん',
        'user_id': str(uuid.uuid4())
    },
    {
        'filename': '新潟_インタビューデータ.xlsx - 副長_佐藤さん.csv',
        'position': '副長',
        'name': '佐藤さん',
        'user_id': str(uuid.uuid4())
    }
]

# Existing users
existing_users = [
    {'user_id': 'dbf9b7c4-e0cc-4e32-baf2-aece42e8725c', 'name': '佐藤健太さん', 'position': '係'},
    {'user_id': '81f9a6e5-21ec-43a1-bffe-88181fa8f221', 'name': '高橋さん', 'position': '係'},
    {'user_id': '08b25299-c3b5-4124-9055-6bff3b64ea77', 'name': '青井さん', 'position': '係'},
    {'user_id': 'b86e613e-bd1d-4d96-b29e-9b6ca351f39e', 'name': '南さん', 'position': '薬長'},
    {'user_id': '5df4c4d9-fcc8-4604-a9f9-9da170bf416c', 'name': '江端さん', 'position': '班長'},
    {'user_id': '372c0bca-3825-459e-bc4e-6b9a52980247', 'name': '馬場さん', 'position': '班長'},
    {'user_id': 'e0a0ed9b-5c80-4186-a856-98fdbd04e81b', 'name': '斎藤さん', 'position': '班長'},
    {'user_id': 'c4ae3c06-34f2-4d64-9bf0-cdd5847b5663', 'name': '高木さん', 'position': '班長'},
    {'user_id': '57285317-7957-4c47-bed5-a7489f0d9cd4', 'name': '細貝さん', 'position': '班長'},
    {'user_id': 'a0b21e98-972b-486e-9e19-9c1ea2c79035', 'name': '野口さん', 'position': '班長'}
]

# Output file
output_file = 'transformed_interviews_with_id.csv'

# Process each file
output_rows = []

for file_info in files:
    filepath = os.path.join('/Users/mana/Desktop/AudioInterview/data', file_info['filename'])
    position = file_info['position']
    name = file_info['name']
    user_id = file_info['user_id']

    print(f"Processing: {file_info['filename']}")
    print(f"  User ID: {user_id}")

    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)

        # Skip header row
        next(reader)

        # Extract first column (文章) from each row
        for row in reader:
            if row and len(row) > 0 and row[0]:
                # Remove the arrow prefix if present
                text = row[0].replace('→', '').strip()

                # Only add non-empty text
                if text:
                    output_rows.append([user_id, 'Japan', name, position, text])

# Write output
output_path = os.path.join('/Users/mana/Desktop/AudioInterview/data', output_file)
with open(output_path, 'w', encoding='utf-8', newline='') as f:
    writer = csv.writer(f)
    writer.writerows(output_rows)

print(f"\nTransformation complete!")
print(f"Total rows: {len(output_rows)}")
print(f"Output file: {output_path}")

# Print user ID mapping
print("\n=== New User ID Mapping ===")
for file_info in files:
    print(f"{file_info['user_id']},Japan,{file_info['name']},{file_info['position']}")
