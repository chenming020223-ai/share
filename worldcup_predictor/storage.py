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

        CREATE TABLE IF NOT EXISTS paper_bankroll_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            run_id INTEGER NOT NULL,
            fixture_id TEXT NOT NULL,
            market TEXT NOT NULL,
            selection TEXT NOT NULL,
            line REAL,
            bookmaker TEXT NOT NULL DEFAULT '',
            decimal_odds REAL,
            model_probability REAL,
            market_probability REAL,
            expected_value_per_unit REAL,
            ev_pbase_research REAL,
            ev_pfinal_exec REAL,
            signal_status TEXT NOT NULL DEFAULT '',
            ev_layer TEXT NOT NULL DEFAULT '',
            stake REAL NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            settled_at TEXT NOT NULL DEFAULT '',
            net_per_unit REAL,
            profit REAL,
            result_score TEXT NOT NULL DEFAULT '',
            bankroll_before REAL NOT NULL,
            bankroll_after_stake REAL NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(run_id) REFERENCES prediction_runs(id)
        );

        CREATE TABLE IF NOT EXISTS batch_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            official_date TEXT NOT NULL DEFAULT '',
            is_official INTEGER NOT NULL DEFAULT 0,
            date TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL DEFAULT '',
            fixture_ids TEXT NOT NULL DEFAULT '',
            collected_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            signal_count INTEGER NOT NULL DEFAULT 0,
            planned_stake REAL NOT NULL DEFAULT 0,
            expected_profit REAL NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL
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

        CREATE INDEX IF NOT EXISTS idx_paper_bankroll_ledger_run
            ON paper_bankroll_ledger(run_id);

        CREATE INDEX IF NOT EXISTS idx_batch_runs_created_at
            ON batch_runs(created_at);
        """
    )
    _ensure_column(conn, "prediction_runs", "snapshot_id", "INTEGER")
    _ensure_column(conn, "api_snapshots", "required_bookmaker", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "api_snapshots", "selected_bookmaker", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "api_snapshots", "odds_captured_at", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "api_snapshots", "kickoff_at", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "api_snapshots", "model_version", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "batch_runs", "title", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "batch_runs", "notes", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "batch_runs", "official_date", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "batch_runs", "is_official", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "paper_bankroll_ledger", "settled_at", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "paper_bankroll_ledger", "net_per_unit", "REAL")
    _ensure_column(conn, "paper_bankroll_ledger", "profit", "REAL")
    _ensure_column(conn, "paper_bankroll_ledger", "result_score", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "paper_bankroll_ledger", "ev_pbase_research", "REAL")
    _ensure_column(conn, "paper_bankroll_ledger", "ev_pfinal_exec", "REAL")
    _ensure_column(conn, "paper_bankroll_ledger", "signal_status", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "paper_bankroll_ledger", "ev_layer", "TEXT NOT NULL DEFAULT ''")
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
        run_id = int(cursor.lastrowid)
        _insert_paper_ledger_entries(conn, run_id, payload, created_at)
        conn.commit()
        return run_id


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


def record_batch_prediction(payload: dict[str, Any], db_path: str | Path | None = None) -> int:
    summary = payload.get("batchSummary") or {}
    plan = summary.get("portfolioPlan") or {}
    created_at = datetime.now(timezone.utc).isoformat()
    fixture_ids = payload.get("fixtureIds") or []
    fixture_ids_text = ",".join(str(item) for item in fixture_ids)
    stored_payload = dict(payload)
    with connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO batch_runs (
                created_at,
                title,
                notes,
                official_date,
                is_official,
                date,
                scope,
                fixture_ids,
                collected_count,
                failed_count,
                signal_count,
                planned_stake,
                expected_profit,
                payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                str(payload.get("batchTitle") or ""),
                str(payload.get("batchNotes") or ""),
                str(payload.get("officialDate") or ""),
                1 if payload.get("isOfficial") else 0,
                str(payload.get("date") or ""),
                str(payload.get("scope") or ""),
                fixture_ids_text,
                int(payload.get("collectedCount") or summary.get("success") or 0),
                int(payload.get("failedCount") or summary.get("failed") or 0),
                int(summary.get("signalCount") or 0),
                float(plan.get("plannedStake") or 0.0),
                float(plan.get("expectedProfit") or summary.get("expectedProfit") or 0.0),
                json.dumps(stored_payload, ensure_ascii=False),
            ),
        )
        batch_id = int(cursor.lastrowid)
        stored_payload["batchRunId"] = batch_id
        if payload.get("isOfficial"):
            official_date = str(payload.get("officialDate") or payload.get("date") or "")
            _mark_official_batch(conn, batch_id, official_date)
            stored_payload["isOfficial"] = True
            stored_payload["officialDate"] = official_date
        conn.execute(
            "UPDATE batch_runs SET payload_json = ? WHERE id = ?",
            (json.dumps(stored_payload, ensure_ascii=False), batch_id),
        )
        conn.commit()
    payload["batchRunId"] = batch_id
    return batch_id


def recent_batch_predictions(limit: int = 12, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                created_at,
                title,
                notes,
                official_date,
                is_official,
                date,
                scope,
                fixture_ids,
                collected_count,
                failed_count,
                signal_count,
                planned_stake,
                expected_profit
            FROM batch_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_batch_prediction_payload(batch_id: int, db_path: str | Path | None = None) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT payload_json FROM batch_runs WHERE id = ?",
            (batch_id,),
        ).fetchone()
    if not row:
        return None
    payload = json.loads(row["payload_json"])
    payload["batchRunId"] = batch_id
    return payload


def update_batch_metadata(
    batch_id: int,
    title: str = "",
    notes: str = "",
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    clean_title = str(title or "").strip()[:80]
    clean_notes = str(notes or "").strip()[:500]
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT payload_json FROM batch_runs WHERE id = ?",
            (batch_id,),
        ).fetchone()
        if not row:
            return None
        payload = json.loads(row["payload_json"])
        payload["batchRunId"] = batch_id
        payload["batchTitle"] = clean_title
        payload["batchNotes"] = clean_notes
        conn.execute(
            """
            UPDATE batch_runs
            SET title = ?, notes = ?, payload_json = ?
            WHERE id = ?
            """,
            (clean_title, clean_notes, json.dumps(payload, ensure_ascii=False), batch_id),
        )
        conn.commit()
    return payload


def mark_official_batch(
    batch_id: int,
    official_date: str = "",
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT date, payload_json FROM batch_runs WHERE id = ?",
            (batch_id,),
        ).fetchone()
        if not row:
            return None
        target_date = str(official_date or row["date"] or "").strip()
        _mark_official_batch(conn, batch_id, target_date)
        updated = conn.execute(
            "SELECT payload_json FROM batch_runs WHERE id = ?",
            (batch_id,),
        ).fetchone()
        conn.commit()
    payload = json.loads(updated["payload_json"])
    payload["batchRunId"] = batch_id
    return payload


def official_batch_for_date(
    date: str,
    scope: str = "",
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        if scope:
            row = conn.execute(
                """
                SELECT id, payload_json
                FROM batch_runs
                WHERE is_official = 1
                  AND official_date = ?
                  AND scope = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (date, scope),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT id, payload_json
                FROM batch_runs
                WHERE is_official = 1
                  AND official_date = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (date,),
            ).fetchone()
    if not row:
        return None
    payload = json.loads(row["payload_json"])
    payload["batchRunId"] = int(row["id"])
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
            and str(row["selected_bookmaker"] or "").strip()
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
            and str(row["selected_bookmaker"] or "").strip()
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
        ledger = conn.execute("SELECT COUNT(*) AS count FROM paper_bankroll_ledger").fetchone()["count"]
        open_ledger = conn.execute(
            "SELECT COUNT(*) AS count FROM paper_bankroll_ledger WHERE status = 'OPEN'"
        ).fetchone()["count"]
        settled_ledger = conn.execute(
            "SELECT COUNT(*) AS count FROM paper_bankroll_ledger WHERE status = 'SETTLED'"
        ).fetchone()["count"]
        batches = conn.execute("SELECT COUNT(*) AS count FROM batch_runs").fetchone()["count"]
        official_batches = conn.execute(
            "SELECT COUNT(*) AS count FROM batch_runs WHERE is_official = 1"
        ).fetchone()["count"]
    return {
        "db_path": str(path),
        "prediction_runs": int(count),
        "api_snapshots": int(snapshots),
        "match_results": int(results),
        "market_quotes": int(quotes),
        "paper_ledger_entries": int(ledger),
        "paper_ledger_open": int(open_ledger),
        "paper_ledger_settled": int(settled_ledger),
        "batch_runs": int(batches),
        "official_batch_runs": int(official_batches),
    }


