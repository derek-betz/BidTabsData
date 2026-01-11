"""FastAPI service for BidTabsData metadata access."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent_hub import fetch_knowledge, publish_knowledge, register_agent

load_dotenv()

DATA_ROOT = Path(os.getenv("BIDTABSDATA_PATH", Path(__file__).resolve().parent / "data"))

app = FastAPI(title="BidTabsData API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HealthResponse(BaseModel):
    status: str
    version: str


@app.on_event("startup")
def on_startup() -> None:
    register_agent()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version="0.1.0")


@app.get("/agent/info")
def agent_info() -> dict[str, Any]:
    return {
        "name": "BidTabsData",
        "capabilities": ["bidtabs", "dataset", "metadata"],
    }


@app.post("/agent/register")
def agent_register() -> dict[str, str]:
    register_agent()
    return {"status": "registered"}


@app.post("/agent/knowledge/publish")
def agent_publish(payload: dict[str, Any]) -> dict[str, str]:
    publish_knowledge(payload)
    return {"status": "queued"}


@app.get("/agent/knowledge/query")
def agent_query(
    source: str | None = None,
    topic: str | None = None,
    tag: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    return fetch_knowledge(source=source, topic=topic, tag=tag, limit=limit)


def _list_files() -> list[Path]:
    if not DATA_ROOT.exists():
        return []
    return [path for path in DATA_ROOT.rglob("*") if path.is_file()]


@app.get("/data/summary")
def data_summary() -> dict[str, Any]:
    files = _list_files()
    extensions = {}
    for path in files:
        ext = path.suffix.lower()
        extensions[ext] = extensions.get(ext, 0) + 1
    return {
        "root": str(DATA_ROOT),
        "total_files": len(files),
        "extensions": extensions,
    }


@app.get("/data/files")
def data_files(pattern: str = "") -> list[dict[str, Any]]:
    files = _list_files()
    results = []
    for path in files:
        if pattern and pattern.lower() not in path.name.lower():
            continue
        results.append(
            {
                "name": path.name,
                "path": str(path.relative_to(DATA_ROOT)),
                "size": path.stat().st_size,
            }
        )
    return results


def start_server() -> None:
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "9008"))
    uvicorn.run("bidtabs_api:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    start_server()
