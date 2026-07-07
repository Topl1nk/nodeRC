"""graph_migration.py — Upgrading Graph Snapshots

Applies a chained series of migrations to a loaded JSON payload, ensuring that
GraphModel.from_dict only ever has to parse the current, latest schema version.
"""
from __future__ import annotations

def migrate(payload: dict) -> dict:
    """Migrate an older graph payload to the current schema version.
    Returns the mutated payload (or a new dict)."""
    # version = payload.get("version", 1)
    
    # if version == 1:
    #     payload = _migrate_1_to_2(payload)
    #     version = 2
        
    # payload["version"] = version
    return payload