def settle_open_paper_ledger(db_path: str | Path | None = None) -> dict[str, Any]:
    from .backtest import _settle_handicap, _settle_match_winner, _settle_total

    settled: list[int] = []
    awaiting: list[int] = []
    skipped: list[int] = []
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                l.*,
                p.payload_json,
                r.home_goals_90,
                r.away_goals_90
            FROM paper_bankroll_ledger AS l
            JOIN prediction_runs AS p
                ON p.id = l.run_id
            LEFT JOIN match_results AS r
                ON r.fixture_id = l.fixture_id
            WHERE l.status = 'OPEN'
            ORDER BY l.id ASC
            """
        ).fetchall()
        settled_at = datetime.now(timezone.utc).isoformat()
        for row in rows:
            if row["home_goals_90"] is None or row["away_goals_90"] is None:
                awaiting.append(int(row["id"]))
                continue
            payload = json.loads(row["payload_json"])
            market = str(row["market"] or "")
            selection = str(row["selection"] or "")
            odds = float(row["decimal_odds"] or 0.0)
            stake = float(row["stake"] or 0.0)
            line = row["line"]
            home_goals = int(row["home_goals_90"])
            away_goals = int(row["away_goals_90"])
            try:
                if market == "胜平负":
                    net = _settle_match_winner(payload, selection, home_goals, away_goals, odds)
                elif market == "大小球":
                    net = _settle_total(selection, float(line), home_goals, away_goals, odds)
                elif market == "让球":
                    net = _settle_handicap(payload, selection, float(line), home_goals, away_goals, odds)
                else:
                    skipped.append(int(row["id"]))
                    continue
            except (TypeError, ValueError):
                skipped.append(int(row["id"]))
                continue
            conn.execute(
                """
                UPDATE paper_bankroll_ledger
                SET status = 'SETTLED',
                    settled_at = ?,
                    net_per_unit = ?,
                    profit = ?,
                    result_score = ?
                WHERE id = ?
                """,
                (settled_at, net, stake * net, f"{home_goals}-{away_goals}", int(row["id"])),
            )
            settled.append(int(row["id"]))
        conn.commit()
    return {
        "settled": settled,
        "awaiting": awaiting,
        "skipped": skipped,
        "settledCount": len(settled),
        "awaitingCount": len(awaiting),
        "skippedCount": len(skipped),
    }


def _mark_official_batch(conn: sqlite3.Connection, batch_id: int, official_date: str) -> None:
    row = conn.execute(
        "SELECT date, scope, payload_json FROM batch_runs WHERE id = ?",
        (batch_id,),
    ).fetchone()
    if not row:
        return
    target_date = str(official_date or row["date"] or "").strip()
    scope = str(row["scope"] or "")
    conn.execute(
        """
        UPDATE batch_runs
        SET is_official = 0
        WHERE official_date = ?
          AND scope = ?
        """,
        (target_date, scope),
    )
    payload = json.loads(row["payload_json"])
    payload["isOfficial"] = True
    payload["officialDate"] = target_date
    conn.execute(
        """
        UPDATE batch_runs
        SET is_official = 1,
            official_date = ?,
            payload_json = ?
        WHERE id = ?
        """,
        (target_date, json.dumps(payload, ensure_ascii=False), batch_id),
    )


def _insert_paper_ledger_entries(
    conn: sqlite3.Connection,
    run_id: int,
    payload: dict[str, Any],
    created_at: str,
) -> None:
    portfolio = payload.get("portfolio") or {}
    recommendations = payload.get("recommendations") or []
    if not isinstance(recommendations, list):
        return
    bankroll_before = float(portfolio.get("bankroll") or 0.0)
    remaining = bankroll_before
    fixture_id = str((payload.get("match") or {}).get("id") or "")
    market_payload = payload.get("market") or {}
    selected_bookmakers = market_payload.get("selectedBookmakers") or market_payload.get("selected_bookmakers") or {}
    fallback_bookmaker = str(
        market_payload.get("selectedBookmaker")
        or market_payload.get("selected_bookmaker")
        or (payload.get("meta") or {}).get("bookmaker")
        or ""
    )
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "")
        signal_status = str(item.get("signal_status") or "")
        stake = _optional_float(item.get("stake")) or 0.0
        if signal_status:
            if signal_status != "PAPER_BUY" or stake <= 0:
                continue
        elif action not in {"BUY", "PAPER_BUY"} or stake <= 0:
            continue
        market_name = str(item.get("market") or "")
        remaining = max(0.0, remaining - stake)
        conn.execute(
            """
            INSERT INTO paper_bankroll_ledger (
                created_at, run_id, fixture_id, market, selection, line,
                bookmaker, decimal_odds, model_probability, market_probability,
                expected_value_per_unit, ev_pbase_research, ev_pfinal_exec,
                signal_status, ev_layer, stake, action, status,
                bankroll_before, bankroll_after_stake, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                int(run_id),
                fixture_id,
                market_name,
                str(item.get("selection") or ""),
                _optional_float(item.get("line")),
                _bookmaker_for_recommendation(market_name, selected_bookmakers, fallback_bookmaker),
                _optional_float(item.get("odds")),
                _optional_float(item.get("model_probability")),
                _optional_float(item.get("market_probability")),
                _optional_float(item.get("expected_value_per_unit")),
                _optional_float(item.get("ev_pbase_research")),
                _optional_float(item.get("ev_pfinal_exec")),
                signal_status,
                str(item.get("ev_layer") or ""),
                stake,
                action,
                "OPEN",
                bankroll_before,
                remaining,
                str(item.get("reason") or ""),
            ),
        )


