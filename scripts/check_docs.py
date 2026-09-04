import requests
r = requests.get("http://127.0.0.1:8000/api/documents?limit=15")
docs = r.json()["documents"]
print(f"{len(docs)} indexed documents:")
for d in docs:
    print(f"  {d['extract_id']:>3}  {d['file_name'][:45]:<45s}  "
          f"cat={d['document_category']:<10s} chunks={d['chunk_count']}  "
          f"words={d['word_count']}")
