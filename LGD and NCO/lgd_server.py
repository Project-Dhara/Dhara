"""FastAPI server: look up an LGD entity by code or name.

Run from the repo root or from LGD/:

    uvicorn lgd_server:app --app-dir LGD --port 8005

Or:

    python LGD/lgd_server.py
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query

from lgd_directory import Directory

directory = Directory.load()
app = FastAPI(title="LGD lookup", description="Resolve an LGD code or name.")


def _entity_payload(record: dict) -> dict:
    return {
        "lgd_code": record["lgd_code"],
        "name": record["name_english"],
        "entity_type": record["entity_type"],
        "aliases": record["aliases"],
        "hierarchy_parts": record["hierarchy_parts"],
    }


def _name_payload(match: dict) -> dict:
    return {
        "lgd_code": match["lgd_code"],
        "name": match["name_english"],
        "entity_type": match["entity_type"],
        "hierarchy_parts": match["hierarchy_parts"],
    }


@app.get("/")
def root() -> dict:
    return {
        "entities": len(directory.entities),
        "source": str(directory.source),
        "by_code": "/lgd/{code}",
        "by_name": "/name?q=",
    }


@app.get("/lgd/{code}")
def get_by_code(code: str) -> dict:
    matches = directory.by_code(code)
    if not matches:
        raise HTTPException(status_code=404, detail=f"No entity for code {code}")
    entities = [_entity_payload(record) for record in matches]
    if len(entities) == 1:
        return entities[0]
    return {"code": code, "count": len(entities), "entities": entities}


@app.get("/name")
def get_by_name(q: str = Query(..., min_length=1, description="Entity name to look up")) -> dict:
    result = directory.search(q)
    matches = result["matches"]
    if not matches:
        raise HTTPException(status_code=404, detail=f"No entity for name {q!r}")
    entities = [_name_payload(match) for match in matches]
    if len(entities) == 1:
        return entities[0]
    return {
        "query": q,
        "kind": result["kind"],
        "count": result["total"],
        "entities": entities,
    }


def main() -> None:
    import uvicorn

    print(f"Indexed {len(directory.entities)} entities from {directory.source}")
    uvicorn.run("lgd_server:app", host="0.0.0.0", port=8005, reload=False)


if __name__ == "__main__":
    main()
