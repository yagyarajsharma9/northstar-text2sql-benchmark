"""
NorthStar Petroleum - Text Document Ingestion
==============================================
Reads .txt files from /documents, extracts content, builds chunks for
RAG, and writes everything to:
  - document_extracts        (one row per file)
  - document_chunks          (chunked text)
  - document_chunks_fts      (FTS5 keyword index)
  - document_references      (catalog entry)
  - external_links           (back-pointer to file path)

Run AFTER seed_data.py:
    python ingest_documents.py
"""

from __future__ import annotations
import os
import re
import sys
import sqlite3
import datetime as dt
from pathlib import Path

HERE = Path(__file__).parent
DB_PATH = HERE / "oilgas.db"
DOC_DIR = HERE.parent / "documents"

# --- Chunking config ---
CHUNK_SIZE = 800        # characters (~200 tokens)
CHUNK_OVERLAP = 120     # chars of overlap between chunks
TOKEN_PER_CHAR = 0.25   # rough estimator


# Map filename keywords -> document category and related entity hints
CATEGORY_RULES = [
    (r"hse|safety|incident",          "Policy"),
    (r"sop|procedure|operation",      "SOP"),
    (r"contract|msa|agreement",       "Contract"),
    (r"checklist",                    "Checklist"),
    (r"report|summary",               "Report"),
    (r"manual",                       "Manual"),
    (r"memo",                         "Memo"),
    (r"permit",                       "Permit"),
    (r"plan",                         "Plan"),
    (r"policy",                       "Policy"),
]

ENTITY_RULES = [
    (r"well|drilling",        "well"),
    (r"pipeline",             "pipeline"),
    (r"contract|crude|sale",  "contract"),
    (r"incident|hse",         "incident"),
    (r"production",           "daily_production"),
    (r"vendor",               "vendor"),
]

STOPWORDS = {
    "the","of","and","to","in","a","is","for","on","by","with","this","that","be",
    "as","at","or","an","are","from","it","not","shall","may","each","any","all",
    "if","into","such","other","than","may","must","also","its","their","which","s",
}


def categorize(filename: str) -> str:
    f = filename.lower()
    for pat, cat in CATEGORY_RULES:
        if re.search(pat, f):
            return cat
    return "Other"


def hint_entity(filename: str) -> str | None:
    f = filename.lower()
    for pat, ent in ENTITY_RULES:
        if re.search(pat, f):
            return ent
    return None


