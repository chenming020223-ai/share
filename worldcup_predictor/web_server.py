from __future__ import annotations

import argparse
import base64
import copy
import hmac
import json
import mimetypes
import random
import threading
import time
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
from .backtest import sync_completed_paper_ledger_results, sync_completed_results
from .betting import DEFAULT_MIN_EDGE, build_distribution_audit, build_recommendations
from .calibration import MARKET_DATASET_VERSION, PBASE_MODEL_VERSION, build_model_validation_status
from .data_quality import apply_quality_gate, build_data_quality_report
from .data import load_fixtures, load_teams
from .data_layer import CachedApiFootballClient
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
from .live_readiness import build_live_readiness_status
from .market import MarketSnapshot
from .model_governance import sample_model_governance
from .models import ModelConfig, as_bool, as_float, clamp
from .odds_monitor import collect_fixture_odds_snapshots
from .paper_bankroll import build_paper_ledger_book
from .predictor import predict_match
from .poisson import score_matrix
from .payload_governance import apply_current_score_validation_to_payload
from .report import build_chinese_report, build_excel_report, build_pdf_report
from .replay import build_history_replay_ledger, build_prediction_replay
from .review import build_daily_review, build_daily_review_excel
from .score_calibration import build_score_distribution_calibration_status
from .settings import env_bool, env_int, env_str
from .storage import (
    get_batch_prediction_payload,
    get_prediction_payload,
    mark_official_batch,
    recent_batch_predictions,
    recent_predictions,
    record_api_snapshot,
    record_batch_prediction,
    record_prediction,
    settle_open_paper_ledger,
    storage_health,
    update_batch_metadata,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PROJECT_ROOT / "web"
_MODEL_VALIDATION_CACHE: tuple[float, dict[str, Any]] | None = None
_AUTO_SETTLEMENT_LOCK = threading.Lock()
_AUTO_SETTLEMENT_STARTED = False
_AUTO_SETTLEMENT_RUNNING = False
_AUTO_SETTLEMENT_LAST_RUN = 0.0
_AUTO_SETTLEMENT_LAST_RESULT: dict[str, Any] | None = None


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the World Cup predictor web app.")
    default_host = "0.0.0.0" if env_bool("WORLDCUP_PUBLIC_MODE", False) else "127.0.0.1"
    parser.add_argument("--host", default=env_str("WORLDCUP_WEB_HOST", default_host))
    parser.add_argument("--port", type=int, default=env_int("WORLDCUP_WEB_PORT", env_int("PORT", 8765)))
    args = parser.parse_args(argv)

    server = ReusableThreadingHTTPServer((args.host, args.port), PredictorWebHandler)
    start_auto_settlement_worker()
    print(f"World Cup predictor web app: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def start_auto_settlement_worker() -> None:
    global _AUTO_SETTLEMENT_STARTED
    if not env_bool("WORLDCUP_AUTO_SETTLEMENT_ENABLED", True):
        return
    with _AUTO_SETTLEMENT_LOCK:
        if _AUTO_SETTLEMENT_STARTED:
            return
        _AUTO_SETTLEMENT_STARTED = True
    thread = threading.Thread(target=_auto_settlement_loop, name="paper-settlement", daemon=True)
    thread.start()


def _auto_settlement_loop() -> None:
    initial_delay = max(5, env_int("WORLDCUP_AUTO_SETTLEMENT_INITIAL_DELAY_SECONDS", 15))
    time.sleep(initial_delay)
    while True:
        run_auto_settlement_once(source="background")
        time.sleep(_auto_settlement_interval_seconds())


def run_auto_settlement_once(source: str = "background", force: bool = False) -> dict[str, Any]:
    global _AUTO_SETTLEMENT_LAST_RESULT, _AUTO_SETTLEMENT_LAST_RUN, _AUTO_SETTLEMENT_RUNNING
    if not env_bool("WORLDCUP_AUTO_SETTLEMENT_ENABLED", True):
        return {"ok": True, "source": source, "skipped": "disabled"}
    current = time.monotonic()
    with _AUTO_SETTLEMENT_LOCK:
        if _AUTO_SETTLEMENT_RUNNING:
            return {
                "ok": True,
                "source": source,
                "skipped": "already_running",
                "lastResult": _AUTO_SETTLEMENT_LAST_RESULT,
            }
        if not force and current - _AUTO_SETTLEMENT_LAST_RUN < _auto_settlement_interval_seconds():
            return {
                "ok": True,
                "source": source,
                "skipped": "interval",
                "lastResult": _AUTO_SETTLEMENT_LAST_RESULT,
            }
        _AUTO_SETTLEMENT_RUNNING = True
        _AUTO_SETTLEMENT_LAST_RUN = current
    result: dict[str, Any]
    try:
        sync_result = sync_completed_paper_ledger_results()
        paper_ledger = settle_open_paper_ledger()
        result = {
            "ok": True,
            "source": source,
            "syncedCount": len(sync_result.get("synced") or []),
            "awaitingCount": len(sync_result.get("awaitingCompletion") or []),
            "settledCount": int(paper_ledger.get("settledCount") or 0),
            "sync": sync_result,
            "paperLedger": paper_ledger,
        }
    except ApiFootballError as exc:
        try:
            paper_ledger = settle_open_paper_ledger()
        except Exception as ledger_exc:  # noqa: BLE001 - preserve the API error while reporting ledger failure.
            paper_ledger = {"settledCount": 0, "error": str(ledger_exc)}
        result = {
            "ok": False,
            "source": source,
            "error": str(exc),
            "errorKind": exc.kind,
            "settledCount": int(paper_ledger.get("settledCount") or 0),
            "paperLedger": paper_ledger,
        }
    except Exception as exc:  # noqa: BLE001 - background maintenance must not break page reads.
        result = {"ok": False, "source": source, "error": str(exc)}
    finally:
        with _AUTO_SETTLEMENT_LOCK:
            _AUTO_SETTLEMENT_LAST_RESULT = result
            _AUTO_SETTLEMENT_RUNNING = False
    return result


def _auto_settlement_interval_seconds() -> int:
    return max(60, env_int("WORLDCUP_AUTO_SETTLEMENT_INTERVAL_SECONDS", 300))


class PredictorWebHandler(BaseHTTPRequestHandler):
    server_version = "WorldCupPredictor/0.1"

    def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/healthz":
            self._send_json({"ok": True, "app": "worldcup-predictor"}, write_body=False)
            return
        if not self._authorize_request():
            return
        if path in {"/", "/index.html"}:
            self._serve_static(WEB_ROOT / "index.html", write_body=False)
            return
        static_path = (WEB_ROOT / path.lstrip("/")).resolve()
        if WEB_ROOT.resolve() not in static_path.parents and static_path != WEB_ROOT.resolve():
            self._send_error(HTTPStatus.FORBIDDEN, "Forbidden", write_body=False)
            return
        if static_path.exists() and static_path.is_file():
            self._serve_static(static_path, write_body=False)
            return
        self._send_error(HTTPStatus.NOT_FOUND, "Not found", write_body=False)

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
            self._send_json(model_validation_payload())
            return
        if path == "/api/live-readiness":
            self._send_json(build_live_readiness_status())
            return
        if path == "/api/paper-ledger":
            auto_settlement = run_auto_settlement_once(source="paper-ledger-view")
            book = build_paper_ledger_book()
            book["autoSettlement"] = auto_settlement
            self._send_json(book)
            return
        if path == "/api/daily-review":
            query = urllib.parse.parse_qs(parsed.query)
            date = (query.get("date") or [_today_shanghai()])[0]
            batch_id = _optional_int((query.get("batch_id") or [""])[0])
            self._send_json(build_daily_review(date=date, batch_id=batch_id))
            return
        if path == "/api/daily-review-report":
            query = urllib.parse.parse_qs(parsed.query)
            date = (query.get("date") or [_today_shanghai()])[0]
            batch_id = _optional_int((query.get("batch_id") or [""])[0])
            review = build_daily_review(date=date, batch_id=batch_id)
            self._send_file(
                build_daily_review_excel(review),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                f"worldcup_review_{date}.xlsx",
            )
            return
        if path == "/api/recent-predictions":
            self._send_json({"runs": recent_prediction_options()})
            return
        if path == "/api/recent-batches":
            self._send_json({"batches": recent_batch_options()})
            return
        if path == "/api/batch-run":
            query = urllib.parse.parse_qs(parsed.query)
            batch_id = _optional_int((query.get("batch_id") or [""])[0])
            if not batch_id:
                self._send_error(HTTPStatus.BAD_REQUEST, "Missing batch_id")
                return
            payload = get_batch_prediction_payload(batch_id)
            if not payload:
                self._send_error(HTTPStatus.NOT_FOUND, "Batch not found")
                return
            self._send_json(payload)
            return
        if path == "/api/prediction":
            query = urllib.parse.parse_qs(parsed.query)
            run_id = _optional_int((query.get("run_id") or [""])[0])
            if not run_id:
                self._send_error(HTTPStatus.BAD_REQUEST, "Missing run_id")
                return
            payload = get_prediction_payload(run_id)
            if not payload:
                self._send_error(HTTPStatus.NOT_FOUND, "Prediction not found")
                return
            self._send_json(_current_display_payload(payload))
            return
        if path == "/api/prediction-replay":
            query = urllib.parse.parse_qs(parsed.query)
            run_id = _optional_int((query.get("run_id") or [""])[0])
            if not run_id:
                self._send_error(HTTPStatus.BAD_REQUEST, "Missing run_id")
                return
            try:
                self._send_json(build_prediction_replay(run_id))
            except ValueError:
                self._send_error(HTTPStatus.NOT_FOUND, "Prediction not found")
            return
        if path == "/api/history-replay-ledger":
            query = urllib.parse.parse_qs(parsed.query)
            limit = _optional_int((query.get("limit") or [""])[0]) or 120
            bankroll = _optional_float((query.get("bankroll") or [""])[0]) or 1000.0
            self._send_json(build_history_replay_ledger(limit=limit, starting_bankroll=bankroll))
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
            payload = _current_display_payload(payload)
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
        if self.path not in {
            "/api/predict",
            "/api/random-today-predict",
            "/api/search-fixtures",
            "/api/today-fixtures",
            "/api/batch-predict",
            "/api/update-batch",
            "/api/mark-official-batch",
            "/api/sync-results",
            "/api/collect-odds-snapshot",
        }:
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
                sync_result["paperLedger"] = settle_open_paper_ledger()
                sync_result["modelValidation"] = model_validation_payload(force_refresh=True)
                self._send_json(sync_result)
                return
            if self.path == "/api/collect-odds-snapshot":
                fixture_ids = _parse_fixture_ids(payload.get("fixtureIds") or payload.get("fixtureId"))
                if not fixture_ids:
                    self._send_error(HTTPStatus.BAD_REQUEST, "Missing fixture_id")
                    return
                self._send_json(
                    collect_fixture_odds_snapshots(
                        fixture_ids,
                        api_key=_api_key_from_request(payload),
                        bookmaker_priority=payload.get("bookmakerPriority") or payload.get("bookmaker_priority"),
                    )
                )
                return
            if self.path == "/api/mark-official-batch":
                batch_id = _optional_int(payload.get("batchId") or payload.get("batch_id"))
                if not batch_id:
                    self._send_error(HTTPStatus.BAD_REQUEST, "Missing batch_id")
                    return
                updated = mark_official_batch(
                    batch_id,
                    official_date=str(payload.get("officialDate") or payload.get("date") or ""),
                )
                if not updated:
                    self._send_error(HTTPStatus.NOT_FOUND, "Batch not found")
                    return
                self._send_json({"ok": True, "batch": updated})
                return
            if self.path == "/api/update-batch":
                batch_id = _optional_int(payload.get("batchId") or payload.get("batch_id"))
                if not batch_id:
                    self._send_error(HTTPStatus.BAD_REQUEST, "Missing batch_id")
                    return
                updated = update_batch_metadata(
                    batch_id,
                    title=str(payload.get("title") or ""),
                    notes=str(payload.get("notes") or ""),
                )
                if not updated:
                    self._send_error(HTTPStatus.NOT_FOUND, "Batch not found")
                    return
                self._send_json({"ok": True, "batch": updated})
                return
            if self.path == "/api/batch-predict":
                batch_result = run_batch_prediction(payload)
                batch_result["batchRunId"] = record_batch_prediction(batch_result)
                self._send_json(batch_result)
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

    def _serve_static(self, path: Path, *, write_body: bool = True) -> None:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        if write_body:
            self.wfile.write(body)

    def _send_json(
        self,
        payload: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
        *,
        write_body: bool = True,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        if write_body:
            self.wfile.write(body)

    def _send_error(self, status: HTTPStatus, message: str, *, write_body: bool = True) -> None:
        self._send_json({"error": message}, status=status, write_body=write_body)

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


def run_web_prediction(payload: dict[str, Any], client: ApiFootballClient | None = None) -> dict[str, Any]:
    mode = str(payload.get("mode") or "sample")
    bankroll = as_float(payload.get("bankroll"), 1000.0)
    unit = _optional_float(payload.get("unit"))
    market_weight = clamp(as_float(payload.get("marketWeight"), 0.45), 0.0, 0.95)
    min_edge = clamp(as_float(payload.get("minEdge"), DEFAULT_MIN_EDGE), 0.0, 1.0)
    min_quality = clamp(as_float(payload.get("minQuality"), 0.60), 0.0, 1.0)
    force_picks = False

    if mode in {"auto", "historical", "historical_asof"}:
        home_value = str(payload.get("home") or "").strip()
        away_value = str(payload.get("away") or "").strip()
        fixture_id = _optional_int(payload.get("fixtureId"))
        historical_mode = mode in {"historical", "historical_asof"}
        staking_context = _paper_staking_context(
            starting_bankroll=bankroll,
            unit_stake=unit,
            enabled=not historical_mode and client is None,
        )
        if not fixture_id and (not home_value or not away_value):
            raise ValueError("API 模式需要填写两支球队，或填写 fixture_id。")
        if historical_mode and not fixture_id:
            raise ValueError("历史赛前模拟必须填写已知 fixture_id，防止匹配到错误赛程。")
        source = client or CachedApiFootballClient(api_key=_api_key_from_request(payload))
        validation = model_validation_payload()
        score_validation = validation.get("scoreDistributionValidation") or build_score_distribution_calibration_status()
        auto = run_auto_prediction(
            home_value,
            away_value,
            api_key=_api_key_from_request(payload),
            fixture_id=fixture_id,
            collection_mode=str(payload.get("collectionMode") or ""),
            market_weight=market_weight,
            bankroll=staking_context["currentBankroll"],
            unit_stake=unit,
            min_edge=min_edge,
            force_picks=force_picks,
            bookmaker_priority=payload.get("bookmakerPriority"),
            client=source,
            historical_as_of=(
                str(payload.get("historicalAsOf") or payload.get("historical_as_of") or "").strip()
                if historical_mode
                else None
            ),
            score_distribution_calibration=score_validation,
            starting_bankroll=staking_context["startingBankroll"],
            realized_pnl=staking_context["realizedPnl"],
            reserved_stake=staking_context["reservedStake"],
        )
        if staking_context.get("enabled"):
            auto.data_notes.append(str(staking_context["note"]))
        quality = build_data_quality_report(
            auto.market,
            fixture_id=auto.fixture_id,
            team_rating_score=1.0 if auto.recent_form_available else 0.25,
            context_score=0.75 if auto.league_id and auto.season and auto.kickoff else 0.45,
            lineup_score=0.30 if auto.deep_stats_available else 0.0,
            min_quality=min_quality,
            max_score=_quality_cap_for_recent_form(auto.recent_form_available, min_quality),
        )
        snapshot_id = None if historical_mode else _record_auto_snapshot(auto, "API-Football")
        recommendations, portfolio = apply_quality_gate(
            auto.recommendations,
            auto.portfolio,
            quality,
            enforce=True,
        )
        data_source = "历史赛前模拟（不进入正式验收）" if historical_mode else "API-Football"
        return {
            "mode": "historical_asof" if historical_mode else "auto",
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
                "dataSource": data_source,
                "snapshotId": snapshot_id,
                "historicalMode": historical_mode,
                "historicalAsOf": auto.historical_as_of or "",
                "historicalAsOfBeijing": to_beijing_time(auto.historical_as_of or ""),
                "leakageGuard": historical_mode,
                "requiredBookmaker": auto.market.required_bookmaker or "-",
                "bookmakerPriority": auto.market.bookmaker_priority,
                "selectedBookmakers": auto.market.selected_bookmakers,
                "bookmaker": auto.market.selected_bookmaker or "未取得",
                "oddsCapturedAt": auto.market.captured_at or "",
                "oddsCapturedAtBeijing": to_beijing_time(auto.market.captured_at or ""),
                "marketDatasetVersion": MARKET_DATASET_VERSION,
                "pbaseModelVersion": PBASE_MODEL_VERSION,
                "collectionMode": auto.collection_mode,
                "collectionModeZh": _collection_mode_zh(auto.collection_mode),
                "deepStatsMatches": auto.deep_stats_matches,
                "apiLogicalRequests": auto.api_logical_requests,
                "apiHttpAttempts": auto.api_http_attempts,
                "apiCacheHits": auto.api_cache_hits,
                "apiCacheMisses": auto.api_cache_misses,
                "recentMatchesHome": auto.home_recent_matches,
                "recentMatchesAway": auto.away_recent_matches,
                "recentMatchesRequired": MIN_VALID_RECENT_MATCHES,
                "recentMatchesRequested": RECENT_MATCH_FETCH_COUNT,
            },
            "snapshotId": snapshot_id,
            "modelValidation": validation,
            "dataProcessing": _data_processing_payload(auto),
            **_prediction_payload(
                auto.result,
                auto.market,
                recommendations,
                portfolio,
                auto.data_notes,
                quality,
                auto.governance,
                auto.risk_context,
                team_visuals=_team_visuals_from_auto(auto),
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


def _paper_staking_context(
    *,
    starting_bankroll: float,
    unit_stake: float | None,
    enabled: bool,
) -> dict[str, Any]:
    start = max(1.0, float(starting_bankroll or 1000.0))
    if not enabled or (unit_stake is not None and unit_stake > 0):
        return {
            "enabled": False,
            "startingBankroll": start,
            "currentBankroll": start,
            "realizedPnl": None,
            "reservedStake": 0.0,
            "note": "手动注额或隔离模式：不读取模拟舱滚动资金。",
        }

    summary = (build_paper_ledger_book(starting_bankroll=start).get("summary") or {})
    equity = _optional_float(summary.get("equity"))
    realized = _optional_float(summary.get("realizedPnl"))
    reserved = _optional_float(summary.get("reservedStake")) or 0.0
    cash = _optional_float(summary.get("cash"))
    current = equity if equity is not None else start
    return {
        "enabled": True,
        "startingBankroll": start,
        "currentBankroll": current,
        "realizedPnl": realized,
        "reservedStake": reserved,
        "note": (
            "模拟舱动态资金：按滚动权益 "
            f"{current:.2f}、可用现金 {(cash if cash is not None else max(0.0, current - reserved)):.2f}、"
            f"未结算预留 {reserved:.2f} 计算纸上注额；盈利仅 50% 纳入下一轮下注本金池。"
        ),
    }


def run_random_today_prediction(payload: dict[str, Any]) -> dict[str, Any]:
    bankroll = as_float(payload.get("bankroll"), 1000.0)
    unit = _optional_float(payload.get("unit"))
    market_weight = clamp(as_float(payload.get("marketWeight"), 0.45), 0.0, 0.95)
    min_edge = clamp(as_float(payload.get("minEdge"), DEFAULT_MIN_EDGE), 0.0, 1.0)
    min_quality = clamp(as_float(payload.get("minQuality"), 0.60), 0.0, 1.0)
    date = str(payload.get("date") or _today_shanghai())
    staking_context = _paper_staking_context(
        starting_bankroll=bankroll,
        unit_stake=unit,
        enabled=True,
    )

    client = CachedApiFootballClient(api_key=_api_key_from_request(payload))
    validation = model_validation_payload()
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
        collection_mode=str(payload.get("collectionMode") or ""),
        market_weight=market_weight,
        bankroll=staking_context["currentBankroll"],
        unit_stake=unit,
        min_edge=min_edge,
        force_picks=False,
        bookmaker_priority=payload.get("bookmakerPriority"),
        client=client,
        score_distribution_calibration=validation.get("scoreDistributionValidation"),
        starting_bankroll=staking_context["startingBankroll"],
        realized_pnl=staking_context["realizedPnl"],
        reserved_stake=staking_context["reservedStake"],
    )
    if staking_context.get("enabled"):
        auto.data_notes.append(str(staking_context["note"]))
    quality = build_data_quality_report(
        auto.market,
        fixture_id=auto.fixture_id,
        team_rating_score=1.0 if auto.recent_form_available else 0.25,
        context_score=0.75 if auto.league_id and auto.season and auto.kickoff else 0.45,
        lineup_score=0.30 if auto.deep_stats_available else 0.0,
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
            "bookmakerPriority": auto.market.bookmaker_priority,
            "selectedBookmakers": auto.market.selected_bookmakers,
            "bookmaker": auto.market.selected_bookmaker or "未取得",
            "oddsCapturedAt": auto.market.captured_at or "",
            "oddsCapturedAtBeijing": to_beijing_time(auto.market.captured_at or ""),
            "marketDatasetVersion": MARKET_DATASET_VERSION,
            "pbaseModelVersion": PBASE_MODEL_VERSION,
            "collectionMode": auto.collection_mode,
            "collectionModeZh": _collection_mode_zh(auto.collection_mode),
            "deepStatsMatches": auto.deep_stats_matches,
            "apiLogicalRequests": auto.api_logical_requests,
            "apiHttpAttempts": auto.api_http_attempts,
            "apiCacheHits": auto.api_cache_hits,
            "apiCacheMisses": auto.api_cache_misses,
            "recentMatchesHome": auto.home_recent_matches,
            "recentMatchesAway": auto.away_recent_matches,
            "recentMatchesRequired": MIN_VALID_RECENT_MATCHES,
            "recentMatchesRequested": RECENT_MATCH_FETCH_COUNT,
        },
        "snapshotId": snapshot_id,
        "modelValidation": validation,
        "dataProcessing": _data_processing_payload(auto),
        **_prediction_payload(
            auto.result,
            auto.market,
            recommendations,
            portfolio,
            auto.data_notes,
            quality,
            auto.governance,
            auto.risk_context,
            team_visuals=_team_visuals_from_auto(auto),
        ),
    }
    return result


def run_batch_prediction(payload: dict[str, Any]) -> dict[str, Any]:
    date = str(payload.get("date") or _today_shanghai())
    scope = str(payload.get("scope") or "first_division")
    requested_fixture_ids = _parse_fixture_ids(payload.get("fixtureIds") or payload.get("batchFixtureIds"))
    max_limit = max(30, env_int("WORLDCUP_WEB_BATCH_LIMIT", 30))
    default_limit = max(1, min(max_limit, env_int("WORLDCUP_WEB_BATCH_DEFAULT_LIMIT", 10)))
    requested_limit = _optional_int(payload.get("limit"))
    if requested_fixture_ids and requested_limit is None:
        requested_limit = len(requested_fixture_ids)
    limit = max(1, min(max_limit, requested_limit or default_limit))
    bankroll = as_float(payload.get("bankroll"), 1000.0)
    unit = _optional_float(payload.get("unit"))
    market_weight = clamp(as_float(payload.get("marketWeight"), 0.45), 0.0, 0.95)
    min_edge = clamp(as_float(payload.get("minEdge"), DEFAULT_MIN_EDGE), 0.0, 1.0)
    collection_mode = str(payload.get("collectionMode") or "batch")
    client = CachedApiFootballClient(api_key=_api_key_from_request(payload))
    failed: list[dict[str, Any]] = []
    if requested_fixture_ids:
        fixtures = []
        for fixture_id in requested_fixture_ids[:limit]:
            try:
                fixtures.append(client.fixture_by_id(fixture_id))
            except ApiFootballError as exc:
                failure = _classify_batch_failure(str(exc))
                failed.append(
                    {
                        "fixtureId": fixture_id,
                        "home": "主队",
                        "away": "客队",
                        "league": "-",
                        "kickoffBeijing": "-",
                        "failureType": failure["type"],
                        "failureLabel": failure["label"],
                        "error": str(exc),
                    }
                )
    else:
        fixtures = [
            item
            for item in client.fixtures_by_date(date)
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
        fixtures = sorted(fixtures, key=lambda item: str((item.get("fixture") or {}).get("date") or ""))[:limit]

    collected: list[dict[str, Any]] = []
    for row in fixtures:
        fixture = row.get("fixture") or {}
        teams = row.get("teams") or {}
        league = row.get("league") or {}
        fixture_id = _optional_int(fixture.get("id"))
        home = str((teams.get("home") or {}).get("name") or "")
        away = str((teams.get("away") or {}).get("name") or "")
        home_logo = _team_logo_from_teams(teams, "home")
        away_logo = _team_logo_from_teams(teams, "away")
        try:
            result = run_web_prediction(
                {
                    "mode": "auto",
                    "home": home,
                    "away": away,
                    "fixtureId": fixture_id,
                    "bankroll": bankroll,
                    "unit": unit,
                    "marketWeight": market_weight,
                    "minEdge": min_edge,
                    "collectionMode": collection_mode,
                    "bookmakerPriority": payload.get("bookmakerPriority"),
                },
                client=client,
            )
            run_id = record_prediction(result)
            result["runId"] = run_id
            collected.append(
                _batch_collected_item(
                    result,
                    run_id,
                    fixture_id,
                    home,
                    away,
                    league,
                    fixture,
                    bankroll,
                    home_logo=home_logo,
                    away_logo=away_logo,
                )
            )
        except (ApiFootballError, ValueError) as exc:
            failed.append(_batch_failed_item(fixture_id, home, away, league, fixture, exc, home_logo=home_logo, away_logo=away_logo))

    collected = sorted(collected, key=_batch_sort_key, reverse=True)

    return {
        "date": date,
        "scope": scope,
        "limit": limit,
        "requestedCount": len(requested_fixture_ids) if requested_fixture_ids else limit,
        "fixtureIds": requested_fixture_ids,
        "candidateFixtures": len(fixtures),
        "collectedCount": len(collected),
        "failedCount": len(failed),
        "batchSummary": _batch_summary(collected, failed, bankroll),
        "collected": collected,
        "failed": failed,
        "apiRequests": {
            "logical": client.logical_requests,
            "httpAttempts": client.http_attempts,
            "cacheHits": client.cache_hits,
            "cacheMisses": client.cache_misses,
        },
        "message": (
            f"指定比赛批量分析完成：成功 {len(collected)} 场，失败 {len(failed)} 场。"
            if requested_fixture_ids
            else f"{date} 批量分析完成：成功 {len(collected)} 场，失败 {len(failed)} 场。"
        ),
    }


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

    client = CachedApiFootballClient(api_key=api_key.strip() if api_key else None)
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
    source = client or CachedApiFootballClient(api_key=api_key)
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


def model_validation_payload(*, force_refresh: bool = False) -> dict[str, Any]:
    global _MODEL_VALIDATION_CACHE
    cache_seconds = max(0, env_int("WORLDCUP_MODEL_VALIDATION_CACHE_SECONDS", 300))
    now = time.monotonic()
    if (
        not force_refresh
        and cache_seconds > 0
        and _MODEL_VALIDATION_CACHE is not None
        and now - _MODEL_VALIDATION_CACHE[0] <= cache_seconds
    ):
        return copy.deepcopy(_MODEL_VALIDATION_CACHE[1])

    payload = build_model_validation_status()
    score_validation = build_score_distribution_calibration_status()
    payload["scoreDistributionValidation"] = score_validation
    payload["marketValidation"] = _market_validation_summary(payload, score_validation)
    if cache_seconds > 0:
        _MODEL_VALIDATION_CACHE = (now, copy.deepcopy(payload))
    return payload


def _market_validation_summary(
    outcome_validation: dict[str, Any],
    score_validation: dict[str, Any],
) -> dict[str, Any]:
    score_markets = score_validation.get("markets") or {}
    outcome_checks = outcome_validation.get("checks") or []
    return {
        "1X2": {
            "market": "1X2",
            "marketLabel": "胜平负",
            "probabilityObject": "pshr",
            "status": outcome_validation.get("status"),
            "statusLabel": outcome_validation.get("statusLabel"),
            "paperEvEnabled": False,
            "formalEvEnabled": False,
            "samples": outcome_validation.get("eligibleSamples") or 0,
            "distinctFixtures": outcome_validation.get("distinctFixtures") or 0,
            "split": outcome_validation.get("split") or {},
            "checks": outcome_checks,
            "failedChecks": [item for item in outcome_checks if not item.get("passed")],
            "metrics": outcome_validation.get("metrics") or {},
            "note": "胜平负只验收三分类概率；通过后仍需 pfinal 人工审批才可开放正式 EV。",
        },
        "OU": _score_market_validation_item(score_markets.get("OU") or {}),
        "AH": _score_market_validation_item(score_markets.get("AH") or {}),
    }


def _score_market_validation_item(market: dict[str, Any]) -> dict[str, Any]:
    checks = market.get("checks") or []
    return {
        "market": market.get("market"),
        "marketLabel": market.get("marketLabel"),
        "probabilityObject": "score_distribution",
        "status": market.get("status"),
        "statusLabel": market.get("statusLabel"),
        "paperEvEnabled": bool(market.get("paperEvEnabled")),
        "formalEvEnabled": False,
        "samples": market.get("sampleCount") or 0,
        "distinctFixtures": market.get("distinctFixtures") or 0,
        "split": market.get("split") or {},
        "checks": checks,
        "failedChecks": [item for item in checks if not item.get("passed")],
        "validation": market.get("validation") or {},
        "sides": market.get("sides") or {},
        "note": "大小球/让球按比分分布层单独验收；未通过时不应用失败校准因子。",
    }


def _current_display_payload(
    payload: dict[str, Any] | None,
    score_validation: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    return apply_current_score_validation_to_payload(
        payload,
        score_validation if score_validation is not None else model_validation_payload().get("scoreDistributionValidation"),
    )


def _api_key_from_request(payload: dict[str, Any]) -> str | None:
    if env_bool("WORLDCUP_PUBLIC_MODE", False):
        return None
    return str(payload.get("apiKey") or "").strip() or None


def recent_prediction_options(limit: int = 12) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    score_validation = model_validation_payload().get("scoreDistributionValidation")
    for item in recent_predictions(limit=limit):
        payload = _current_display_payload(
            get_prediction_payload(int(item["id"])) or {},
            score_validation=score_validation,
        ) or {}
        match = payload.get("match") or {}
        meta = payload.get("meta") or {}
        portfolio = payload.get("portfolio") or {}
        prediction = _history_prediction_summary(payload)
        recommendation = _history_recommendation_summary(payload)
        options.append(
            {
                **item,
                "homeZh": translate_team_display(match.get("home") or item.get("home_team"), "主队"),
                "awayZh": translate_team_display(match.get("away") or item.get("away_team"), "客队"),
                "homeLogo": match.get("homeLogo") or match.get("home_logo") or "",
                "awayLogo": match.get("awayLogo") or match.get("away_logo") or "",
                "leagueZh": translate_league_display(meta.get("leagueName"), meta.get("leagueCountry")),
                "kickoffBeijing": meta.get("kickoffBeijing") or to_beijing_time(meta.get("kickoff")),
                "predictionLabel": prediction["label"],
                "predictionProbability": prediction["probability"],
                "recommendationSummary": recommendation["summary"],
                "recommendationAction": recommendation["action"],
                "signalStatus": recommendation["action"],
                "bookmaker": meta.get("bookmaker") or "未取得",
                "qualityLabel": ((payload.get("dataQuality") or {}).get("gradeLabel") or "-"),
                "bankroll": portfolio.get("bankroll"),
                "totalStake": portfolio.get("total_stake"),
                "expectedBankroll": portfolio.get("expected_bankroll"),
                "expectedProfit": portfolio.get("expected_profit"),
            }
        )
    return options


def recent_batch_options(limit: int = 50) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    for item in recent_batch_predictions(limit=limit):
        title = str(item.get("title") or "").strip()
        notes = str(item.get("notes") or "").strip()
        fixture_ids = [
            value for value in str(item.get("fixture_ids") or "").split(",")
            if value.strip()
        ]
        fallback_label = f"批次 {item['id']} · 成功 {item.get('collected_count') or 0} 场 · 信号 {item.get('signal_count') or 0} 个"
        batches.append(
            {
                **item,
                "title": title,
                "notes": notes,
                "fixtureIds": fixture_ids,
                "isOfficial": bool(item.get("is_official")),
                "officialDate": item.get("official_date") or "",
                "label": title or fallback_label,
                "fallbackLabel": fallback_label,
                "scopeZh": "甲级联赛" if item.get("scope") == "first_division" else str(item.get("scope") or "-"),
            }
        )
    return batches


def _history_prediction_summary(payload: dict[str, Any]) -> dict[str, Any]:
    match = payload.get("match") or {}
    probabilities = payload.get("probabilities") or {}
    display = probabilities.get("display") or probabilities.get("final") or {}
    labels = {
        "home_win": f"{translate_team_display(match.get('home'), '主队')} 胜",
        "draw": "平局",
        "away_win": f"{translate_team_display(match.get('away'), '客队')} 胜",
    }
    candidates = [
        (key, float(display.get(key) or 0.0))
        for key in ("home_win", "draw", "away_win")
    ]
    key, probability = max(candidates, key=lambda item: item[1])
    return {"label": labels[key], "probability": probability}


def _history_recommendation_summary(payload: dict[str, Any]) -> dict[str, Any]:
    match = payload.get("match") or {}
    recommendations = payload.get("recommendations") or []
    active = [
        item for item in recommendations
        if isinstance(item, dict) and item.get("signal_status") == "PAPER_BUY"
    ]
    if active:
        item = active[0]
        selection = localize_selection(str(item.get("selection") or ""), str(match.get("home") or ""), str(match.get("away") or ""))
        return {"action": "PAPER_BUY", "summary": f"{item.get('market') or '-'}：{selection}"}
    suspended = [
        item for item in recommendations
        if isinstance(item, dict) and item.get("signal_status") == "SUSPENDED"
    ]
    if suspended:
        item = suspended[0]
        selection = localize_selection(str(item.get("selection") or ""), str(match.get("home") or ""), str(match.get("away") or ""))
        return {"action": "SUSPENDED", "summary": f"暂停：{item.get('market') or '-'} {selection}".strip()}
    model_candidates = [
        item for item in recommendations
        if isinstance(item, dict) and item.get("signal_status") == "MODEL_CANDIDATE"
    ]
    if model_candidates:
        item = model_candidates[0]
        selection = localize_selection(str(item.get("selection") or ""), str(match.get("home") or ""), str(match.get("away") or ""))
        return {"action": "MODEL_CANDIDATE", "summary": f"模型候选：{item.get('market') or '-'} {selection}".strip()}
    watch = [
        item for item in recommendations
        if isinstance(item, dict) and (item.get("signal_status") == "RESEARCH_WATCH" or item.get("action") == "WATCH")
    ]
    if watch:
        item = watch[0]
        selection = localize_selection(str(item.get("selection") or ""), str(match.get("home") or ""), str(match.get("away") or ""))
        return {"action": "RESEARCH_WATCH", "summary": f"研究观察：{item.get('market') or '-'} {selection}".strip()}
    no_market = [
        item for item in recommendations
        if isinstance(item, dict) and item.get("action") == "NO_MARKET"
    ]
    if no_market:
        return {"action": "NO_MARKET", "summary": "市场缺失"}
    return {"action": "-", "summary": "暂无方向"}


def _batch_collected_item(
    result: dict[str, Any],
    run_id: int,
    fixture_id: int | None,
    home: str,
    away: str,
    league: dict[str, Any],
    fixture: dict[str, Any],
    bankroll: float,
    home_logo: str = "",
    away_logo: str = "",
) -> dict[str, Any]:
    match = result.get("match") or {}
    meta = result.get("meta") or {}
    portfolio = result.get("portfolio") or {}
    quality = result.get("dataQuality") or {}
    prediction = _history_prediction_summary(result)
    recommendation = _batch_recommendation_summary(result)
    governance = result.get("modelGovernance") or {}
    market = result.get("market") or {}
    quality_score = _optional_float(quality.get("score"))
    markets = quality.get("markets") or []
    available_markets = sum(1 for item in markets if isinstance(item, dict) and item.get("status") == "available")
    return {
        "runId": run_id,
        "fixtureId": fixture_id,
        "home": match.get("homeZh") or translate_team_display(home, "主队"),
        "away": match.get("awayZh") or translate_team_display(away, "客队"),
        "homeLogo": match.get("homeLogo") or match.get("home_logo") or home_logo,
        "awayLogo": match.get("awayLogo") or match.get("away_logo") or away_logo,
        "league": meta.get("leagueNameZh") or translate_league_display(league.get("name"), league.get("country")),
        "kickoffBeijing": meta.get("kickoffBeijing") or to_beijing_time(fixture.get("date")),
        "bookmaker": meta.get("bookmaker") or "未取得",
        "selectedBookmakers": (market.get("selectedBookmakers") or meta.get("selectedBookmakers") or {}),
        "predictionLabel": prediction["label"],
        "predictionProbability": prediction["probability"],
        "recommendationAction": recommendation["action"],
        "recommendationSummary": recommendation["summary"],
        "recommendationMarket": recommendation["market"],
        "recommendationSelection": recommendation["selection"],
        "recommendationReason": recommendation["reason"],
        "odds": recommendation["odds"],
        "modelProbability": recommendation["modelProbability"],
        "modelProbabilityLabel": recommendation.get("modelProbabilityLabel") or "",
        "marketProbability": recommendation["marketProbability"],
        "expectedValue": recommendation["expectedValue"],
        "conservativeExpectedValue": recommendation["conservativeExpectedValue"],
        "evStatus": recommendation["evStatus"],
        "signalStatus": recommendation.get("signalStatus") or recommendation["action"],
        "evLayer": recommendation.get("evLayer") or "",
        "evPbaseResearch": recommendation.get("evPbaseResearch"),
        "evPfinalExec": recommendation.get("evPfinalExec"),
        "qualityScore": quality_score,
        "qualityLabel": quality.get("gradeLabel") or "-",
        "availableMarkets": available_markets,
        "totalMarkets": len(markets),
        "gateLabel": governance.get("gateLabel") or "",
        "activeBets": int(portfolio.get("active_bets") or 0),
        "unitStake": _optional_float(portfolio.get("unit_stake")),
        "totalStake": _optional_float(portfolio.get("total_stake")) or 0.0,
        "expectedProfit": _optional_float(portfolio.get("expected_profit")) or 0.0,
        "expectedBankroll": _optional_float(portfolio.get("expected_bankroll")) or bankroll,
    }


def _batch_recommendation_summary(payload: dict[str, Any]) -> dict[str, Any]:
    match = payload.get("match") or {}
    recommendations = [
        item for item in (payload.get("recommendations") or [])
        if isinstance(item, dict)
    ]
    if not recommendations:
        return _empty_batch_recommendation("暂无方向", "-")
    priority = {
        "PAPER_BUY": 5,
        "MODEL_CANDIDATE": 4,
        "SUSPENDED": 3,
        "RESEARCH_WATCH": 2,
        "NO_MARKET": 1,
        "BUY": 4,
        "WATCH": 2,
    }

    def score(item: dict[str, Any]) -> tuple[float, float, float, float]:
        conservative_ev = _optional_float(
            item.get("conservative_ev_pbase_research")
            if item.get("conservative_ev_pbase_research") is not None
            else item.get("conservative_expected_value_per_unit")
        )
        ev = _optional_float(
            item.get("ev_pbase_research")
            if item.get("ev_pbase_research") is not None
            else item.get("expected_value_per_unit")
        )
        model_probability = _optional_float(item.get("model_probability"))
        signal_status = str(item.get("signal_status") or item.get("action") or "")
        return (
            priority.get(signal_status, 0),
            conservative_ev if conservative_ev is not None else -99.0,
            ev if ev is not None else -99.0,
            model_probability if model_probability is not None else 0.0,
        )

    item = max(recommendations, key=score)
    action = str(item.get("signal_status") or item.get("action") or "-")
    market = str(item.get("market") or "-")
    selection = localize_selection(str(item.get("selection") or ""), str(match.get("home") or ""), str(match.get("away") or ""))
    if action == "NO_MARKET":
        summary = "市场缺失"
    elif action == "SUSPENDED":
        summary = f"暂停：{market} {selection}".strip()
    elif action in {"WATCH", "RESEARCH_WATCH"}:
        summary = f"研究观察：{market} {selection}".strip()
    elif action == "MODEL_CANDIDATE":
        summary = f"模型候选：{market} {selection}".strip()
    else:
        summary = f"{market}：{selection}"
    expected_value = _optional_float(
        item.get("ev_pbase_research")
        if item.get("ev_pbase_research") is not None
        else item.get("expected_value_per_unit")
    )
    conservative_value = _optional_float(
        item.get("conservative_ev_pbase_research")
        if item.get("conservative_ev_pbase_research") is not None
        else item.get("conservative_expected_value_per_unit")
    )
    return {
        "action": action,
        "summary": summary,
        "market": market,
        "selection": selection,
        "reason": str(item.get("reason") or ""),
        "odds": _optional_float(item.get("odds")),
        "modelProbability": _optional_float(item.get("model_probability")),
        "modelProbabilityLabel": str(item.get("model_probability_label") or ""),
        "marketProbability": _optional_float(item.get("market_probability")),
        "expectedValue": expected_value,
        "conservativeExpectedValue": conservative_value,
        "evStatus": str(item.get("ev_status") or ""),
        "signalStatus": action,
        "evLayer": str(item.get("ev_layer") or ""),
        "evPbaseResearch": _optional_float(item.get("ev_pbase_research")),
        "evPfinalExec": _optional_float(item.get("ev_pfinal_exec")),
    }


def _empty_batch_recommendation(summary: str, action: str) -> dict[str, Any]:
    return {
        "action": action,
        "summary": summary,
        "market": "-",
        "selection": "-",
        "reason": "",
        "odds": None,
        "modelProbability": None,
        "modelProbabilityLabel": "",
        "marketProbability": None,
        "expectedValue": None,
        "conservativeExpectedValue": None,
        "evStatus": "",
        "signalStatus": action,
        "evLayer": "",
        "evPbaseResearch": None,
        "evPfinalExec": None,
    }


def _batch_failed_item(
    fixture_id: int | None,
    home: str,
    away: str,
    league: dict[str, Any],
    fixture: dict[str, Any],
    exc: Exception,
    home_logo: str = "",
    away_logo: str = "",
) -> dict[str, Any]:
    failure = _classify_batch_failure(str(exc))
    return {
        "fixtureId": fixture_id,
        "home": translate_team_display(home, "主队"),
        "away": translate_team_display(away, "客队"),
        "homeLogo": home_logo,
        "awayLogo": away_logo,
        "league": translate_league_display(league.get("name"), league.get("country")),
        "kickoffBeijing": to_beijing_time(fixture.get("date")),
        "failureType": failure["type"],
        "failureLabel": failure["label"],
        "error": str(exc),
    }


def _classify_batch_failure(message: str) -> dict[str, str]:
    text = message.casefold()
    if any(keyword in text for keyword in ["已开赛", "完赛", "赛前", "kickoff", "started", "finished"]):
        return {"type": "NOT_PRE_MATCH", "label": "非赛前比赛"}
    if any(keyword in text for keyword in ["fixture", "id", "not found", "找不到", "无效"]):
        return {"type": "INVALID_FIXTURE", "label": "比赛 ID/赛程无效"}
    if any(keyword in text for keyword in ["赔率", "欧赔", "盘口", "odds", "market"]):
        return {"type": "NO_MARKET", "label": "盘口缺失"}
    if any(keyword in text for keyword in ["样本", "近期", "recent"]):
        return {"type": "INSUFFICIENT_SAMPLE", "label": "样本不足"}
    if any(keyword in text for keyword in ["api-football", "ssl", "timeout", "request", "连接"]):
        return {"type": "API_ERROR", "label": "API/网络异常"}
    return {"type": "PREDICTION_ERROR", "label": "分析失败"}


def _batch_sort_key(item: dict[str, Any]) -> tuple[float, float, float, float, float]:
    action_priority = {
        "PAPER_BUY": 5.0,
        "MODEL_CANDIDATE": 4.0,
        "SUSPENDED": 3.0,
        "RESEARCH_WATCH": 2.0,
        "BUY": 4.0,
        "WATCH": 2.0,
        "NO_MARKET": 1.0,
    }.get(
        str(item.get("signalStatus") or item.get("recommendationAction") or ""),
        0.0,
    )
    quality_score = _optional_float(item.get("qualityScore")) or 0.0
    conservative_ev = _optional_float(item.get("conservativeExpectedValue"))
    expected_ev = _optional_float(item.get("expectedValue"))
    prediction_probability = _optional_float(item.get("predictionProbability")) or 0.0
    return (
        action_priority,
        quality_score,
        conservative_ev if conservative_ev is not None else -99.0,
        expected_ev if expected_ev is not None else -99.0,
        prediction_probability,
    )


def _batch_summary(collected: list[dict[str, Any]], failed: list[dict[str, Any]], bankroll: float) -> dict[str, Any]:
    active = [item for item in collected if _is_batch_paper_buy(item)]
    watch = [item for item in collected if item.get("signalStatus") in {"RESEARCH_WATCH", "MODEL_CANDIDATE"}]
    no_market = [item for item in collected if item.get("signalStatus") == "NO_MARKET" or item.get("recommendationAction") == "NO_MARKET"]
    total_stake = sum(_optional_float(item.get("totalStake")) or 0.0 for item in collected)
    expected_profit = sum(_optional_float(item.get("expectedProfit")) or 0.0 for item in collected)
    high_quality = sum(1 for item in collected if (_optional_float(item.get("qualityScore")) or 0.0) >= 0.75)
    return {
        "total": len(collected) + len(failed),
        "success": len(collected),
        "failed": len(failed),
        "signalCount": len(active),
        "watchCount": len(watch),
        "noMarketCount": len(no_market),
        "highQualityCount": high_quality,
        "totalStake": total_stake,
        "expectedProfit": expected_profit,
        "expectedBankroll": bankroll + expected_profit,
        "bankrollMode": "批量内逐场独立评估，暂未按同批顺序扣减资金。",
        "portfolioPlan": _batch_portfolio_plan(collected, bankroll),
    }


def _batch_portfolio_plan(collected: list[dict[str, Any]], bankroll: float) -> dict[str, Any]:
    candidates = [
        item for item in collected
        if _is_batch_paper_buy(item)
        and (_optional_float(item.get("totalStake")) or 0.0) > 0
    ]
    stake_cap = max(0.0, bankroll * 0.5)
    used_stake = 0.0
    selected: list[dict[str, Any]] = []
    for item in sorted(candidates, key=_batch_sort_key, reverse=True):
        stake = _optional_float(item.get("totalStake")) or 0.0
        if stake_cap and used_stake + stake > stake_cap:
            continue
        used_stake += stake
        selected.append(item)

    expected_profit = sum(_optional_float(item.get("expectedProfit")) or 0.0 for item in selected)
    league_counts: dict[str, int] = {}
    market_counts: dict[str, int] = {}
    for item in selected:
        league = str(item.get("league") or "未知联赛")
        market = str(item.get("recommendationMarket") or "未知市场")
        league_counts[league] = league_counts.get(league, 0) + 1
        market_counts[market] = market_counts.get(market, 0) + 1

    warnings: list[str] = []
    if len(candidates) != len(selected):
        warnings.append(f"候选 {len(candidates)} 场中仅纳入 {len(selected)} 场，避免单批资金占用超过 50%。")
    crowded_leagues = [league for league, count in league_counts.items() if count >= 3]
    if crowded_leagues:
        league = crowded_leagues[0]
        warnings.append(f"同一联赛集中：{league} 达到 {league_counts[league]} 场，后续应降权。")
    crowded_markets = [market for market, count in market_counts.items() if count >= 3]
    if crowded_markets:
        market = crowded_markets[0]
        warnings.append(f"同一市场集中：{market} 达到 {market_counts[market]} 场，后续应控制暴露。")
    if not selected:
        warnings.append("本批次暂无通过研究信号和资金占用条件的组合候选。")

    return {
        "mode": "研究组合预案",
        "policy": "候选按推荐优先、质量、纸上 EV 排序；正式 EV 未开放时不产生资金占用。",
        "candidateCount": len(candidates),
        "selectedCount": len(selected),
        "stakeCap": stake_cap,
        "plannedStake": used_stake,
        "remainingStakeCap": max(0.0, stake_cap - used_stake),
        "expectedProfit": expected_profit,
        "expectedBankroll": bankroll + expected_profit,
        "selectedRunIds": [item.get("runId") for item in selected],
        "leagueExposure": league_counts,
        "marketExposure": market_counts,
        "warnings": warnings,
    }


def _is_batch_paper_buy(item: dict[str, Any]) -> bool:
    signal = str(item.get("signalStatus") or "")
    if signal:
        return signal == "PAPER_BUY"
    return str(item.get("recommendationAction") or "") in {"BUY", "PAPER_BUY"}


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


def _team_logo_from_teams(teams: dict[str, Any], side: str) -> str:
    return str(((teams.get(side) or {}).get("logo") or "")).strip()


def _team_visuals_from_fixture_row(row: dict[str, Any]) -> dict[str, str]:
    teams = row.get("teams") or {}
    return {
        "homeLogo": _team_logo_from_teams(teams, "home"),
        "awayLogo": _team_logo_from_teams(teams, "away"),
    }


def _team_visuals_from_auto(auto) -> dict[str, str]:
    snapshot = getattr(auto, "raw_snapshot", None) or {}
    return _team_visuals_from_fixture_row(snapshot.get("fixture") or {})


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
        "homeLogo": _team_logo_from_teams(teams, "home"),
        "awayLogo": _team_logo_from_teams(teams, "away"),
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
    risk_context = auto.risk_context or {}
    home = _form_series_payload(auto.result.home_team, "主队", recent_form.get("home") or [])
    away = _form_series_payload(auto.result.away_team, "客队", recent_form.get("away") or [])
    fixture_label = translate_league_display(auto.league_name, auto.league_country)
    odds_status = (
        f"已按优先级取得全场盘口：{_bookmaker_source_summary(auto.market)}"
        if auto.market.selected_bookmaker
        else "未取得庄家优先级内可用全场盘口"
    )
    return {
        "collectionMode": auto.collection_mode,
        "collectionModeZh": _collection_mode_zh(auto.collection_mode),
        "deepStatsMatches": auto.deep_stats_matches,
        "apiRequests": {
            "logical": auto.api_logical_requests,
            "httpAttempts": auto.api_http_attempts,
            "cacheHits": auto.api_cache_hits,
            "cacheMisses": auto.api_cache_misses,
        },
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
                "label": "补充深度统计",
                "status": "完成" if auto.deep_stats_matches else ("跳过" if auto.collection_mode == "fast" else "缺失"),
                "detail": (
                    f"{_collection_mode_zh(auto.collection_mode)}；技术统计/事件覆盖 "
                    f"{auto.deep_stats_matches} 场，逻辑请求 {auto.api_logical_requests} 次，"
                    f"实际 HTTP {auto.api_http_attempts} 次，缓存命中 {auto.api_cache_hits} 次。"
                ),
            },
            {
                "label": "抓取盘口",
                "status": "完成" if auto.market.selected_bookmaker else "缺失",
                "detail": odds_status,
            },
            {
                "label": "风险识别与 λ 收缩",
                "status": "已执行",
                "detail": (
                    f"λ shrink factor {float(risk_context.get('lambdaShrinkFactor') or 1.0):.2f}；"
                    + "、".join(str(item) for item in risk_context.get("lambdaShrinkReasons") or ["无额外风险"])
                ),
            },
            {
                "label": "模型与 EV 闸门",
                "status": "已执行",
                "detail": "生成 pbase、对照 qmkt、计算 p_adj / paper_EV，并检查盘口分歧、质量门槛与 formal_EV 准入状态。",
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
            "riskContext": risk_context,
        },
    }


def _bookmaker_source_summary(market: MarketSnapshot) -> str:
    if market.selected_bookmakers:
        labels = {"1X2": "胜平负", "OU": "大小球", "AH": "让球"}
        return "，".join(
            f"{labels.get(key, key)}={value}"
            for key, value in market.selected_bookmakers.items()
        )
    return market.selected_bookmaker or "未取得"


def _form_series_payload(team_name: str, role_label: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    chronological = sorted(rows, key=lambda item: str(item.get("date") or ""))
    points = sum(int(item.get("points") or 0) for item in chronological)
    goals_for = sum(int(item.get("goals_for") or 0) for item in chronological)
    goals_against = sum(int(item.get("goals_against") or 0) for item in chronological)
    count = len(chronological)
    ppg = points / count if count else 0.0
    gf_avg = goals_for / count if count else 0.0
    ga_avg = goals_against / count if count else 0.0
    xg_avg = _average_optional(chronological, "xg")
    shots_avg = _average_optional(chronological, "shots")
    shots_on_target_avg = _average_optional(chronological, "shots_on_target")
    possession_avg = _average_optional(chronological, "possession_pct")
    red_cards = sum(int(item.get("red_cards") or 0) for item in chronological)
    penalties = sum(int(item.get("penalties") or 0) for item in chronological)
    technical_count = sum(1 for item in chronological if item.get("technical_available"))
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
                "xg": item.get("xg"),
                "shots": item.get("shots"),
                "shotsOnTarget": item.get("shots_on_target"),
                "possessionPct": item.get("possession_pct"),
                "redCards": item.get("red_cards"),
                "penalties": item.get("penalties"),
                "technicalAvailable": bool(item.get("technical_available")),
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
        "xgAverage": xg_avg,
        "shotsAverage": shots_avg,
        "shotsOnTargetAverage": shots_on_target_avg,
        "possessionAverage": possession_avg,
        "redCards": red_cards,
        "penalties": penalties,
        "technicalCount": technical_count,
        "attackRating": attack_rating,
        "defenseRating": defense_rating,
        "estimatedElo": estimated_elo,
        "matches": matches,
    }


def _average_optional(rows: list[dict[str, Any]], key: str) -> float | None:
    values = []
    for row in rows:
        value = row.get(key)
        if value in {None, ""}:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return sum(values) / len(values) if values else None


def _collection_mode_zh(value: str) -> str:
    return {
        "fast": "快速模式",
        "deep": "深度模式",
        "batch": "批量建库模式",
    }.get(str(value or ""), "深度模式")


def _prediction_payload(
    result,
    market: MarketSnapshot,
    recommendations,
    portfolio,
    notes: list[str],
    data_quality,
    governance,
    risk_context: dict[str, Any] | None = None,
    team_visuals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    home_zh = translate_team_display(result.home_team, "主队")
    away_zh = translate_team_display(result.away_team, "客队")
    visuals = team_visuals or {}
    model_audit = build_distribution_audit(result, market)
    audit_notes = [str(model_audit["reason"])] if model_audit.get("evSuspended") else []
    return {
        "match": {
            "id": result.match_id,
            "home": result.home_team,
            "away": result.away_team,
            "homeZh": home_zh,
            "awayZh": away_zh,
            "homeLogo": str(visuals.get("homeLogo") or ""),
            "awayLogo": str(visuals.get("awayLogo") or ""),
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
        "liveReadiness": build_live_readiness_status(),
        "modelAudit": model_audit,
        "expectedGoals": {
            "home": result.expected_goals_home,
            "away": result.expected_goals_away,
            "baseHome": result.base_expected_goals_home,
            "baseAway": result.base_expected_goals_away,
            "rawHome": result.raw_expected_goals_home,
            "rawAway": result.raw_expected_goals_away,
            "logEdge": result.log_edge,
            "homeExpMultiplier": result.home_exp_multiplier,
            "awayExpMultiplier": result.away_exp_multiplier,
            "lambdaShrinkFactor": result.lambda_shrink_factor,
            "lambdaShrinkReasons": list(result.lambda_shrink_reasons or []),
            "scoreMatrixMaxGoals": result.score_matrix_max_goals,
            "scoreMatrixProbabilitySum": result.score_matrix_probability_sum,
            "scoreMatrixTailMass": result.score_matrix_tail_mass,
            "lambdaRiskFlags": list(result.lambda_risk_flags or []),
        },
        "riskContext": risk_context or {},
        "topScores": [{"score": score, "probability": probability} for score, probability in result.top_scores],
        "featureEdges": result.feature_edges,
        "market": _market_payload(market),
        "dataQuality": data_quality.to_dict(),
        "recommendations": [
            {
                **asdict(item),
                "selection": localize_selection(item.selection, result.home_team, result.away_team),
                "publicAction": _public_action(item),
                "publicActionLabel": _public_action_label(item),
                "formalExecutionEnabled": item.action == "BUY" and item.ev_pfinal_exec is not None,
                "paperSimulationEnabled": item.action == "PAPER_BUY" and item.stake > 0,
                "stakeStatusLabel": "资金占用已关闭" if item.stake <= 0 else "纸上资金占用",
                "evLayers": _ev_layers_for_recommendation(item),
            }
            for item in recommendations
        ],
        "portfolio": asdict(portfolio),
        "notes": [*audit_notes, *notes, *data_quality.notes, *governance.notes],
    }


def _ev_layers_for_recommendation(item) -> dict[str, Any]:
    calculation = getattr(item, "ev_calculation", None) or {}
    signal = str(getattr(item, "signal_status", "") or getattr(item, "action", "") or "")
    ev_status = str(getattr(item, "ev_status", "") or "")
    suspended = signal in {"SUSPENDED", "MODEL_MARKET_CONFLICT"} or "SUSPENDED" in ev_status
    score_research_only = calculation.get("evDecisionLayer") == "research_audit_only"
    research_value = _first_present(
        getattr(item, "ev_pbase_research", None),
        getattr(item, "audit_expected_value_per_unit", None),
        getattr(item, "expected_value_per_unit", None),
    )
    paper_value = _first_present(
        getattr(item, "paper_expected_value_per_unit", None),
        getattr(item, "ev_pshr_candidate", None),
        getattr(item, "conservative_ev_pbase_research", None),
        getattr(item, "audit_paper_expected_value_per_unit", None),
        getattr(item, "audit_conservative_expected_value_per_unit", None),
        getattr(item, "conservative_expected_value_per_unit", None),
    )
    formal_value = getattr(item, "ev_pfinal_exec", None)
    return {
        "research": {
            "key": "research",
            "label": "研究EV(pbase)",
            "value": research_value,
            "status": "paused" if suspended else "available" if research_value is not None else "missing",
            "statusLabel": "已暂停" if suspended else "可研究" if research_value is not None else "缺失",
            "probabilitySource": "pbase",
            "participatesInMoney": False,
        },
        "paper": {
            "key": "paper",
            "label": "纸上EV(p_adj/pshr)",
            "value": None if score_research_only else paper_value,
            "status": (
                "paused"
                if suspended
                else "not_open"
                if score_research_only
                else "candidate"
                if paper_value is not None
                else "missing"
            ),
            "statusLabel": (
                "已暂停"
                if suspended
                else "未开放"
                if score_research_only
                else "候选观察"
                if paper_value is not None
                else "缺失"
            ),
            "probabilitySource": "pshr_or_score_distribution",
            "participatesInMoney": False,
        },
        "formal": {
            "key": "formal",
            "label": "正式EV(pfinal)",
            "value": formal_value,
            "status": "enabled" if formal_value is not None and getattr(item, "action", "") == "BUY" else "closed",
            "statusLabel": "可执行" if formal_value is not None and getattr(item, "action", "") == "BUY" else "未开放",
            "probabilitySource": "pfinal",
            "participatesInMoney": bool(formal_value is not None and getattr(item, "action", "") == "BUY"),
        },
    }


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _public_action(item) -> str:
    signal = str(getattr(item, "signal_status", "") or getattr(item, "action", "") or "")
    if signal == "PAPER_BUY":
        return "PAPER_OBSERVATION"
    if signal in {"SUSPENDED", "MODEL_MARKET_CONFLICT"}:
        return "SUSPENDED"
    if signal == "NO_MARKET" or getattr(item, "action", "") == "NO_MARKET":
        return "NO_MARKET"
    if signal in {"MODEL_CANDIDATE", "BUY"}:
        return "MODEL_CANDIDATE"
    return "RESEARCH_OBSERVATION"


def _public_action_label(item) -> str:
    return {
        "PAPER_OBSERVATION": "纸上模拟",
        "SUSPENDED": "暂停复核",
        "NO_MARKET": "市场缺失",
        "MODEL_CANDIDATE": "模型候选（未执行）",
        "RESEARCH_OBSERVATION": "研究观察",
    }[_public_action(item)]


def _market_payload(market: MarketSnapshot) -> dict[str, Any]:
    total_line = market.best_total_line()
    handicap_line = market.best_handicap_line()
    return {
        "bookmakersCount": market.bookmakers_count,
        "availableBookmakersCount": market.available_bookmakers_count,
        "requiredBookmaker": market.required_bookmaker,
        "bookmakerPriority": market.bookmaker_priority,
        "selectedBookmaker": market.selected_bookmaker,
        "selectedBookmakers": market.selected_bookmakers,
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
        available_bookmakers_count=1,
        required_bookmaker="本地示例",
        bookmaker_priority=["本地示例"],
        selected_bookmaker="本地示例",
        selected_bookmakers={"1X2": "本地示例", "OU": "本地示例", "AH": "本地示例"},
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


def _parse_fixture_ids(value: Any) -> list[int]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_items = value
    else:
        if str(value).strip() == "":
            return []
        raw_items = str(value).replace("，", ",").replace("\n", ",").replace(" ", ",").split(",")
    fixture_ids: list[int] = []
    seen: set[int] = set()
    for raw in raw_items:
        fixture_id = _optional_int(raw)
        if fixture_id is None or fixture_id in seen:
            continue
        seen.add(fixture_id)
        fixture_ids.append(fixture_id)
    return fixture_ids


def _optional_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
