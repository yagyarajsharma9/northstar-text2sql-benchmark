"""
FastAPI backend for the NorthStar chat assistant.

Endpoints
---------
GET  /                 - serve chat UI (frontend/index.html)
GET  /static/*         - assets (app.js, style.css)
GET  /healthz          - liveness
GET  /api/schema       - return the catalog (for the UI sidebar)
POST /api/chat         - one-shot chat (returns full PipelineResult JSON)
GET  /api/chat/stream  - SSE stream of trace events + final result
GET  /api/sample-questions - example queries to seed the UI

Run:
    uvicorn winning_architecture.server:app --reload --port 8000
or
    python winning_architecture/server.py
"""
from __future__ import annotations
import os
import re
import json
import asyncio
import logging
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from winning_architecture import engine, schema_catalog
from winning_architecture.engine import TraceEvent

# Reusable extraction module from the database/ package
import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent.parent))
from database import extraction as doc_extraction  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
log = logging.getLogger("server")

HERE = Path(__file__).parent
FRONTEND = HERE / "frontend"

app = FastAPI(title="NorthStar Chat Assistant", version="1.0.0")

if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    idx = FRONTEND / "index.html"
    return FileResponse(str(idx)) if idx.exists() else HTMLResponse("<h1>frontend missing</h1>")


