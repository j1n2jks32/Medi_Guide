"""
Simple dataset expansion script to create a larger CSV from an existing small `medicine_dataset.csv`.
This script performs light augmentation (word shuffles, short synonyms insertion) to reach a target row count.

Usage: python generate_dataset.py --source medicine_dataset.csv --output medicine_dataset_expanded.csv --target 100000

Note: This is a helper for synthetic data generation for testing and improving retrieval. Do not treat
the generated dataset as validated clinical data.
"""
import argparse
import csv
import random
import os

SYNONYMS = {
    'pain': ['pain', 'ache', 'soreness', 'discomfort'],
    'fever': ['fever', 'high temperature', 'pyrexia'],
    'cough': ['cough', 'coughing', 'hack'],
    'headache': ['headache', 'head pain', 'migraine-like pain']
}

def augment_text(text):
    words = text.split()
    # randomly replace some words with synonyms
    for i, w in enumerate(words):
        key = w.lower().strip('.,')
        if key in SYNONYMS and random.random() < 0.4:
            words[i] = random.choice(SYNONYMS[key])
    # small shuffle
    if len(words) > 4 and random.random() < 0.2:
        i = random.randint(0, len(words)-2)
        words[i], words[i+1] = words[i+1], words[i]
    return ' '.join(words)

def expand_csv(source, output, target):
    rows = []
    with open(source, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    if not rows:
        raise SystemExit('Source file empty')

    fieldnames = list(rows[0].keys())
    out_count = 0
    with open(output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        while out_count < target:
            src = random.choice(rows)
            new = dict(src)
            # augment symptoms text
            new_sym = augment_text(new.get('symptoms',''))
            # add small variant to advice line
            new_adv = augment_text(new.get('advice',''))
            new['symptoms'] = new_sym
            new['advice'] = new_adv
            writer.writerow(new)
            out_count += 1

    print(f'Wrote {out_count} rows to {output}')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', default='medicine_dataset.csv')
    p.add_argument('--output', default='medicine_dataset_expanded.csv')
    p.add_argument('--target', type=int, default=100000)
    args = p.parse_args()
    src = args.source
    if not os.path.exists(src):
        src = os.path.join(os.path.dirname(__file__), src)
    out = args.output
    if not os.path.isabs(out):
        out = os.path.join(os.path.dirname(__file__), out)
    expand_csv(src, out, args.target)


if __name__ == '__main__':
    main()
