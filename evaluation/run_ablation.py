"""CLI runner forwarding to packages.evaluation.run_ablation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packages.evaluation.run_ablation import main

if __name__ == "__main__":
    main()