def make_chunks(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    """Sliding window over character text, broken on whitespace where possible."""
    text = text.strip()
    if not text:
        return []
    chunks = []
    i = 0
    n = len(text)
    while i < n:
        end = min(i + size, n)
        # Try to break on a sentence/paragraph boundary near the end.
        if end < n:
            for sep in ("\n\n", "\n", ". ", " "):
                cut = text.rfind(sep, i + size // 2, end)
                if cut != -1:
                    end = cut + len(sep)
                    break
        chunks.append((i, end, text[i:end].strip()))
        if end >= n:
            break
        i = max(end - overlap, i + 1)
    return chunks


def build_summary(text: str, max_sentences: int = 4) -> str:
    """Pick first non-trivial paragraph as summary."""
    paras = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 80]
    if not paras:
        return text[:400]
    blob = paras[0]
    sentences = re.split(r"(?<=[.!?])\s+", blob)
    return " ".join(sentences[:max_sentences])[:500]


def extract_keywords(text: str, top_n: int = 12) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", text.lower())
    freq = {}
    for w in words:
        if w in STOPWORDS:
            continue
        freq[w] = freq.get(w, 0) + 1
    ranked = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return ",".join(w for w, _ in ranked)


def ingest():
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} does not exist. Run seed_data.py first.", file=sys.stderr)
        sys.exit(1)
    if not DOC_DIR.exists():
        print(f"ERROR: documents folder not found at {DOC_DIR}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.cursor()

    # Pick a default ingestor user (admin) and a HSE-ish user fallback.
    admin_user = cur.execute(
        "SELECT user_id FROM users WHERE username='admin.root'"
    ).fetchone()
    ingestor_id = admin_user[0] if admin_user else None

    files = sorted([p for p in DOC_DIR.glob("*.txt") if p.is_file()])
    if not files:
        print("No .txt files found in documents/, nothing to ingest.")
        return

    print(f"Ingesting {len(files)} text document(s) from {DOC_DIR}\n")

    total_chunks = 0
    for fp in files:
        text = fp.read_text(encoding="utf-8", errors="replace")
        char_count = len(text)
        word_count = len(text.split())
        category = categorize(fp.name)
        entity_hint = hint_entity(fp.name)
        keywords = extract_keywords(text)
        summary = build_summary(text)

        # Skip if already ingested (idempotent)
        existing = cur.execute(
            "SELECT extract_id FROM document_extracts WHERE source_path=?", (str(fp),)
        ).fetchone()
        if existing:
            print(f"  - SKIP (already ingested): {fp.name}")
            continue

        # Create / find the document_references catalog row.
        ref = cur.execute(
            """SELECT document_id FROM document_references
               WHERE storage_uri=? LIMIT 1""", (f"file://{fp}",)
        ).fetchone()
        if ref:
            doc_ref_id = ref[0]
        else:
            cur.execute(
                """INSERT INTO document_references(entity_type,entity_id,document_name,document_type,
                    storage_uri,file_size_bytes,mime_type,uploaded_by_user_id,uploaded_at,is_confidential)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (entity_hint or "policy", 0, fp.name, category,
                 f"file://{fp}", char_count, "text/plain",
                 ingestor_id, dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                 0)
            )
            doc_ref_id = cur.lastrowid

        cur.execute(
            """INSERT INTO document_extracts(document_id,source_path,file_name,document_category,
                related_entity_type,related_entity_id,char_count,word_count,language,
                extracted_text,summary,keywords,extraction_method,extracted_by_user_id,is_indexed)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (doc_ref_id, str(fp), fp.name, category,
             entity_hint, None, char_count, word_count, "en",
             text, summary, keywords, "plaintext", ingestor_id, 0)
        )
        extract_id = cur.lastrowid

        # External link back to original file
        cur.execute(
            """INSERT INTO external_links(entity_type,entity_id,link_type,system_name,url,external_id,
                last_synced_at,is_active) VALUES(?,?,?,?,?,?,?,?)""",
            ("document_extract", extract_id, "FileSystem", "Local Documents Drive",
             f"file://{fp}", fp.stem,
             dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), 1)
        )

        # Chunk and insert
        chunks = make_chunks(text)
        for idx, (start, end, ctext) in enumerate(chunks):
            cur.execute(
                """INSERT INTO document_chunks(extract_id,chunk_index,chunk_text,char_start,char_end,
                    token_estimate,embedding_model,embedding_blob)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (extract_id, idx, ctext, start, end,
                 int(len(ctext) * TOKEN_PER_CHAR), None, None)
            )

        # Mark as indexed
        cur.execute("UPDATE document_extracts SET is_indexed=1 WHERE extract_id=?", (extract_id,))
        total_chunks += len(chunks)
        print(f"  + {fp.name:<45s} cat={category:<10s} chunks={len(chunks):>3d} words={word_count:>5d}")

    # Rebuild FTS5 index from base table
    print("\nRebuilding FTS5 index over document_chunks ...")
    cur.execute("INSERT INTO document_chunks_fts(document_chunks_fts) VALUES('rebuild')")

    conn.commit()

    # Summary
    n_extracts = cur.execute("SELECT COUNT(*) FROM document_extracts").fetchone()[0]
    n_chunks = cur.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
    n_fts = cur.execute("SELECT COUNT(*) FROM document_chunks_fts").fetchone()[0]
    print(f"\nDONE. extracts={n_extracts}  chunks={n_chunks}  fts_rows={n_fts}")
    conn.close()


if __name__ == "__main__":
    ingest()
