from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .api_football import ApiFootballError
from .data_layer import CachedApiFootballClient
from .localization import is_first_division_league, to_beijing_time, translate_league_display, translate_team_display
from .settings import env_int
from .storage import record_prediction
from .web_server import run_web_prediction


def collect_daily_batch(
    *,
    date: str | None = None,
    scope: str = "first_division",
    limit: int | None = None,
    collection_mode: str = "batch",
    api_key: str | None = None,
    bankroll: float = 1000.0,
    unit_stake: float = 0.0,
) -> dict[str, Any]:
    target_date = date or _today_shanghai()
    max_fixtures = limit if limit is not None else env_int("WORLDCUP_BATCH_MAX_FIXTURES", 30)
    client = CachedApiFootballClient(api_key=api_key)
    fixtures = [
        item
        for item in client.fixtures_by_date(target_date)
        if _fixture_has_two_teams(item)
        and _is_pre_match_fixture(item)
        and (
            scope == "all"
            or is_first_division_league(
                (item.get("league") or {}).get("name"),
                (item.get("league") or {}).get("country"),
            )
        )
    ]
    fixtures = sorted(fixtures, key=lambda item: str((item.get("fixture") or {}).get("date") or ""))
    if max_fixtures > 0:
        fixtures = fixtures[:max_fixtures]

    collected: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for item in fixtures:
        fixture = item.get("fixture") or {}
        teams = item.get("teams") or {}
        league = item.get("league") or {}
        fixture_id = fixture.get("id")
        home = str((teams.get("home") or {}).get("name") or "")
        away = str((teams.get("away") or {}).get("name") or "")
        try:
            payload = run_web_prediction(
                {
                    "mode": "auto",
                    "home": home,
                    "away": away,
                    "fixtureId": fixture_id,
                    "apiKey": api_key or "",
                    "bankroll": bankroll,
                    "unit": unit_stake,
                    "collectionMode": collection_mode,
                },
                client=client,
            )
            run_id = record_prediction(payload)
            collected.append(
                {
                    "runId": run_id,
                    "fixtureId": fixture_id,
                    "home": translate_team_display(home, "主队"),
                    "away": translate_team_display(away, "客队"),
                    "league": translate_league_display(league.get("name"), league.get("country")),
                    "kickoffBeijing": to_beijing_time(fixture.get("date")),
                    "snapshotId": payload.get("snapshotId"),
                    "bookmaker": (payload.get("meta") or {}).get("bookmaker"),
                    "deepStatsMatches": ((payload.get("dataProcessing") or {}).get("deepStatsMatches")),
                    "apiLogicalRequests": ((payload.get("dataProcessing") or {}).get("apiRequests") or {}).get("logical"),
                    "apiHttpAttempts": ((payload.get("dataProcessing") or {}).get("apiRequests") or {}).get("httpAttempts"),
                    "apiCacheHits": ((payload.get("dataProcessing") or {}).get("apiRequests") or {}).get("cacheHits"),
                }
            )
        except (ApiFootballError, ValueError) as exc:
            failed.append(
                {
                    "fixtureId": fixture_id,
                    "home": translate_team_display(home, "主队"),
                    "away": translate_team_display(away, "客队"),
                    "error": str(exc),
                }
            )

    result = {
        "date": target_date,
        "scope": scope,
        "collectionMode": collection_mode,
        "candidateFixtures": len(fixtures),
        "collectedCount": len(collected),
        "failedCount": len(failed),
        "apiLogicalRequests": client.logical_requests,
        "apiHttpAttempts": client.http_attempts,
        "apiCacheHits": client.cache_hits,
        "apiCacheMisses": client.cache_misses,
        "collected": collected,
        "failed": failed,
        "message": f"{target_date} 批量建库完成：成功 {len(collected)} 场，失败 {len(failed)} 场。",
    }
    _write_batch_log(result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run daily World Cup predictor batch collection.")
    parser.add_argument("--date", help="北京时间日期，例如 2026-05-28。默认今天。")
    parser.add_argument("--scope", choices=["first_division", "all"], default="first_division")
    parser.add_argument("--limit", type=int, help="最多处理多少场。默认读取 WORLDCUP_BATCH_MAX_FIXTURES，缺省 30。")
    parser.add_argument("--mode", choices=["deep", "batch", "fast"], default="batch", help="抓取模式。后台默认 batch。")
    parser.add_argument("--api-key", help="API-Football key。默认读取环境变量或 .env。")
    parser.add_argument("--json", action="store_true", help="输出 JSON。")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = collect_daily_batch(
        date=args.date,
        scope=args.scope,
        limit=args.limit,
        collection_mode=args.mode,
        api_key=args.api_key,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["message"])
        for item in result["collected"]:
            print(f"- 运行 {item['runId']}: {item['home']} vs {item['away']} · {item['league']} · {item['kickoffBeijing']}")
        for item in result["failed"]:
            print(f"- 失败 {item['fixtureId']}: {item['home']} vs {item['away']} · {item['error']}")
    return 0


def _fixture_has_two_teams(row: dict[str, Any]) -> bool:
    teams = row.get("teams") or {}
    fixture = row.get("fixture") or {}
    return bool(fixture.get("id") and (teams.get("home") or {}).get("name") and (teams.get("away") or {}).get("name"))


def _is_pre_match_fixture(row: dict[str, Any]) -> bool:
    fixture = row.get("fixture") or {}
    status = (fixture.get("status") or {}).get("short")
    if status not in {"NS", "TBD", "PST"}:
        return False
    kickoff = str(fixture.get("date") or "")
    if not kickoff:
        return False
    try:
        parsed = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
    except ValueError:
        return False
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed.astimezone(ZoneInfo("Asia/Shanghai")) > now


def _today_shanghai() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


def _write_batch_log(result: dict[str, Any]) -> None:
    log_dir = Path(__file__).resolve().parents[1] / "storage" / "batch_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S")
    path = log_dir / f"batch_{result['date']}_{timestamp}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
