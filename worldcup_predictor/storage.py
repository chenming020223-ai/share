from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings import default_db_path


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS prediction_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            mode TEXT NOT NULL,
            match_id TEXT NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            bankroll REAL NOT NULL,
            unit_stake REAL NOT NULL,
            active_bets INTEGER NOT NULL,
            total_stake REAL NOT NULL,
            expected_profit REAL NOT NULL,
            snapshot_id INTEGER,
            payload_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS api_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            fixture_id TEXT NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            source TEXT NOT NULL,
            required_bookmaker TEXT NOT NULL DEFAULT '',
            selected_bookmaker TEXT NOT NULL DEFAULT '',
            odds_captured_at TEXT NOT NULL DEFAULT '',
            kickoff_at TEXT NOT NULL DEFAULT '',
            model_version TEXT NOT NULL DEFAULT '',
            fixture_json TEXT NOT NULL,
            odds_json TEXT NOT NULL,
            team_stats_json TEXT NOT NULL,
            h2h_json TEXT NOT NULL,
            notes TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS match_results (
            fixture_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            home_goals_90 INTEGER NOT NULL,
            away_goals_90 INTEGER NOT NULL,
            notes TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS market_quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            fixture_id TEXT NOT NULL,
            bookmaker TEXT NOT NULL,
            captured_at TEXT NOT NULL DEFAULT '',
            kickoff_at TEXT NOT NULL DEFAULT '',
            model_version TEXT NOT NULL DEFAULT '',
            market_type TEXT NOT NULL,
            line REAL,
            line_key TEXT NOT NULL,
            selection TEXT NOT NULL,
            decimal_odds REAL NOT NULL,
            market_probability REAL NOT NULL,
            market_key TEXT NOT NULL,
            selection_key TEXT NOT NULL,
            is_primary INTEGER NOT NULL DEFAULT 0,
            UNIQUE(snapshot_id, selection_key),
            FOREIGN KEY(snapshot_id) REFERENCES api_snapshots(id)
        );

        CREATE INDEX IF NOT EXISTS idx_prediction_runs_created_at
            ON prediction_runs(created_at);

        CREATE INDEX IF NOT EXISTS idx_prediction_runs_match
            ON prediction_runs(match_id, home_team, away_team);

        CREATE INDEX IF NOT EXISTS idx_api_snapshots_fixture
            ON api_snapshots(fixture_id);

        CREATE INDEX IF NOT EXISTS idx_market_quotes_snapshot
            ON market_quotes(snapshot_id);

        CREATE INDEX IF NOT EXISTS idx_market_quotes_fixture_time
            ON market_quotes(fixture_id, captured_at);
        """
    )
    _ensure_column(conn, "prediction_runs", "snapshot_id", "INTEGER")
    _ensure_column(conn, "api_snapshots", "required_bookmaker", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "api_snapshots", "selected_bookmaker", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "api_snapshots", "odds_captured_at", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "api_snapshots", "kickoff_at", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "api_snapshots", "model_version", "TEXT NOT NULL DEFAULT ''")
    _backfill_structured_market_quotes(conn)
    conn.commit()


def record_prediction(payload: dict[str, Any], db_path: str | Path | None = None) -> int:
    match = payload.get("match") or {}
    meta = payload.get("meta") or {}
    portfolio = payload.get("portfolio") or {}
    snapshot_id = _optional_int(payload.get("snapshotId") or meta.get("snapshotId"))
    created_at = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO prediction_runs (
                created_at,
                mode,
                match_id,
                home_team,
                away_team,
                bankroll,
                unit_stake,
                active_bets,
                total_stake,
                expected_profit,
                snapshot_id,
                payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                str(payload.get("mode") or ""),
                str(match.get("id") or ""),
                str(match.get("home") or ""),
                str(match.get("away") or ""),
                float(portfolio.get("bankroll") or 0.0),
                float(portfolio.get("unit_stake") or 0.0),
                int(portfolio.get("active_bets") or 0),
                float(portfolio.get("total_stake") or 0.0),
                float(portfolio.get("expected_profit") or 0.0),
                snapshot_id,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def recent_predictions(limit: int = 20, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                created_at,
                mode,
                match_id,
                home_team,
                away_team,
                bankroll,
                unit_stake,
                active_bets,
                total_stake,
                expected_profit,
                snapshot_id
            FROM prediction_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_prediction_payload(run_id: int, db_path: str | Path | None = None) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT payload_json FROM prediction_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    if not row:
        return None
    payload = json.loads(row["payload_json"])
    payload["runId"] = run_id
    return payload


def record_api_snapshot(
    *,
    fixture_id: str | int | None,
    home_team: str,
    away_team: str,
    source: str,
    fixture: Any,
    odds: Any,
    team_stats: Any,
    h2h: Any,
    market: Any = None,
    kickoff_at: str = "",
    model_version: str = "",
    notes: list[str] | str | None = None,
    db_path: str | Path | None = None,
) -> int:
    created_at = datetime.now(timezone.utc).isoformat()
    note_text = "\n".join(notes) if isinstance(notes, list) else str(notes or "")
    market_data = _market_data(market, odds)
    kickoff_value = kickoff_at or _fixture_kickoff(fixture)
    with connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO api_snapshots (
                created_at,
                fixture_id,
                home_team,
                away_team,
                source,
                required_bookmaker,
                selected_bookmaker,
                odds_captured_at,
                kickoff_at,
                model_version,
                fixture_json,
                odds_json,
                team_stats_json,
                h2h_json,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                str(fixture_id or ""),
                home_team,
                away_team,
                source,
                str(market_data.get("required_bookmaker") or ""),
                str(market_data.get("selected_bookmaker") or ""),
                str(market_data.get("captured_at") or ""),
                str(kickoff_value or ""),
                str(model_version or ""),
                json.dumps(fixture, ensure_ascii=False),
                json.dumps(odds, ensure_ascii=False),
                json.dumps(team_stats, ensure_ascii=False),
                json.dumps(h2h, ensure_ascii=False),
                note_text,
            ),
        )
        snapshot_id = int(cursor.lastrowid)
        _insert_market_quotes(
            conn,
            snapshot_id=snapshot_id,
            fixture_id=str(fixture_id or ""),
            market=market_data,
            kickoff_at=str(kickoff_value or ""),
            model_version=str(model_version or ""),
        )
        conn.commit()
        return snapshot_id


def get_api_snapshot(snapshot_id: int, db_path: str | Path | None = None) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM api_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    for key in ("fixture_json", "odds_json", "team_stats_json", "h2h_json"):
        data[key] = json.loads(data[key])
    return data


def market_quotes_for_snapshot(snapshot_id: int, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM market_quotes
            WHERE snapshot_id = ?
            ORDER BY market_type, line_key, selection
            """,
            (snapshot_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def market_dataset_coverage(db_path: str | Path | None = None) -> dict[str, int]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, selected_bookmaker, odds_captured_at, kickoff_at
            FROM api_snapshots
            """
        ).fetchall()
        quote_count = conn.execute("SELECT COUNT(*) AS count FROM market_quotes").fetchone()["count"]
        pinnacle_quotes = conn.execute(
            "SELECT COUNT(*) AS count FROM market_quotes WHERE lower(bookmaker) = lower('Pinnacle')"
        ).fetchone()["count"]
    with_time = 0
    eligible_pre_match = 0
    post_kickoff = 0
    for row in rows:
        captured = _parse_datetime(row["odds_captured_at"])
        created = _parse_datetime(row["created_at"])
        kickoff = _parse_datetime(row["kickoff_at"])
        if captured and kickoff:
            with_time += 1
        if kickoff and created and created >= kickoff:
            post_kickoff += 1
        elif (
            kickoff
            and created
            and captured
            and created < kickoff
            and captured < kickoff
            and str(row["selected_bookmaker"] or "").casefold() == "pinnacle"
        ):
            eligible_pre_match += 1
    return {
        "snapshots": len(rows),
        "structured_quotes": int(quote_count),
        "pinnacle_quotes": int(pinnacle_quotes),
        "snapshots_with_odds_time": with_time,
        "eligible_pre_match_snapshots": eligible_pre_match,
        "post_kickoff_snapshots": post_kickoff,
    }


def record_match_result(
    fixture_id: str | int,
    home_goals_90: int,
    away_goals_90: int,
    notes: str = "",
    db_path: str | Path | None = None,
) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO match_results (
                fixture_id,
                created_at,
                home_goals_90,
                away_goals_90,
                notes
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(fixture_id) DO UPDATE SET
                created_at = excluded.created_at,
                home_goals_90 = excluded.home_goals_90,
                away_goals_90 = excluded.away_goals_90,
                notes = excluded.notes
            """,
            (str(fixture_id), created_at, int(home_goals_90), int(away_goals_90), notes),
        )
        conn.commit()


