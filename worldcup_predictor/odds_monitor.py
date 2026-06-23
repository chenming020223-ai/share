from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .api_football import ApiFootballClient
from .market import parse_api_football_odds
from .storage import odds_movement_coverage, record_odds_movement_snapshot


def collect_fixture_odds_snapshot(
    fixture_id: int | str,
    *,
    api_key: str | None = None,
    bookmaker_priority: list[str] | tuple[str, ...] | str | None = None,
    client: Any | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    source = client or ApiFootballClient(api_key=api_key)
    fixture_number = int(fixture_id)
    fixture = source.fixture_by_id(fixture_number)
    odds_rows = source.odds(fixture_number)
    market = parse_api_football_odds(
        odds_rows or [],
        required_bookmaker=None,
        bookmaker_priority=bookmaker_priority,
    )
    stored = record_odds_movement_snapshot(
        fixture_id=fixture_number,
        fixture=fixture,
        odds=odds_rows,
        market=market,
        source="API-Football odds monitor",
        db_path=db_path,
    )
    return {
        "fixtureId": str(fixture_number),
        "selectedBookmakers": dict(market.selected_bookmakers),
        "availableBookmakerCount": market.available_bookmakers_count,
        "capturedAt": market.captured_at,
        "stored": stored,
        "warnings": list(market.warnings),
        "rawMarket": asdict(market),
        "requestsUsed": int(getattr(source, "logical_requests", 0) or 0),
    }


def collect_fixture_odds_snapshots(
    fixture_ids: list[int | str],
    *,
    api_key: str | None = None,
    bookmaker_priority: list[str] | tuple[str, ...] | str | None = None,
    client: Any | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    source = client or ApiFootballClient(api_key=api_key)
    results = []
    for fixture_id in fixture_ids:
        results.append(
            collect_fixture_odds_snapshot(
                fixture_id,
                bookmaker_priority=bookmaker_priority,
                client=source,
                db_path=db_path,
            )
        )
    return {
        "ok": True,
        "results": results,
        "coverage": odds_movement_coverage(db_path=db_path),
        "requestsUsed": int(getattr(source, "logical_requests", 0) or 0),
    }
