import threading
import os
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

_lock = threading.Lock()
_model = None
_df = None

def _build_index(csv_path=None):
    global _model, _df
    with _lock:
        if _model is not None and _df is not None:
            return
        # Prefer an expanded dataset if present
        if csv_path is None:
            base_dir = os.path.dirname(__file__)
            expanded = os.path.join(base_dir, 'medicine_dataset_expanded.csv')
            default = os.path.join(base_dir, 'medicine_dataset.csv')
            csv_path = expanded if os.path.exists(expanded) else default
        if not os.path.exists(csv_path):
            _df = None
            _model = None
            return
        _df = pd.read_csv(csv_path, encoding='utf-8')
        # create a combined text field
        _df['combined'] = (_df.get('symptoms','').astype(str) + ' | ' + _df.get('disease','').astype(str) + ' | ' + _df.get('advice','').astype(str)).fillna('')
        texts = _df['combined'].fillna('').tolist()
        _model = TfidfVectorizer(stop_words='english', max_features=20000)
        _model.fit(texts)

def find_similar(query, topn=3, csv_path=None):
    """Return topn similar records from the local dataset with cosine scores."""
    global _model, _df
    if _model is None or _df is None:
        _build_index(csv_path)
    if _model is None or _df is None:
        return []
    qv = _model.transform([query])
    matrix = _model.transform(_df['combined'].fillna('').tolist())
    sims = cosine_similarity(qv, matrix)[0]
    top_idx = sims.argsort()[::-1][:topn]
    results = []
    for idx in top_idx:
        score = float(sims[idx])
        row = _df.iloc[idx]
        results.append({
            'disease': str(row.get('disease','')),
            'medicine': str(row.get('medicine','')),
            'advice': str(row.get('advice','')),
            'symptoms': str(row.get('symptoms','')),
            'score': score
        })
    return results
