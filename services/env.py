"""Read the git-ignored .env for local runs. Variables already set in the environment win."""

import os
from pathlib import Path


def load_env_file(path: str | Path = Path(__file__).resolve().parents[1] / ".env") -> None:
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
