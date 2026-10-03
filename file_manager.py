# file_manager.py
"""
file_manager.py
JSON 입출력 · 실행별 폴더
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

from config import RUNS_DIR


def save_json(data, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def new_run_dir() -> Path:
    """실행마다 별도 폴더 (동시 사용 시 산출물이 섞이지 않게)."""
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    path = RUNS_DIR / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path
