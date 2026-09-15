"""Application entry point for development.

Run:
    python run.py
"""

from __future__ import annotations

import sys


def main() -> int:
    from app.main import run

    return run()


if __name__ == "__main__":
    sys.exit(main())
