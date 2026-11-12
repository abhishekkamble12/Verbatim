"""CLI runner forwarding to packages.evaluation.run_agent."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packages.evaluation.run_agent import main

if __name__ == "__main__":
    main()
