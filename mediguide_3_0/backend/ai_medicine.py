import dataset_search

def recommend_medicine(symptoms, topn=1):
    """Return best match from local dataset using TF-IDF similarity.

    This is a conservative lookup helper: it returns a dictionary with disease,
    medicine and advice for the top matched record, or a Not Found fallback.
    """
    if not symptoms:
        return {
            "disease": "Not Found",
            "medicine": "Consult a doctor",
            "advice": "No symptoms provided"
        }

    results = dataset_search.find_similar(symptoms, topn=topn)
    if not results:
        return {
            "disease": "Not Found",
            "medicine": "Consult a doctor",
            "advice": "No matching disease found for given symptoms"
        }

    best = results[0]
    return {
        "disease": best.get('disease','Not Found'),
        "medicine": best.get('medicine','Consult a doctor'),
        "advice": best.get('advice','No advice'),
        "score": best.get('score', 0.0)
    }