def prediction_payloads_with_results(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                prediction_runs.id AS run_id,
                prediction_runs.payload_json AS payload_json,
                match_results.home_goals_90 AS home_goals_90,
                match_results.away_goals_90 AS away_goals_90
            FROM prediction_runs
            JOIN match_results
                ON prediction_runs.match_id = match_results.fixture_id
            ORDER BY prediction_runs.id ASC
            """
        ).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        payload["runId"] = int(row["run_id"])
        results.append(
            {
                "payload": payload,
                "home_goals_90": int(row["home_goals_90"]),
                "away_goals_90": int(row["away_goals_90"]),
            }
        )
    return results


def calibration_source_rows(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                prediction_runs.id AS run_id,
                prediction_runs.created_at AS prediction_created_at,
                prediction_runs.match_id AS fixture_id,
                prediction_runs.snapshot_id AS snapshot_id,
                prediction_runs.payload_json AS payload_json,
                match_results.home_goals_90 AS home_goals_90,
                match_results.away_goals_90 AS away_goals_90,
                api_snapshots.odds_captured_at AS odds_captured_at,
                api_snapshots.kickoff_at AS kickoff_at,
                api_snapshots.selected_bookmaker AS selected_bookmaker
            FROM prediction_runs
            JOIN match_results
                ON prediction_runs.match_id = match_results.fixture_id
            LEFT JOIN api_snapshots
                ON prediction_runs.snapshot_id = api_snapshots.id
            WHERE prediction_runs.mode = 'auto'
            ORDER BY prediction_runs.created_at ASC, prediction_runs.id ASC
            """
        ).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        data["payload"] = json.loads(data.pop("payload_json"))
        results.append(data)
    return results


