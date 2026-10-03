"""Writes the OpenAPI snapshot to docs/openapi.json. Run from backend/: python -m scripts.export_openapi"""

import json
from pathlib import Path

from app.main import app

OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"


def run() -> None:
    OUTPUT.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    run()
