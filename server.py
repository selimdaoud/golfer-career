"""Point d'entrée pratique pour lancer le serveur FastAPI avec uvicorn."""
from __future__ import annotations

import uvicorn


if __name__ == "__main__":
    uvicorn.run("routes.api:app", host="127.0.0.1", port=8000, reload=True)