def pending_result_fixtures(db_path: str | Path | None = None) -> list[str]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT
                s.fixture_id,
                s.created_at,
                s.odds_captured_at,
                s.kickoff_at,
                s.selected_bookmaker
            FROM api_snapshots AS s
            JOIN prediction_runs AS p
                ON p.snapshot_id = s.id AND p.mode = 'auto'
            LEFT JOIN match_results AS r
                ON r.fixture_id = s.fixture_id
            WHERE r.fixture_id IS NULL
            """
        ).fetchall()
    eligible: set[str] = set()
    for row in rows:
        created = _parse_datetime(row["created_at"])
        captured = _parse_datetime(row["odds_captured_at"])
        kickoff = _parse_datetime(row["kickoff_at"])
        if (
            created
            and captured
            and kickoff
            and created < kickoff
            and captured < kickoff
            and str(row["selected_bookmaker"] or "").casefold() == "pinnacle"
        ):
            eligible.add(str(row["fixture_id"]))
    return sorted(eligible)


def storage_health(db_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(db_path) if db_path else default_db_path()
    with connect(path) as conn:
        count = conn.execute("SELECT COUNT(*) AS count FROM prediction_runs").fetchone()["count"]
        snapshots = conn.execute("SELECT COUNT(*) AS count FROM api_snapshots").fetchone()["count"]
        results = conn.execute("SELECT COUNT(*) AS count FROM match_results").fetchone()["count"]
        quotes = conn.execute("SELECT COUNT(*) AS count FROM market_quotes").fetchone()["count"]
    return {
        "db_path": str(path),
        "prediction_runs": int(count),
        "api_snapshots": int(snapshots),
        "match_results": int(results),
        "market_quotes": int(quotes),
    }


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _optional_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _market_data(market: Any, odds: Any) -> dict[str, Any]:
    if is_dataclass(market):
        return asdict(market)
    if isinstance(market, dict):
        return market
    try:
        from .market import parse_api_football_odds

        return asdict(parse_api_football_odds(odds or []))
    except (TypeError, ValueError):
        return {}


def _fixture_kickoff(fixture: Any) -> str:
    if not isinstance(fixture, dict):
        return ""
    meta = fixture.get("fixture") or fixture
    return str(meta.get("date") or "")


def _insert_market_quotes(
    conn: sqlite3.Connection,
    *,
    snapshot_id: int,
    fixture_id: str,
    market: dict[str, Any],
    kickoff_at: str,
    model_version: str,
) -> None:
    bookmaker = str(market.get("selected_bookmaker") or "")
    if not bookmaker:
        return
    captured_at = str(market.get("captured_at") or "")
    groups: list[tuple[str, float | None, dict[str, float], bool]] = []
    winner = market.get("match_winner") or {}
    if all(float(winner.get(key) or 0.0) > 1.0 for key in ("home_win", "draw", "away_win")):
        groups.append(("1X2", None, winner, True))
    totals = _float_line_groups(market.get("totals") or {})
    primary_total = _primary_line(totals, "over", "under", preferred=2.5)
    groups.extend(("OU", line, odds, line == primary_total) for line, odds in totals.items())
    handicaps = _float_line_groups(market.get("handicaps") or {})
    primary_handicap = _primary_line(handicaps, "home", "away", preferred=0.0)
    groups.extend(("AH", line, odds, line == primary_handicap) for line, odds in handicaps.items())

    for market_type, line, odds, is_primary in groups:
        probabilities = _devig_prices(odds)
        line_key = "" if line is None else f"{line:g}"
        market_key = f"{fixture_id}:FT:{market_type}:{line_key or '-'}"
        for selection, decimal_odds in odds.items():
            if decimal_odds <= 1.0 or selection not in probabilities:
                continue
            selection_key = f"{market_key}:{selection}"
            conn.execute(
                """
                INSERT OR IGNORE INTO market_quotes (
                    snapshot_id, fixture_id, bookmaker, captured_at, kickoff_at,
                    model_version, market_type, line, line_key, selection,
                    decimal_odds, market_probability, market_key, selection_key, is_primary
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    fixture_id,
                    bookmaker,
                    captured_at,
                    kickoff_at,
                    model_version,
                    market_type,
                    line,
                    line_key,
                    selection,
                    float(decimal_odds),
                    probabilities[selection],
                    market_key,
                    selection_key,
                    int(is_primary),
                ),
            )


