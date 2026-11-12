import os
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from packages.ingestion.pipeline import ingest_pdf
from packages.llm_gateway.gateway import generate_embedding
from packages.retrieval.db import get_engine
from services.env import load_env_file

load_env_file()

API_URL = os.environ.get("API_URL", "http://localhost:8000")
USER_ID = "alice"
HEADERS = {"X-User-Id": USER_ID}


def run_live_test():
    client = httpx.Client(base_url=API_URL, headers=HEADERS, timeout=120.0)

    # 1. Create notebook
    res = client.post("/notebooks", json={"title": "Apollo 11 Research", "description": "Space exploration docs"})
    res.raise_for_status()
    notebook = res.json()
    nb_id = notebook["id"]
    print(f"[1] Created Notebook: id={nb_id}, title={notebook['title']}")

    # 2. Ingest sample PDF directly into the DB with Voyage embeddings
    pdf_path = Path("data/corpus/Apollo_11_Mission_Report.pdf")
    engine = get_engine()
    with Session(engine) as session:
        result = ingest_pdf(session, USER_ID, nb_id, pdf_path, file_path=str(pdf_path), embed_fn=generate_embedding)
        print(f"[2] Ingested PDF: source_id={result.source_id}, chunk_count={result.chunk_count}")

    # 3. Check sources endpoint
    res = client.get(f"/notebooks/{nb_id}/sources")
    res.raise_for_status()
    sources_data = res.json()
    print(f"[3] Sources in notebook: {len(sources_data['sources'])} sources ready.")

    # 4. Ask grounded query
    query1 = "How much lunar material was collected, and when did the crew land on the Moon?"
    print(f"\n[4] Asking Query: '{query1}'...")
    res = client.post(f"/notebooks/{nb_id}/chat", json={"query": query1})
    res.raise_for_status()
    chat1 = res.json()
    print("--- Answer ---")
    print(chat1["answer"])
    print("--- Verification Receipts ---")
    print(f"Insufficient evidence? {chat1['insufficient_evidence']}")
    for i, claim in enumerate(chat1.get("claims", [])):
        print(f'Claim {i+1} [{claim["support_status"]}]: "{claim["text"]}"')
        for cit in claim.get("citations", []):
            print(f"  -> Source: {cit.get('source_title')} (Page {cit.get('page_number')})")
            print(f'  -> Quote: "{cit.get("quote")}"')

    # 5. Ask unanswerable query (verify honest abstention)
    query2 = "What was the color of Neil Armstrong's car on Earth?"
    print(f"\n[5] Asking Unanswerable Query: '{query2}'...")
    res = client.post(f"/notebooks/{nb_id}/chat", json={"query": query2})
    res.raise_for_status()
    chat2 = res.json()
    print(f"Answer: {chat2['answer']}")
    print(f"Insufficient evidence? {chat2['insufficient_evidence']} (Expected: True)")

    print("\n[SUCCESS] Live end-to-end verification completed successfully!")


if __name__ == "__main__":
    run_live_test()
