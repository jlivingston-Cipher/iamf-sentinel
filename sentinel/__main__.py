"""`python -m sentinel` — the Sentinel CLI."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