def _bookmaker_for_recommendation(market_name: str, selected_bookmakers: dict[str, Any], fallback: str) -> str:
    key = {
        "胜平负": "1X2",
        "大小球": "OU",
        "让球": "AH",
    }.get(market_name)
    if key:
        return str(selected_bookmakers.get(key) or fallback)
    return fallback


def _optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
    selected_bookmakers = market.get("selected_bookmakers") or {}
    fallback_bookmaker = str(market.get("selected_bookmaker") or "")
    if not fallback_bookmaker and not selected_bookmakers:
        return
    captured_at = str(market.get("captured_at") or "")
    groups: list[tuple[str, float | None, dict[str, float], bool, str]] = []
    winner = market.get("match_winner") or {}
    if all(float(winner.get(key) or 0.0) > 1.0 for key in ("home_win", "draw", "away_win")):
        groups.append(("1X2", None, winner, True, str(selected_bookmakers.get("1X2") or fallback_bookmaker)))
    totals = _float_line_groups(market.get("totals") or {})
    primary_total = _primary_line(totals, "over", "under", preferred=2.5)
    groups.extend(
        ("OU", line, odds, line == primary_total, str(selected_bookmakers.get("OU") or fallback_bookmaker))
        for line, odds in totals.items()
    )
    handicaps = _float_line_groups(market.get("handicaps") or {})
    primary_handicap = _primary_line(handicaps, "home", "away", preferred=0.0)
    groups.extend(
        ("AH", line, odds, line == primary_handicap, str(selected_bookmakers.get("AH") or fallback_bookmaker))
        for line, odds in handicaps.items()
    )

    for market_type, line, odds, is_primary, bookmaker in groups:
        if not bookmaker:
            continue
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
