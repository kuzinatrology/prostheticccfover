"""Every parameter set that ever broke a property, kept and re-run forever.

Hypothesis shrinks a failure by trying dozens of nearby parameter sets, and
every one of those is a genuine failing case. Keeping all of them would make
the suite crawl for no extra coverage, so the corpus holds a handful per kind
of failure and drops the rest.
"""

from __future__ import annotations

import json
import pathlib
import re

CORPUS = pathlib.Path(__file__).parent / "regressions" / "corpus.jsonl"

PER_KIND = 3
"""How many parameter sets to keep for each kind of failure."""


def kind(reason: str) -> str:
    """The reason with its numbers removed, so near misses group together."""
    return re.sub(r"[-+]?\d*\.?\d+", "#", reason).strip()


def load(path: pathlib.Path = CORPUS) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def record(params: dict, reason: str, path: pathlib.Path = CORPUS) -> None:
    """Append a failing case unless this kind of failure is well covered."""
    existing = load(path)
    if any(e["params"] == params for e in existing):
        return
    group = kind(reason)
    if sum(1 for e in existing if kind(e["reason"]) == group) >= PER_KIND:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps({"reason": reason, "params": params}, sort_keys=True) + "\n")


def prune() -> int:
    """Trim the corpus to PER_KIND entries per kind. Returns how many went."""
    entries = load()
    counts: dict[str, int] = {}
    keep = []
    for entry in entries:
        group = kind(entry["reason"])
        counts[group] = counts.get(group, 0) + 1
        if counts[group] <= PER_KIND:
            keep.append(entry)
    CORPUS.write_text(
        "".join(json.dumps(e, sort_keys=True) + "\n" for e in keep)
    )
    return len(entries) - len(keep)
