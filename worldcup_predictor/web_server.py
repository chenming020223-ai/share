from __future__ import annotations

import argparse
import base64
import hmac
import json
import mimetypes
import random
import urllib.parse
from dataclasses import asdict
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .api_football import ApiFootballClient, ApiFootballError
from .auto_predict import MIN_VALID_RECENT_MATCHES, RECENT_MATCH_FETCH_COUNT, run_auto_prediction
from .backtest import sync_completed_results
from .betting import DEFAULT_MIN_EDGE, build_distribution_audit, build_recommendations
from .calibration import MARKET_DATASET_VERSION, PBASE_MODEL_VERSION, build_model_validation_status
from .data_quality import apply_quality_gate, build_data_quality_report
from .data import load_fixtures, load_teams
from .localization import (
    is_first_division_league,
    localize_selection,
    to_api_name,
    to_beijing_time,
    translate_league_display,
    translate_league_name,
    translate_name,
    translate_team_display,
)
from .market import MarketSnapshot
from .model_governance import sample_model_governance
from .models import ModelConfig, as_bool, as_float, clamp
from .predictor import predict_match
from .poisson import score_matrix
from .report import build_chinese_report, build_excel_report, build_pdf_report
from .settings import env_bool, env_int, env_str
from .storage import (
    get_prediction_payload,
    recent_predictions,
    record_api_snapshot,
    record_prediction,
    storage_health,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PROJECT_ROOT / "web"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the World Cup predictor web app.")
    default_host = "0.0.0.0" if env_bool("WORLDCUP_PUBLIC_MODE", False) else "127.0.0.1"
    parser.add_argument("--host", default=env_str("WORLDCUP_WEB_HOST", default_host))
    parser.add_argument("--port", type=int, default=env_int("WORLDCUP_WEB_PORT", env_int("PORT", 8765)))
    args = parser.parse_args(argv)

    server = ThreadingHTTPServer((args.host, args.port), PredictorWebHandler)
    print(f"World Cup predictor web app: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


class PredictorWebHandler(BaseHTTPRequestHandler):
    server_version = "WorldCupPredictor/0.1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/healthz":
            self._send_json({"ok": True, "app": "worldcup-predictor"})
            return
        if not self._authorize_request():
            return
        if path in {"/", "/index.html"}:
            self._serve_static(WEB_ROOT / "index.html")
            return
        if path == "/api/sample-fixtures":
            self._send_json({"fixtures": list_sample_fixtures()})
            return
        if path == "/api/health":
            self._send_json(health_payload())
            return
        if path == "/api/api-status":
            self._send_json(api_status_payload())
            return
        if path == "/api/model-validation":
            self._send_json(build_model_validation_status())
            return
        if path == "/api/recent-predictions":
            self._send_json({"runs": recent_prediction_options()})
            return
        if path == "/api/search-fixtures":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                home = (query.get("home") or [""])[0]
                away = (query.get("away") or [""])[0]
                self._send_json({"fixtures": search_api_fixtures(home, away)})
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except ApiFootballError as exc:
                self._send_api_error(exc)
            return
        if path == "/api/today-fixtures":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                date = (query.get("date") or [_today_shanghai()])[0]
                scope = (query.get("scope") or ["first_division"])[0]
                self._send_json(today_fixture_options(date=date, scope=scope))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except ApiFootballError as exc:
                self._send_api_error(exc)
            return
        if path == "/api/report":
            query = urllib.parse.parse_qs(parsed.query)
            run_id = _optional_int((query.get("run_id") or [""])[0])
            if not run_id:
                self._send_error(HTTPStatus.BAD_REQUEST, "Missing run_id")
                return
            payload = get_prediction_payload(run_id)
            if not payload:
                self._send_error(HTTPStatus.NOT_FOUND, "Report not found")
                return
            report_format = ((query.get("format") or ["pdf"])[0] or "pdf").casefold()
            if report_format in {"xlsx", "excel"}:
                self._send_file(
                    build_excel_report(payload),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    f"worldcup_report_run_{run_id}.xlsx",
                )
            elif report_format == "md":
                self._send_file(
                    build_chinese_report(payload).encode("utf-8"),
                    "text/markdown; charset=utf-8",
                    f"worldcup_report_run_{run_id}.md",
                )
            else:
                self._send_file(
                    build_pdf_report(payload),
                    "application/pdf",
                    f"worldcup_report_run_{run_id}.pdf",
                )
            return

        static_path = (WEB_ROOT / path.lstrip("/")).resolve()
        if WEB_ROOT.resolve() not in static_path.parents and static_path != WEB_ROOT.resolve():
            self._send_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if static_path.exists() and static_path.is_file():
            self._serve_static(static_path)
            return
        self._send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        if not self._authorize_request():
            return
        if self.path not in {"/api/predict", "/api/random-today-predict", "/api/search-fixtures", "/api/today-fixtures", "/api/sync-results"}:
            self._send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        try:
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if self.path == "/api/search-fixtures":
                result = {
                    "fixtures": search_api_fixtures(
                        str(payload.get("home") or ""),
                        str(payload.get("away") or ""),
                        api_key=_api_key_from_request(payload),
                    )
                }
                self._send_json(result)
                return
            if self.path == "/api/today-fixtures":
                self._send_json(
                    today_fixture_options(
                        date=str(payload.get("date") or _today_shanghai()),
                        scope=str(payload.get("scope") or "first_division"),
                        api_key=_api_key_from_request(payload),
                    )
                )
                return
            if self.path == "/api/sync-results":
                sync_result = sync_completed_results(
                    api_key=_api_key_from_request(payload),
                )
                sync_result["modelValidation"] = build_model_validation_status()
                self._send_json(sync_result)
                return
            result = run_random_today_prediction(payload) if self.path == "/api/random-today-predict" else run_web_prediction(payload)
            result["runId"] = record_prediction(result)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        except ApiFootballError as exc:
            self._send_api_error(exc)
            return
        except Exception as exc:  # noqa: BLE001 - keep the local web app from crashing.
            self._send_json({"error": f"预测失败：{exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._send_json(result)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _authorize_request(self) -> bool:
        password = env_str("WORLDCUP_ACCESS_PASSWORD", "").strip()
        if not password:
            return True
        username = env_str("WORLDCUP_ACCESS_USER", "viewer").strip() or "viewer"
        authorization = self.headers.get("Authorization", "")
        supplied = ""
        if authorization.startswith("Basic "):
            try:
                supplied = base64.b64decode(authorization[6:]).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                supplied = ""
        expected = f"{username}:{password}"
        if hmac.compare_digest(supplied, expected):
            return True
        body = json.dumps({"error": "此页面需要访问口令。"}, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="WorldCup Predictor Share", charset="UTF-8"')
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def _serve_static(self, path: Path) -> None:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"error": message}, status=status)

    def _send_api_error(self, exc: ApiFootballError) -> None:
        status = _api_error_status(exc)
        self._send_json(
            {
                "error": str(exc),
                "errorKind": exc.kind,
                "retryable": exc.retryable,
                "statusCode": exc.status_code,
                "details": exc.details[:500] if exc.details else "",
            },
            status=status,
        )

    def _send_file(self, body: bytes, content_type: str, filename: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", content_type)
        self.send_header("content-disposition", f'attachment; filename="{filename}"')
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_web_prediction(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "sample")
    bankroll = as_float(payload.get("bankroll"), 1000.0)
    unit = _optional_float(payload.get("unit"))
    market_weight = clamp(as_float(payload.get("marketWeight"), 0.45), 0.0, 0.95)
    min_edge = clamp(as_float(payload.get("minEdge"), DEFAULT_MIN_EDGE), 0.0, 1.0)
    min_quality = clamp(as_float(payload.get("minQuality"), 0.60), 0.0, 1.0)
    force_picks = False

    if mode == "auto":
        home_value = str(payload.get("home") or "").strip()
        away_value = str(payload.get("away") or "").strip()
        fixture_id = _optional_int(payload.get("fixtureId"))
        if not fixture_id and (not home_value or not away_value):
            raise ValueError("API 模式需要填写两支球队，或填写 fixture_id。")
        auto = run_auto_prediction(
            home_value,
            away_value,
            api_key=_api_key_from_request(payload),
            fixture_id=fixture_id,
            market_weight=market_weight,
            bankroll=bankroll,
            unit_stake=unit,
            min_edge=min_edge,
            force_picks=force_picks,
        )
        quality = build_data_quality_report(
            auto.market,
            fixture_id=auto.fixture_id,
            team_rating_score=1.0 if auto.recent_form_available else 0.25,
            context_score=0.75 if auto.league_id and auto.season and auto.kickoff else 0.45,
            lineup_score=0.0,
            min_quality=min_quality,
            max_score=_quality_cap_for_recent_form(auto.recent_form_available, min_quality),
        )
        snapshot_id = _record_auto_snapshot(auto, "API-Football")
        recommendations, portfolio = apply_quality_gate(
            auto.recommendations,
            auto.portfolio,
            quality,
            enforce=True,
        )
        return {
            "mode": "auto",
            "meta": {
                "fixtureId": auto.fixture_id,
                "leagueId": auto.league_id,
                "leagueName": auto.league_name,
                "leagueCountry": auto.league_country,
                "leagueNameZh": translate_league_display(auto.league_name, auto.league_country),
                "season": auto.season,
                "kickoff": auto.kickoff,
                "kickoffBeijing": to_beijing_time(auto.kickoff),
                "venue": auto.venue,
                "dataSource": "API-Football",
                "snapshotId": snapshot_id,
                "requiredBookmaker": auto.market.required_bookmaker or "-",
                "bookmaker": auto.market.selected_bookmaker or "未取得",
                "oddsCapturedAt": auto.market.captured_at or "",
                "oddsCapturedAtBeijing": to_beijing_time(auto.market.captured_at or ""),
                "marketDatasetVersion": MARKET_DATASET_VERSION,
                "pbaseModelVersion": PBASE_MODEL_VERSION,
                "recentMatchesHome": auto.home_recent_matches,
                "recentMatchesAway": auto.away_recent_matches,
                "recentMatchesRequired": MIN_VALID_RECENT_MATCHES,
                "recentMatchesRequested": RECENT_MATCH_FETCH_COUNT,
            },
            "snapshotId": snapshot_id,
            "modelValidation": build_model_validation_status(),
            "dataProcessing": _data_processing_payload(auto),
            **_prediction_payload(
                auto.result,
                auto.market,
                recommendations,
                portfolio,
                auto.data_notes,
                quality,
                auto.governance,
            ),
        }

    return run_sample_prediction(
        match_id=str(payload.get("matchId") or "").strip(),
        home_name=str(payload.get("home") or "").strip(),
        away_name=str(payload.get("away") or "").strip(),
        market_weight=market_weight,
        bankroll=bankroll,
        unit_stake=unit,
        min_edge=min_edge,
        force_picks=force_picks,
        min_quality=min_quality,
    )


def run_random_today_prediction(payload: dict[str, Any]) -> dict[str, Any]:
    bankroll = as_float(payload.get("bankroll"), 1000.0)
    unit = _optional_float(payload.get("unit"))
    market_weight = clamp(as_float(payload.get("marketWeight"), 0.45), 0.0, 0.95)
    min_edge = clamp(as_float(payload.get("minEdge"), DEFAULT_MIN_EDGE), 0.0, 1.0)
    min_quality = clamp(as_float(payload.get("minQuality"), 0.60), 0.0, 1.0)
    date = str(payload.get("date") or _today_shanghai())

    client = ApiFootballClient(api_key=_api_key_from_request(payload))
    fixtures = [
        item
        for item in client.fixtures_by_date(date)
        if _fixture_has_two_teams(item) and _is_pre_match_fixture(item)
    ]
    if not fixtures:
        raise ApiFootballError("今天暂无可预测的赛前比赛，请使用搜索比赛或填写比赛 ID。")

    fixture_row = random.choice(fixtures)
    teams = fixture_row.get("teams") or {}
    home = (teams.get("home") or {}).get("name") or ""
    away = (teams.get("away") or {}).get("name") or ""
    fixture_id = int((fixture_row.get("fixture") or {}).get("id"))
    auto = run_auto_prediction(
        str(home),
        str(away),
        api_key=_api_key_from_request(payload),
        fixture_id=fixture_id,
        market_weight=market_weight,
        bankroll=bankroll,
        unit_stake=unit,
        min_edge=min_edge,
        force_picks=False,
    )
    quality = build_data_quality_report(
        auto.market,
        fixture_id=auto.fixture_id,
        team_rating_score=1.0 if auto.recent_form_available else 0.25,
        context_score=0.75 if auto.league_id and auto.season and auto.kickoff else 0.45,
        lineup_score=0.0,
        min_quality=min_quality,
        max_score=_quality_cap_for_recent_form(auto.recent_form_available, min_quality),
    )
    snapshot_id = _record_auto_snapshot(auto, f"API-Football 随机今日比赛 {date}")
    recommendations, portfolio = apply_quality_gate(
        auto.recommendations,
        auto.portfolio,
        quality,
        enforce=True,
    )
    result = {
        "mode": "auto",
        "meta": {
            "fixtureId": auto.fixture_id,
            "leagueId": auto.league_id,
            "leagueName": auto.league_name,
            "leagueCountry": auto.league_country,
            "leagueNameZh": translate_league_display(auto.league_name, auto.league_country),
            "season": auto.season,
            "kickoff": auto.kickoff,
            "kickoffBeijing": to_beijing_time(auto.kickoff),
            "venue": auto.venue,
            "dataSource": f"API-Football 随机今日比赛 {date}",
            "snapshotId": snapshot_id,
            "requiredBookmaker": auto.market.required_bookmaker or "-",
            "bookmaker": auto.market.selected_bookmaker or "未取得",
            "oddsCapturedAt": auto.market.captured_at or "",
            "oddsCapturedAtBeijing": to_beijing_time(auto.market.captured_at or ""),
            "marketDatasetVersion": MARKET_DATASET_VERSION,
            "pbaseModelVersion": PBASE_MODEL_VERSION,
            "recentMatchesHome": auto.home_recent_matches,
            "recentMatchesAway": auto.away_recent_matches,
            "recentMatchesRequired": MIN_VALID_RECENT_MATCHES,
            "recentMatchesRequested": RECENT_MATCH_FETCH_COUNT,
        },
        "snapshotId": snapshot_id,
        "modelValidation": build_model_validation_status(),
        "dataProcessing": _data_processing_payload(auto),
        **_prediction_payload(
            auto.result,
            auto.market,
            recommendations,
            portfolio,
            auto.data_notes,
            quality,
            auto.governance,
        ),
    }
    return result


def search_api_fixtures(
    home_name: str,
    away_name: str,
    limit: int = 20,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    home_name = home_name.strip()
    away_name = away_name.strip()
    if not home_name:
        raise ValueError("请至少填写球队 A。")

    client = ApiFootballClient(api_key=api_key.strip() if api_key else None)
    home = client.resolve_team(to_api_name("team", home_name))
    away = client.resolve_team(to_api_name("team", away_name)) if away_name else None

    fixtures: list[dict[str, Any]] = []
    if away:
        fixtures.extend(client.next_head_to_head_candidates(home.id, away.id, limit=10))
        if not fixtures:
            fixtures.extend(
                item
                for item in client.team_next_fixtures(home.id, limit=50)
                if _fixture_contains_team(item, away.id)
            )
    else:
        fixtures.extend(client.team_next_fixtures(home.id, limit=limit))

    return [_fixture_option(item) for item in fixtures[:limit]]


def today_fixture_options(
    date: str,
    scope: str = "first_division",
    api_key: str | None = None,
    client: ApiFootballClient | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if scope not in {"first_division", "all"}:
        raise ValueError("今日赛程范围仅支持甲级联赛或全部比赛。")
    source = client or ApiFootballClient(api_key=api_key)
    rows = [
        item
        for item in source.fixtures_by_date(date)
        if _fixture_has_two_teams(item)
        and _is_pre_match_fixture(item, now=now)
        and (
            scope == "all"
            or is_first_division_league(
                (item.get("league") or {}).get("name"),
                (item.get("league") or {}).get("country"),
            )
        )
    ]
    fixtures = sorted((_fixture_option(item) for item in rows), key=lambda item: str(item.get("date") or ""))
    scope_zh = "甲级联赛" if scope == "first_division" else "全部赛事"
    return {
        "date": date,
        "dateLabel": f"{date} 北京时间",
        "scope": scope,
        "scopeZh": scope_zh,
        "fixtures": fixtures,
        "count": len(fixtures),
        "message": f"{date} 北京时间找到 {len(fixtures)} 场尚未开赛的{scope_zh}比赛。",
    }


def run_sample_prediction(
    match_id: str = "",
    home_name: str = "",
    away_name: str = "",
    market_weight: float = 0.45,
    bankroll: float = 1000.0,
    unit_stake: float | None = None,
    min_edge: float = DEFAULT_MIN_EDGE,
    force_picks: bool = False,
    min_quality: float = 0.60,
) -> dict[str, Any]:
    teams = load_teams(PROJECT_ROOT / "data/sample_teams.csv")
    fixtures = load_fixtures(PROJECT_ROOT / "data/sample_fixtures.csv")
    fixture = _resolve_sample_fixture(fixtures, match_id, home_name, away_name)
    home = teams[fixture.home_team]
    away = teams[fixture.away_team]
    config = ModelConfig(market_weight=market_weight)
    result = predict_match(home, away, fixture, config)
    matrix = score_matrix(result.expected_goals_home, result.expected_goals_away, config.max_goals)
    market = _sample_market_snapshot(fixture)
    league_name = fixture.extras.get("league_name", "")
    kickoff = fixture.extras.get("kickoff_utc", "")
    recommendations, portfolio = build_recommendations(
        result,
        matrix,
        market,
        bankroll=bankroll,
        unit_stake=unit_stake,
        min_edge=min_edge,
        force_picks=force_picks,
    )
    quality = build_data_quality_report(
        market,
        fixture_id=fixture.match_id,
        team_rating_score=1.0,
        context_score=0.75,
        lineup_score=0.0,
        min_quality=min_quality,
        sample=True,
    )
    governance = sample_model_governance()
    return {
        "mode": "sample",
        "meta": {
            "fixtureId": fixture.match_id,
            "leagueName": league_name,
            "leagueNameZh": translate_league_name(league_name),
            "kickoff": kickoff,
            "kickoffBeijing": to_beijing_time(kickoff),
            "venue": "本地示例",
            "dataSource": "本地示例 CSV",
            "requiredBookmaker": "本地示例",
            "bookmaker": "本地示例",
        },
        **_prediction_payload(
            result,
            market,
            recommendations,
            portfolio,
            ["本地示例仅用于界面预览，不代表真实赛程、真实赔率或真实建议。"],
            quality,
            governance,
        ),
    }


def list_sample_fixtures() -> list[dict[str, str]]:
    fixtures = load_fixtures(PROJECT_ROOT / "data/sample_fixtures.csv")
    items: list[dict[str, str]] = []
    for fixture in fixtures.values():
        home_zh = translate_name("team", fixture.home_team)
        away_zh = translate_name("team", fixture.away_team)
        league_name = fixture.extras.get("league_name", "")
        league_zh = translate_league_name(league_name)
        kickoff_beijing = to_beijing_time(fixture.extras.get("kickoff_utc", ""))
        items.append(
            {
                "matchId": fixture.match_id,
                "home": fixture.home_team,
                "away": fixture.away_team,
                "homeZh": home_zh,
                "awayZh": away_zh,
                "league": league_name,
                "leagueZh": league_zh,
                "kickoffBeijing": kickoff_beijing,
                "label": " · ".join(
                    part
                    for part in [f"{home_zh} vs {away_zh}", league_zh, kickoff_beijing]
                    if part
                ),
            }
        )
    return items


def health_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "app": "worldcup-predictor",
        "version": "0.1.0",
        "api": {
            "provider": "API-Football",
            "configured": bool(env_str("API_FOOTBALL_KEY", "").strip()),
            "retries": env_int("API_FOOTBALL_RETRIES", 3),
        },
        "storage": storage_health(),
        "deployment": {
            "publicMode": env_bool("WORLDCUP_PUBLIC_MODE", False),
            "accessProtected": bool(env_str("WORLDCUP_ACCESS_PASSWORD", "").strip()),
            "apiKeyManagedByServer": env_bool("WORLDCUP_PUBLIC_MODE", False),
        },
    }


def _api_key_from_request(payload: dict[str, Any]) -> str | None:
    if env_bool("WORLDCUP_PUBLIC_MODE", False):
        return None
    return str(payload.get("apiKey") or "").strip() or None


def recent_prediction_options(limit: int = 12) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for item in recent_predictions(limit=limit):
        payload = get_prediction_payload(int(item["id"])) or {}
        match = payload.get("match") or {}
        meta = payload.get("meta") or {}
        options.append(
            {
                **item,
                "homeZh": translate_team_display(match.get("home") or item.get("home_team"), "主队"),
                "awayZh": translate_team_display(match.get("away") or item.get("away_team"), "客队"),
                "leagueZh": translate_league_display(meta.get("leagueName"), meta.get("leagueCountry")),
                "kickoffBeijing": meta.get("kickoffBeijing") or to_beijing_time(meta.get("kickoff")),
            }
        )
    return options


def api_status_payload(api_key: str | None = None) -> dict[str, Any]:
    configured = bool((api_key or env_str("API_FOOTBALL_KEY", "")).strip())
    if not configured:
        return {
            "ok": False,
            "configured": False,
            "message": "未配置 API-Football 密钥。",
        }

    try:
        client = ApiFootballClient(api_key=api_key)
        status = client.status()
        response = status.get("response") or {}
        requests = response.get("requests") if isinstance(response, dict) else None
        subscription = response.get("subscription") if isinstance(response, dict) else None
        sanitized_subscription = {}
        if isinstance(subscription, dict):
            sanitized_subscription = {
                "plan": subscription.get("plan"),
                "end": subscription.get("end"),
                "active": subscription.get("active"),
            }
        return {
            "ok": True,
            "configured": True,
            "message": "API-Football 可连接。",
            "requests": requests if isinstance(requests, dict) else {},
            "subscription": sanitized_subscription,
        }
    except ApiFootballError as exc:
        return {
            "ok": False,
            "configured": True,
            "message": str(exc),
            "errorKind": exc.kind,
            "retryable": exc.retryable,
            "statusCode": exc.status_code,
        }


def _api_error_status(exc: ApiFootballError) -> HTTPStatus:
    if exc.kind == "auth":
        return HTTPStatus.UNAUTHORIZED
    if exc.kind == "rate_limit":
        return HTTPStatus.TOO_MANY_REQUESTS
    if exc.kind in {"network", "certificate"}:
        return HTTPStatus.BAD_GATEWAY
    return HTTPStatus.BAD_REQUEST


def _fixture_option(row: dict[str, Any]) -> dict[str, Any]:
    fixture = row.get("fixture") or {}
    league = row.get("league") or {}
    teams = row.get("teams") or {}
    status = (fixture.get("status") or {})
    home_name = str((teams.get("home") or {}).get("name") or "")
    away_name = str((teams.get("away") or {}).get("name") or "")
    league_name = str(league.get("name") or "")
    league_country = str(league.get("country") or "")
    date = str(fixture.get("date") or "")
    return {
        "fixtureId": fixture.get("id"),
        "date": date,
        "dateBeijing": to_beijing_time(date),
        "league": league_name,
        "leagueCountry": league_country,
        "leagueZh": translate_league_display(league_name, league_country),
        "season": league.get("season"),
        "home": home_name,
        "away": away_name,
        "homeZh": translate_team_display(home_name, "主队"),
        "awayZh": translate_team_display(away_name, "客队"),
        "homeNameStatus": "已收录" if translate_name("team", home_name) != home_name else "待核定",
        "awayNameStatus": "已收录" if translate_name("team", away_name) != away_name else "待核定",
        "status": status.get("short") or status.get("long"),
    }


def _fixture_contains_team(row: dict[str, Any], team_id: int) -> bool:
    teams = row.get("teams") or {}
    return ((teams.get("home") or {}).get("id") == team_id) or ((teams.get("away") or {}).get("id") == team_id)


def _fixture_has_two_teams(row: dict[str, Any]) -> bool:
    teams = row.get("teams") or {}
    fixture = row.get("fixture") or {}
    return bool(fixture.get("id") and (teams.get("home") or {}).get("name") and (teams.get("away") or {}).get("name"))


def _is_pre_match_fixture(row: dict[str, Any], now: datetime | None = None) -> bool:
    fixture = row.get("fixture") or {}
    status = (fixture.get("status") or {}).get("short")
    if status not in {"NS", "TBD", "PST"}:
        return False

    kickoff = _parse_fixture_datetime(str(fixture.get("date") or ""))
    if kickoff is None:
        return False
    current = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return kickoff.astimezone(ZoneInfo("Asia/Shanghai")) > current.astimezone(ZoneInfo("Asia/Shanghai"))


def _parse_fixture_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed


def _today_shanghai() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


def _quality_cap_for_recent_form(recent_form_available: bool, min_quality: float) -> float | None:
    if recent_form_available:
        return None
    return max(0.0, min(0.59, min_quality - 0.01))


def _record_auto_snapshot(auto, source: str) -> int:
    snapshot = auto.raw_snapshot or {}
    return record_api_snapshot(
        fixture_id=auto.fixture_id,
        home_team=auto.result.home_team,
        away_team=auto.result.away_team,
        source=source,
        fixture=snapshot.get("fixture") or {},
        odds=snapshot.get("odds") or [],
        team_stats={
            **(snapshot.get("team_stats") or {}),
            "recent_form": snapshot.get("recent_form") or {},
        },
        h2h=snapshot.get("h2h") or [],
        market=auto.market,
        kickoff_at=auto.kickoff,
        model_version=PBASE_MODEL_VERSION,
        notes=snapshot.get("notes") or auto.data_notes,
    )


def _data_processing_payload(auto) -> dict[str, Any]:
    recent_form = (auto.raw_snapshot or {}).get("recent_form") or {}
    home = _form_series_payload(auto.result.home_team, "主队", recent_form.get("home") or [])
    away = _form_series_payload(auto.result.away_team, "客队", recent_form.get("away") or [])
    fixture_label = translate_league_display(auto.league_name, auto.league_country)
    odds_status = (
        f"已取得 {auto.market.selected_bookmaker} 全场盘口"
        if auto.market.selected_bookmaker
        else "未取得指定庄家全场盘口"
    )
    return {
        "requestedMatches": RECENT_MATCH_FETCH_COUNT,
        "requiredMatches": MIN_VALID_RECENT_MATCHES,
        "coverageReady": auto.recent_form_available,
        "home": home,
        "away": away,
        "steps": [
            {
                "label": "定位比赛",
                "status": "完成",
                "detail": f"{fixture_label} · 比赛 ID {auto.fixture_id} · {to_beijing_time(auto.kickoff)}",
            },
            {
                "label": "抓取近期赛果",
                "status": "完成" if auto.recent_form_available else "不足",
                "detail": (
                    f"{home['displayName']} 有效 {home['validCount']}/{RECENT_MATCH_FETCH_COUNT} 场，"
                    f"{away['displayName']} 有效 {away['validCount']}/{RECENT_MATCH_FETCH_COUNT} 场"
                ),
            },
            {
                "label": "提取强度特征",
                "status": "完成" if auto.recent_form_available else "限制",
                "detail": "按 90 分钟赛果计算场均进球、场均失球、场均积分及攻防评分。",
            },
            {
                "label": "抓取盘口",
                "status": "完成" if auto.market.selected_bookmaker else "缺失",
                "detail": odds_status,
            },
            {
                "label": "模型与风险闸门",
                "status": "已执行",
                "detail": "生成独立模型概率并检查盘口分歧、质量门槛与正式 EV 准入状态。",
            },
        ],
        "oddsTrend": {
            "available": False,
            "message": "本场当前仅保存单次赛前赔率快照，不能形成真实赔率走势曲线。",
        },
        "rawAudit": {
            "home": auto.result.home_team,
            "away": auto.result.away_team,
            "league": auto.league_name,
            "leagueCountry": auto.league_country,
        },
    }


def _form_series_payload(team_name: str, role_label: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    chronological = sorted(rows, key=lambda item: str(item.get("date") or ""))
    points = sum(int(item.get("points") or 0) for item in chronological)
    goals_for = sum(int(item.get("goals_for") or 0) for item in chronological)
    goals_against = sum(int(item.get("goals_against") or 0) for item in chronological)
    count = len(chronological)
    ppg = points / count if count else 0.0
    gf_avg = goals_for / count if count else 0.0
    ga_avg = goals_against / count if count else 0.0
    attack_rating = clamp(0.55 + gf_avg / 1.8, 0.65, 1.6) if count else 1.0
    defense_rating = clamp(1.55 - ga_avg / 2.2, 0.65, 1.55) if count else 1.0
    estimated_elo = 1450.0 + ppg * 110.0 if count else 1500.0
    cumulative = 0
    matches: list[dict[str, Any]] = []
    for item in chronological:
        row_points = int(item.get("points") or 0)
        cumulative += row_points
        goals_for_row = int(item.get("goals_for") or 0)
        goals_against_row = int(item.get("goals_against") or 0)
        result = "胜" if row_points == 3 else "平" if row_points == 1 else "负"
        matches.append(
            {
                "fixtureId": item.get("fixture_id"),
                "date": item.get("date"),
                "dateBeijing": item.get("date_beijing") or to_beijing_time(item.get("date")),
                "opponent": item.get("opponent") or "",
                "opponentZh": item.get("opponent_zh") or "历史快照未保存对手名称",
                "league": item.get("league") or "",
                "leagueZh": item.get("league_zh") or "历史快照未保存赛事名称",
                "venueLabel": "主场" if item.get("venue") == "home" else "客场",
                "goalsFor": goals_for_row,
                "goalsAgainst": goals_against_row,
                "points": row_points,
                "cumulativePoints": cumulative,
                "resultLabel": result,
                "included": True,
            }
        )
    return {
        "displayName": translate_team_display(team_name, role_label),
        "rawName": team_name,
        "validCount": count,
        "points": points,
        "pointsPerGame": ppg,
        "goalsForAverage": gf_avg,
        "goalsAgainstAverage": ga_avg,
        "attackRating": attack_rating,
        "defenseRating": defense_rating,
        "estimatedElo": estimated_elo,
        "matches": matches,
    }


def _prediction_payload(
    result,
    market: MarketSnapshot,
    recommendations,
    portfolio,
    notes: list[str],
    data_quality,
    governance,
) -> dict[str, Any]:
    home_zh = translate_team_display(result.home_team, "主队")
    away_zh = translate_team_display(result.away_team, "客队")
    model_audit = build_distribution_audit(result, market)
    audit_notes = [str(model_audit["reason"])] if model_audit.get("evSuspended") else []
    return {
        "match": {
            "id": result.match_id,
            "home": result.home_team,
            "away": result.away_team,
            "homeZh": home_zh,
            "awayZh": away_zh,
        },
        "probabilities": {
            "display": result.final_probabilities,
            "final": result.final_probabilities,
            "pbase": result.model_probabilities,
            "model": result.model_probabilities,
            "qmkt": result.market_probabilities,
            "market": result.market_probabilities,
        },
        "modelGovernance": governance.to_dict(),
        "modelAudit": model_audit,
        "expectedGoals": {
            "home": result.expected_goals_home,
            "away": result.expected_goals_away,
        },
        "topScores": [{"score": score, "probability": probability} for score, probability in result.top_scores],
        "featureEdges": result.feature_edges,
        "market": _market_payload(market),
        "dataQuality": data_quality.to_dict(),
        "recommendations": [
            {
                **asdict(item),
                "selection": localize_selection(item.selection, result.home_team, result.away_team),
            }
            for item in recommendations
        ],
        "portfolio": asdict(portfolio),
        "notes": [*audit_notes, *notes, *data_quality.notes, *governance.notes],
    }


def _market_payload(market: MarketSnapshot) -> dict[str, Any]:
    total_line = market.best_total_line()
    handicap_line = market.best_handicap_line()
    return {
        "bookmakersCount": market.bookmakers_count,
        "requiredBookmaker": market.required_bookmaker,
        "selectedBookmaker": market.selected_bookmaker,
        "capturedAt": market.captured_at,
        "matchWinnerOdds": market.match_winner,
        "totalLine": {"line": total_line[0], "odds": total_line[1]} if total_line else None,
        "handicapLine": {"homeLine": handicap_line[0], "odds": handicap_line[1]} if handicap_line else None,
        "rawBookmakers": market.raw_bookmakers,
        "warnings": list(market.warnings),
    }


def _resolve_sample_fixture(fixtures, match_id: str, home_name: str, away_name: str):
    if match_id:
        if match_id not in fixtures:
            raise ValueError(f"找不到示例比赛 {match_id}。")
        return fixtures[match_id]

    home = to_api_name("team", home_name).casefold()
    away = to_api_name("team", away_name).casefold()
    if home and away:
        for fixture in fixtures.values():
            pair = {fixture.home_team.casefold(), fixture.away_team.casefold()}
            if {home, away} == pair:
                return fixture

    available = ", ".join(f"{item.home_team} vs {item.away_team}" for item in fixtures.values())
    raise ValueError(f"请选择示例比赛，或输入示例中的两支球队。可用示例：{available}")


def _sample_market_snapshot(fixture) -> MarketSnapshot:
    total_line = as_float(fixture.extras.get("total_line"), 2.5)
    handicap_line = as_float(fixture.extras.get("handicap_home_line"), -0.5)
    return MarketSnapshot(
        fixture_id=None,
        bookmakers_count=1,
        required_bookmaker="本地示例",
        selected_bookmaker="本地示例",
        match_winner={
            "home_win": fixture.odds_home,
            "draw": fixture.odds_draw,
            "away_win": fixture.odds_away,
        },
        totals={
            total_line: {
                "over": as_float(fixture.extras.get("odds_over"), 0.0),
                "under": as_float(fixture.extras.get("odds_under"), 0.0),
            }
        },
        handicaps={
            handicap_line: {
                "home": as_float(fixture.extras.get("handicap_home_odds"), 0.0),
                "away": as_float(fixture.extras.get("handicap_away_odds"), 0.0),
            }
        },
    )


def _optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    return as_float(value)


def _optional_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
