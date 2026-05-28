from __future__ import annotations

import csv
from pathlib import Path

from .models import Fixture, TeamProfile


def load_teams(path: str | Path) -> dict[str, TeamProfile]:
    rows = _read_csv(path)
    teams = [TeamProfile.from_row(row) for row in rows]
    missing = [row for row in teams if not row.name]
    if missing:
        raise ValueError(f"Team file {path} contains rows without a team name.")
    return {team.name: team for team in teams}


def load_fixtures(path: str | Path) -> dict[str, Fixture]:
    rows = _read_csv(path)
    fixtures = [Fixture.from_row(row) for row in rows]
    missing = [row for row in fixtures if not row.match_id or not row.home_team or not row.away_team]
    if missing:
        raise ValueError(f"Fixture file {path} needs match_id, home_team, and away_team on every row.")
    return {fixture.match_id: fixture for fixture in fixtures}


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))
