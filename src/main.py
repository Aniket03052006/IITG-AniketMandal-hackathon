"""Convenience entry point: ``python src/main.py`` (equivalent to ``python -m eventshock``)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eventshock.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
