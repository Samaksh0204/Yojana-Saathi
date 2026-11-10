import json
from functools import lru_cache

from .config import get_settings
from .schemas import Scheme


@lru_cache
def load_schemes() -> list[Scheme]:
    schemes: list[Scheme] = []
    for path in sorted((get_settings().data_dir / "schemes").glob("*.json")):
        schemes += [Scheme(**item) for item in json.loads(path.read_text(encoding="utf-8"))]
    ids = [s.id for s in schemes]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate scheme ids in data/schemes")
    return schemes


@lru_cache
def schemes_by_id() -> dict[str, Scheme]:
    return {s.id: s for s in load_schemes()}