@app.get("/healthz")
def healthz():
    return {
        "ok": True,
        "provider": engine.active_provider(),
        "model": engine.active_model(),
        "openai_key_set": bool(os.environ.get("OPENAI_API_KEY")),
        "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


@app.get("/api/schema")
def api_schema():
    return {"tables": [
        {"name": t, "desc": info["desc"], "cols": info["cols"].split()}
        for t, info in schema_catalog.TABLES.items()
    ]}


@app.get("/api/sample-questions")
def api_samples():
    return {"questions": [
        "How many wells are currently producing in the Eagle Ford Permian field?",
        "Top 5 wells by total oil production in 2025",
        "Show pending approval requests over 250,000 USD",
        "Which invoices are overdue and over 100k USD?",
        "How many SIF3 or higher incidents in 2025?",
        "Average daily oil production per field in the last 90 days",
        "Failed login attempts in the last 30 days, grouped by user",
        "Pipeline segments needing repair",
        "What is the AFE approval policy for spending over 1 million USD?",
        "How do we validate daily production data?",
        "Top 10 customers by shipment value this year",
        "Active permits expiring in the next 60 days",
    ]}


# =====================================================================
# Per-session conversation memory (in-process; trivially horizontally
# unscalable, but fine for hackathon / single-instance demo).
# =====================================================================

import time as _time
import uuid as _uuid

SESSIONS: dict[str, dict] = {}    # session_id -> {history: [...], last_access: float}
SESSION_TTL_SEC = 60 * 60          # 1 hour idle timeout
MAX_HISTORY_TURNS = 6              # ~12 messages cap


def _gc_sessions():
    cutoff = _time.time() - SESSION_TTL_SEC
    stale = [k for k, v in SESSIONS.items() if v["last_access"] < cutoff]
    for k in stale:
        SESSIONS.pop(k, None)


def _get_session(session_id: str | None) -> tuple[str, list[dict]]:
    _gc_sessions()
    if not session_id or session_id not in SESSIONS:
        sid = session_id or _uuid.uuid4().hex
        SESSIONS[sid] = {"history": [], "last_access": _time.time()}
        return sid, []
    SESSIONS[session_id]["last_access"] = _time.time()
    return session_id, SESSIONS[session_id]["history"]


def _record_turn(session_id: str, question: str, result):
    sess = SESSIONS.setdefault(session_id, {"history": [], "last_access": _time.time()})
    h = sess["history"]
    intent = None
    for ev in result.trace[::-1]:
        if ev.get("stage") == "_meta":
            intent = ev.get("payload", {}).get("intent")
            break
    h.append({"role": "user", "content": question})
    h.append({
        "role": "assistant",
        "content": result.answer,
        "sql": result.sql,
        "row_count": len(result.rows),
        "citations": [
            {"file_name": c.get("file_name"), "chunk_id": c.get("chunk_id")}
            for c in (result.citations or [])
        ],
        "intent": intent,
    })
    # Trim
    if len(h) > MAX_HISTORY_TURNS * 2:
        sess["history"] = h[-(MAX_HISTORY_TURNS * 2):]
    sess["last_access"] = _time.time()


class ChatIn(BaseModel):
    question: str
    session_id: str | None = None


@app.post("/api/chat")
def api_chat(body: ChatIn):
    sid, hist = _get_session(body.session_id)
    res = engine.run_chain(body.question, history=hist)
    _record_turn(sid, body.question, res)
    return {
        "session_id": sid,
        "answer": res.answer,
        "sql": res.sql,
        "columns": res.columns,
        "rows": res.rows,
        "citations": res.citations,
        "trace": res.trace,
    }


@app.get("/api/chat/stream")
async def api_chat_stream(question: str, session_id: str | None = None):
    """Server-Sent Events: emits trace_event lines and a final result event."""
    sid, hist = _get_session(session_id)
    queue: asyncio.Queue = asyncio.Queue()

    def on_event(ev: TraceEvent):
        queue.put_nowait(("trace", {"stage": ev.stage, "status": ev.status,
                                    "message": ev.message, "payload": ev.payload}))

    async def runner():
        loop = asyncio.get_running_loop()

        def _do():
            return engine.run_chain(question, history=hist, on_event=on_event)

        result = await loop.run_in_executor(None, _do)
        _record_turn(sid, question, result)
        queue.put_nowait(("final", {
            "session_id": sid,
            "answer": result.answer,
            "sql": result.sql,
            "columns": result.columns,
            "rows": result.rows,
            "citations": result.citations,
        }))
        queue.put_nowait(("done", None))

    asyncio.create_task(runner())

    async def event_gen() -> AsyncIterator[bytes]:
        while True:
            kind, data = await queue.get()
            if kind == "done":
                yield b"event: done\ndata: {}\n\n"
                return
            payload = json.dumps(data, default=str)
            yield f"event: {kind}\ndata: {payload}\n\n".encode("utf-8")

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# =====================================================================
# File upload : extract text -> chunks -> FTS5 in real time
# =====================================================================

UPLOAD_DIR = HERE.parent / "documents" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024   # 5 MB (text only)
ALLOWED_EXT = {".txt", ".md", ".log", ".csv"}


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...),
                     session_id: str | None = None):
    """Accept a text file, extract -> chunk -> save to DB, return summary.
    If a session_id is provided as a query param, the upload is also recorded
    in that session's history so subsequent chat turns have file context.
    """
    name = file.filename or "upload.txt"
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Only text files allowed ({sorted(ALLOWED_EXT)}). Got {ext!r}.")

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large (max {MAX_UPLOAD_BYTES // 1024} KB).")

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception as e:
            raise HTTPException(400, f"Could not decode as text: {e}")

    if not text.strip():
        raise HTTPException(400, "File is empty.")

    # Persist to disk so re-running ingest sees it too
    safe_name = re.sub(r"[^A-Za-z0-9._\- ]", "_", name)
    dest = UPLOAD_DIR / safe_name
    if dest.exists():
        # de-collide by adding a counter
        i = 1
        while True:
            dest = UPLOAD_DIR / f"{Path(safe_name).stem}_{i}{ext}"
            if not dest.exists():
                break
            i += 1
    dest.write_text(text, encoding="utf-8")

    # Extract + index
    info = doc_extraction.extract_and_store(
        text=text,
        file_name=dest.name,
        source_path=f"file://{dest}",
    )
    info["server_path"] = str(dest)
    log.info("upload indexed: %s -> extract_id=%s, chunks=%s",
             dest.name, info.get("extract_id"), info.get("chunk_count"))

    # Record a synthetic turn into the session so the chat has file context.
    if session_id:
        sid, hist = _get_session(session_id)
        info["session_id"] = sid
        hist.append({"role": "user", "content": f"[Uploaded file: {dest.name}]"})
        hist.append({
            "role": "assistant",
            "content": (f"Indexed {dest.name} into the document store "
                        f"({info['chunk_count']} chunks, {info['word_count']} words). "
                        f"Summary: {info.get('summary', '')[:280]}"),
            "sql": None,
            "row_count": 0,
            "citations": [{"file_name": dest.name, "chunk_id": None}],
            "intent": "POLICY",
        })
        SESSIONS[sid]["history"] = hist[-(MAX_HISTORY_TURNS * 2):]
        SESSIONS[sid]["last_access"] = _time.time()

    return info


@app.get("/api/documents")
def api_documents(limit: int = 30):
    """List recently indexed documents (catalog + uploaded)."""
    return {"documents": doc_extraction.list_uploaded(limit=limit)}


@app.get("/api/session/{session_id}")
def api_session_get(session_id: str):
    s = SESSIONS.get(session_id)
    if not s:
        return {"session_id": session_id, "history": [], "exists": False}
    return {"session_id": session_id, "history": s["history"], "exists": True}


@app.post("/api/session/{session_id}/clear")
def api_session_clear(session_id: str):
    SESSIONS.pop(session_id, None)
    return {"ok": True, "session_id": session_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("winning_architecture.server:app", host="0.0.0.0", port=8000, reload=False)
