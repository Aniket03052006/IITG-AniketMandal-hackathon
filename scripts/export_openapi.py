"""Write the API's OpenAPI schema to web/src/api/openapi.json (input to `npm run gen:api`)."""

from __future__ import annotations

import json
from pathlib import Path

from eventshock.api.main import create_app

OUT = Path(__file__).resolve().parents[1] / "web" / "src" / "api" / "openapi.json"


def main() -> None:
    schema = create_app().openapi()
    OUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(OUT.parents[3])}")


if __name__ == "__main__":
    main()