def _float_line_groups(raw_groups: dict[Any, Any]) -> dict[float, dict[str, float]]:
    groups: dict[float, dict[str, float]] = {}
    for raw_line, raw_odds in raw_groups.items():
        try:
            line = float(raw_line)
        except (TypeError, ValueError):
            continue
        odds = {
            str(key): float(value)
            for key, value in (raw_odds or {}).items()
            if float(value or 0.0) > 1.0
        }
        if len(odds) >= 2:
            groups[line] = odds
    return groups


def _primary_line(groups: dict[float, dict[str, float]], first: str, second: str, preferred: float) -> float | None:
    available = [
        (line, odds)
        for line, odds in groups.items()
        if first in odds and second in odds
    ]
    if not available:
        return None
    return min(available, key=lambda item: (abs(item[1][first] - item[1][second]), abs(item[0] - preferred), item[0]))[0]


def _devig_prices(odds: dict[str, float]) -> dict[str, float]:
    implied = {key: 1.0 / float(value) for key, value in odds.items() if float(value) > 1.0}
    total = sum(implied.values())
    return {key: value / total for key, value in implied.items()} if total else {}


def _backfill_structured_market_quotes(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT s.*
        FROM api_snapshots AS s
        WHERE NOT EXISTS (SELECT 1 FROM market_quotes AS q WHERE q.snapshot_id = s.id)
        """
    ).fetchall()
    if not rows:
        return
    from .market import parse_api_football_odds

    for row in rows:
        try:
            odds = json.loads(row["odds_json"])
            fixture = json.loads(row["fixture_json"])
            market = asdict(parse_api_football_odds(odds or []))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        kickoff_at = str(row["kickoff_at"] or _fixture_kickoff(fixture))
        conn.execute(
            """
            UPDATE api_snapshots
            SET required_bookmaker = ?, selected_bookmaker = ?, odds_captured_at = ?, kickoff_at = ?
            WHERE id = ?
            """,
            (
                str(market.get("required_bookmaker") or ""),
                str(market.get("selected_bookmaker") or ""),
                str(market.get("captured_at") or ""),
                kickoff_at,
                int(row["id"]),
            ),
        )
        _insert_market_quotes(
            conn,
            snapshot_id=int(row["id"]),
            fixture_id=str(row["fixture_id"]),
            market=market,
            kickoff_at=kickoff_at,
            model_version=str(row["model_version"] or ""),
        )


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
