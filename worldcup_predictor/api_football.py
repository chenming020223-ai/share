from __future__ import annotations

import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from http.client import RemoteDisconnected
from dataclasses import dataclass
from typing import Any

from .settings import env_int, load_dotenv


class ApiFootballError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        kind: str = "api",
        retryable: bool = False,
        status_code: int | None = None,
        details: str = "",
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.status_code = status_code
        self.details = details


@dataclass(frozen=True)
class ApiTeam:
    id: int
    name: str
    country: str = ""
    national: bool = False


class ApiFootballClient:
    """Small API-Football client using only the Python standard library."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://v3.football.api-sports.io",
        timeout: int = 20,
        retries: int | None = None,
    ) -> None:
        load_dotenv()
        self.api_key = api_key or os.getenv("API_FOOTBALL_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = max(0, retries if retries is not None else env_int("API_FOOTBALL_RETRIES", 3))
        self.ssl_context = _build_ssl_context()
        self.logical_requests = 0
        self.http_attempts = 0
        if not self.api_key:
            raise ApiFootballError(
                "缺少 API-Football 密钥。请在页面填写 API Key，或在本地 .env 设置 API_FOOTBALL_KEY。",
                kind="auth",
            )

    def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.logical_requests += 1
        query = urllib.parse.urlencode(
            {key: value for key, value in (params or {}).items() if value is not None}
        )
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        if query:
            url = f"{url}?{query}"

        payload = self._open_with_retry(url)

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ApiFootballError(
                "API-Football 返回了非 JSON 响应。请稍后重试，或检查网络代理是否改写了接口响应。",
                kind="api",
                retryable=True,
                details=payload[:500],
            ) from exc
        errors = data.get("errors")
        if errors:
            raise _api_response_error(errors)
        return data

    def _open_with_retry(self, url: str) -> str:
        last_error: BaseException | None = None
        attempts = self.retries + 1
        for attempt in range(1, attempts + 1):
            self.http_attempts += 1
            request = urllib.request.Request(
                url,
                headers={
                    "x-apisports-key": self.api_key,
                    "accept": "application/json",
                    "user-agent": "WorldCupPredictor/1.0",
                    "connection": "close",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout, context=self.ssl_context) as response:
                    return response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                last_error = exc
                if not _is_retryable_http(exc.code) or attempt >= attempts:
                    body = exc.read().decode("utf-8", errors="replace")
                    raise _http_error(exc.code, body) from exc
            except (urllib.error.URLError, ssl.SSLError, TimeoutError, socket.timeout, RemoteDisconnected) as exc:
                last_error = exc
                if _is_certificate_error(exc) or not _is_retryable_transport_error(exc) or attempt >= attempts:
                    raise _transport_error(exc, self.retries) from exc

            time.sleep(min(0.4 * attempt, 1.6))

        raise _transport_error(last_error or RuntimeError("unknown API transport error"), self.retries)

    def search_team(self, name: str) -> list[ApiTeam]:
        data = self.get("teams", {"search": name})
        teams: list[ApiTeam] = []
        for row in data.get("response", []):
            team = row.get("team", {})
            team_id = team.get("id")
            if team_id is None:
                continue
            teams.append(
                ApiTeam(
                    id=int(team_id),
                    name=str(team.get("name") or ""),
                    country=str(team.get("country") or ""),
                    national=bool(team.get("national")),
                )
            )
        return teams

    def resolve_team(self, name: str) -> ApiTeam:
        teams = self.search_team(name)
        if not teams:
            raise ApiFootballError(f"No API-Football team found for {name!r}.")

        normalized = name.casefold().strip()
        exact = [team for team in teams if team.name.casefold() == normalized]
        if exact:
            national_exact = [team for team in exact if team.national]
            return national_exact[0] if national_exact else exact[0]

        national = [team for team in teams if team.national]
        return national[0] if national else teams[0]

    def fixture_by_id(self, fixture_id: int) -> dict[str, Any]:
        data = self.get("fixtures", {"id": fixture_id})
        response = data.get("response", [])
        if not response:
            raise ApiFootballError(f"API-Football 未找到 fixture_id={fixture_id} 的比赛。")
        return response[0]

    def fixtures(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        data = self.get("fixtures", params)
        return list(data.get("response", []))

    def fixtures_by_date(self, date: str, timezone: str = "Asia/Shanghai") -> list[dict[str, Any]]:
        return self.fixtures({"date": date, "timezone": timezone})

    def team_next_fixtures(self, team_id: int, limit: int = 30, timezone: str = "Asia/Shanghai") -> list[dict[str, Any]]:
        return self.fixtures({"team": team_id, "next": limit, "timezone": timezone})

    def next_head_to_head_candidates(self, home_id: int, away_id: int, limit: int = 10) -> list[dict[str, Any]]:
        data = self.get("fixtures/headtohead", {"h2h": f"{home_id}-{away_id}", "next": limit})
        return list(data.get("response", []))

    def next_head_to_head(self, home_id: int, away_id: int, limit: int = 10) -> dict[str, Any]:
        response = self.next_head_to_head_candidates(home_id, away_id, limit)
        if response:
            return response[0]
        raise ApiFootballError(
            "API-Football 未找到两队已排定的未来直接交锋。请点击“搜索比赛”选择可用赛程，或填写已知 fixture_id。"
        )

    def last_head_to_head(self, team_a_id: int, team_b_id: int, limit: int = 10) -> list[dict[str, Any]]:
        data = self.get("fixtures/headtohead", {"h2h": f"{team_a_id}-{team_b_id}", "last": limit})
        return list(data.get("response", []))

    def team_last_fixtures(self, team_id: int, limit: int = 10, timezone: str = "Asia/Shanghai") -> list[dict[str, Any]]:
        return self.fixtures({"team": team_id, "last": limit, "timezone": timezone})

    def team_finished_fixtures_until(
        self,
        team_id: int,
        to_date: str,
        limit: int = 30,
        timezone: str = "Asia/Shanghai",
    ) -> list[dict[str, Any]]:
        rows = self.fixtures({"team": team_id, "to": to_date, "timezone": timezone})
        return sorted(
            rows,
            key=lambda item: str(((item.get("fixture") or {}).get("date") or "")),
            reverse=True,
        )[:limit]

    def odds(self, fixture_id: int) -> list[dict[str, Any]]:
        data = self.get("odds", {"fixture": fixture_id})
        return list(data.get("response", []))

    def predictions(self, fixture_id: int) -> list[dict[str, Any]]:
        data = self.get("predictions", {"fixture": fixture_id})
        return list(data.get("response", []))

    def team_statistics(self, league_id: int, season: int, team_id: int) -> dict[str, Any] | None:
        data = self.get("teams/statistics", {"league": league_id, "season": season, "team": team_id})
        response = data.get("response")
        return response if isinstance(response, dict) else None

    def fixture_statistics(self, fixture_id: int) -> list[dict[str, Any]]:
        data = self.get("fixtures/statistics", {"fixture": fixture_id})
        return list(data.get("response", []))

    def fixture_events(self, fixture_id: int) -> list[dict[str, Any]]:
        data = self.get("fixtures/events", {"fixture": fixture_id})
        return list(data.get("response", []))

    def fixture_lineups(self, fixture_id: int) -> list[dict[str, Any]]:
        data = self.get("fixtures/lineups", {"fixture": fixture_id})
        return list(data.get("response", []))

    def injuries(self, fixture_id: int) -> list[dict[str, Any]]:
        data = self.get("injuries", {"fixture": fixture_id})
        return list(data.get("response", []))

    def status(self) -> dict[str, Any]:
        return self.get("status")


def _build_ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _is_certificate_error(exc: BaseException) -> bool:
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return True
    return "CERTIFICATE_VERIFY_FAILED" in str(reason)


def _is_retryable_http(status_code: int) -> bool:
    return status_code in {408, 425, 429, 500, 502, 503, 504}


def _is_retryable_transport_error(exc: BaseException) -> bool:
    text = str(getattr(exc, "reason", exc)).casefold()
    retry_tokens = [
        "eof",
        "timed out",
        "timeout",
        "connection reset",
        "remote end closed",
        "temporarily unavailable",
        "protocol",
        "unexpected_eof",
        "ssl",
    ]
    return isinstance(exc, (TimeoutError, socket.timeout, RemoteDisconnected, ssl.SSLError)) or any(
        token in text for token in retry_tokens
    )


def _http_error(status_code: int, body: str) -> ApiFootballError:
    if status_code in {401, 403}:
        return ApiFootballError(
            "API-Football 鉴权失败。请检查 API Key 是否正确、是否仍有效。",
            kind="auth",
            status_code=status_code,
            details=body,
        )
    if status_code == 429:
        return ApiFootballError(
            "API-Football 请求过于频繁或额度已用尽。请稍后重试，或检查 API 套餐额度。",
            kind="rate_limit",
            retryable=True,
            status_code=status_code,
            details=body,
        )
    if _is_retryable_http(status_code):
        return ApiFootballError(
            f"API-Football 服务暂时不可用，HTTP {status_code}。系统已自动重试但仍失败，请稍后再试。",
            kind="network",
            retryable=True,
            status_code=status_code,
            details=body,
        )
    return ApiFootballError(
        f"API-Football 返回 HTTP {status_code}。请稍后重试，或检查请求参数。",
        kind="api",
        status_code=status_code,
        details=body,
    )


def _transport_error(exc: BaseException, retries: int) -> ApiFootballError:
    if _is_certificate_error(exc):
        return ApiFootballError(
            "API-Football HTTPS 证书验证失败。请重启本地服务；如果仍失败，请检查 Python 证书或重新安装 certifi。",
            kind="certificate",
            details=str(getattr(exc, "reason", exc)),
        )
    reason = str(getattr(exc, "reason", exc))
    if _is_retryable_transport_error(exc):
        return ApiFootballError(
            f"API-Football 连接被中断，已自动重试 {retries} 次仍失败。请稍后重试，或检查网络、VPN、代理、防火墙。",
            kind="network",
            retryable=True,
            details=reason,
        )
    return ApiFootballError(
        f"API-Football 网络请求失败：{reason}",
        kind="network",
        retryable=True,
        details=reason,
    )


def _api_response_error(errors: Any) -> ApiFootballError:
    text = str(errors)
    lower = text.casefold()
    if "key" in lower or "token" in lower or "account" in lower:
        return ApiFootballError(
            "API-Football 返回密钥或账户错误。请检查 API Key、套餐权限和剩余额度。",
            kind="auth",
            details=text,
        )
    if "rate" in lower or "limit" in lower or "requests" in lower:
        return ApiFootballError(
            "API-Football 返回请求额度或频率限制。请稍后重试，或检查套餐额度。",
            kind="rate_limit",
            retryable=True,
            details=text,
        )
    return ApiFootballError(
        f"API-Football 返回业务错误：{errors}",
        kind="api",
        details=text,
    )
