import requests, json
body = {
    "complaint": "leg pain after running",
    "answers": [
        {"question": "Where exactly is the pain","answer": "knee"},
        {"question": "How did it start","answer": "injury"},
        {"question": "Any swelling","answer": "yes"},
        {"question": "Rate pain","answer": "6"}
    ]
}
resp = requests.post('http://127.0.0.1:5000/chatbot-assistant', json=body)
print(resp.status_code)
print(json.dumps(resp.json(), indent=2))
