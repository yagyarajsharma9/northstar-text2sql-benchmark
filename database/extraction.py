"""
Reusable text-document extraction + DB indexing.

Pulled out of ingest_documents.py so both the CLI batch ingest and the
web upload endpoint can share the exact same chunking / catalog / FTS5
logic.

Public entrypoint::

    extract_and_store(text, file_name, source_path=None, conn=None,
                      uploaded_by_user_id=None)
        -> dict   # {extract_id, chunks, summary, ...}

The caller can pass an existing sqlite3.Connection (transactional) or
omit it to open the default oilgas.db.
"""
from __future__ import annotations
import re
import sqlite3
import datetime as dt
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent / "oilgas.db"

# ----- Tunables (mirror ingest_documents.py defaults) -----
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
TOKEN_PER_CHAR = 0.25

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
    text = text.strip()
    if not text:
        return []
    chunks = []
    i = 0
    n = len(text)
    while i < n:
        end = min(i + size, n)
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
    paras = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 80]
    if not paras:
        return text[:400]
    blob = paras[0]
    sentences = re.split(r"(?<=[.!?])\s+", blob)
    return " ".join(sentences[:max_sentences])[:500]


def extract_keywords(text: str, top_n: int = 12) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", text.lower())
    freq: dict[str, int] = {}
    for w in words:
        if w in STOPWORDS:
            continue
        freq[w] = freq.get(w, 0) + 1
    ranked = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return ",".join(w for w, _ in ranked)


def _now_iso() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _resolve_user(conn: sqlite3.Connection, username: str = "admin.root") -> int | None:
    row = conn.execute("SELECT user_id FROM users WHERE username=?", (username,)).fetchone()
    return row[0] if row else None


def extract_and_store(
    text: str,
    file_name: str,
    source_path: str | None = None,
    conn: sqlite3.Connection | None = None,
    uploaded_by_user_id: int | None = None,
    document_category: str | None = None,
) -> dict[str, Any]:
    """
    Index a single text document end-to-end.

    Returns:
        {extract_id, document_id, file_name, document_category,
         related_entity_type, char_count, word_count, chunk_count,
         summary, keywords, source_path, fts_rebuilt}
    """
    own_conn = conn is None
    if own_conn:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA foreign_keys=ON")

    char_count = len(text)
    word_count = len(text.split())
    category = document_category or categorize(file_name)
    entity_hint = hint_entity(file_name)
    keywords = extract_keywords(text)
    summary = build_summary(text)
    src = source_path or f"upload://{file_name}"

    if uploaded_by_user_id is None:
        uploaded_by_user_id = _resolve_user(conn)

    # Idempotent : if same source_path was already indexed, return it.
    cur = conn.cursor()
    existing = cur.execute(
        "SELECT extract_id, document_id FROM document_extracts WHERE source_path=?",
        (src,),
    ).fetchone()
    if existing:
        extract_id, doc_ref_id = existing
        chunk_count = cur.execute(
            "SELECT COUNT(*) FROM document_chunks WHERE extract_id=?", (extract_id,)
        ).fetchone()[0]
        if own_conn:
            conn.close()
        return {
            "extract_id": extract_id, "document_id": doc_ref_id,
            "file_name": file_name, "document_category": category,
            "related_entity_type": entity_hint, "char_count": char_count,
            "word_count": word_count, "chunk_count": chunk_count,
            "summary": summary, "keywords": keywords,
            "source_path": src, "fts_rebuilt": False, "duplicate": True,
        }

    # 1. document_references catalog row
    cur.execute(
        """INSERT INTO document_references(entity_type,entity_id,document_name,document_type,
            storage_uri,file_size_bytes,mime_type,uploaded_by_user_id,uploaded_at,is_confidential)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (entity_hint or "upload", 0, file_name, category,
         src, char_count, "text/plain",
         uploaded_by_user_id, _now_iso(), 0)
    )
    doc_ref_id = cur.lastrowid

    # 2. document_extracts
    cur.execute(
        """INSERT INTO document_extracts(document_id,source_path,file_name,document_category,
            related_entity_type,related_entity_id,char_count,word_count,language,
            extracted_text,summary,keywords,extraction_method,extracted_by_user_id,is_indexed)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (doc_ref_id, src, file_name, category,
         entity_hint, None, char_count, word_count, "en",
         text, summary, keywords, "plaintext", uploaded_by_user_id, 0)
    )
    extract_id = cur.lastrowid

    # 3. external_links back-pointer
    cur.execute(
        """INSERT INTO external_links(entity_type,entity_id,link_type,system_name,url,external_id,
            last_synced_at,is_active) VALUES(?,?,?,?,?,?,?,?)""",
        ("document_extract", extract_id, "Upload", "Web Upload",
         src, Path(file_name).stem, _now_iso(), 1)
    )

    # 4. chunks
    chunks = make_chunks(text)
    for idx, (start, end, ctext) in enumerate(chunks):
        cur.execute(
            """INSERT INTO document_chunks(extract_id,chunk_index,chunk_text,char_start,char_end,
                token_estimate,embedding_model,embedding_blob)
               VALUES(?,?,?,?,?,?,?,?)""",
            (extract_id, idx, ctext, start, end,
             int(len(ctext) * TOKEN_PER_CHAR), None, None)
        )

    # 5. mark indexed + rebuild FTS5 (cheap on this size)
    cur.execute("UPDATE document_extracts SET is_indexed=1 WHERE extract_id=?", (extract_id,))
    cur.execute("INSERT INTO document_chunks_fts(document_chunks_fts) VALUES('rebuild')")

    conn.commit()
    if own_conn:
        conn.close()

    return {
        "extract_id": extract_id, "document_id": doc_ref_id,
        "file_name": file_name, "document_category": category,
        "related_entity_type": entity_hint, "char_count": char_count,
        "word_count": word_count, "chunk_count": len(chunks),
        "summary": summary, "keywords": keywords,
        "source_path": src, "fts_rebuilt": True, "duplicate": False,
    }


def list_uploaded(conn: sqlite3.Connection | None = None, limit: int = 50) -> list[dict]:
    own = conn is None
    if own:
        conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT extract_id, file_name, document_category, word_count, char_count,
                  summary, keywords, extracted_at,
                  (SELECT COUNT(*) FROM document_chunks dc WHERE dc.extract_id=de.extract_id) AS chunk_count
           FROM document_extracts de
           ORDER BY extracted_at DESC
           LIMIT ?""", (limit,)
    ).fetchall()
    out = [dict(r) for r in rows]
    if own:
        conn.close()
    return out
