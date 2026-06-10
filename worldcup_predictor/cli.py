from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .api_football import ApiFootballError
from .auto_predict import run_auto_prediction
from .batch_collect import collect_daily_batch
from .betting import DEFAULT_MIN_EDGE
from .data import load_fixtures, load_teams
from .localization import (
    localize_selection,
    to_beijing_time,
    translate_league_display,
    translate_team_display,
)
from .models import ModelConfig, clamp
from .predictor import predict_match


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="worldcup-predict",
        description="Predict a football match with explainable team, market, context, and narrative factors.",
    )
    parser.add_argument("--auto", action="store_true", help="Fetch match data from API-Football by team names.")
    parser.add_argument("--batch-collect-today", action="store_true", help="Run daily batch collection for pre-match fixtures.")
    parser.add_argument("--home", help="Home/team A name for auto mode.")
    parser.add_argument("--away", help="Away/team B name for auto mode.")
    parser.add_argument("--fixture-id", type=int, help="API-Football fixture id. Optional but more precise.")
    parser.add_argument("--api-key", help="API-Football key. Defaults to API_FOOTBALL_KEY env var.")
    parser.add_argument(
        "--collection-mode",
        choices=["fast", "deep", "batch"],
        default="deep",
        help="API data collection mode. Default is deep for single-match analysis.",
    )
    parser.add_argument("--date", help="Batch collection date in Asia/Shanghai, for example 2026-05-28.")
    parser.add_argument("--scope", choices=["first_division", "all"], default="first_division", help="Batch collection fixture scope.")
    parser.add_argument("--limit", type=int, help="Batch collection fixture limit.")
    parser.add_argument("--teams", default="data/sample_teams.csv", help="Path to team ratings CSV.")
    parser.add_argument("--fixtures", default="data/sample_fixtures.csv", help="Path to fixtures CSV.")
    parser.add_argument("--match-id", help="Match id from the fixture CSV.")
    parser.add_argument(
        "--market-weight",
        type=float,
        default=0.45,
        help="How much to trust bookmaker odds after removing margin, from 0 to 0.95.",
    )
    parser.add_argument("--bankroll", type=float, default=1000.0, help="Paper bankroll for betting simulation.")
    parser.add_argument("--unit", type=float, help="Flat paper stake per selected market. Defaults to 1%% bankroll.")
    parser.add_argument(
        "--min-edge",
        type=float,
        default=DEFAULT_MIN_EDGE,
        help="Minimum model edge over market probability before a paper signal.",
    )
    parser.add_argument(
        "--force-picks",
        action="store_true",
        help="Force one paper pick per available market even without positive edge.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.batch_collect_today:
        try:
            batch = collect_daily_batch(
                date=args.date,
                scope=args.scope,
                limit=args.limit,
                collection_mode="batch" if args.collection_mode == "deep" else args.collection_mode,
                api_key=args.api_key,
            )
        except ApiFootballError as exc:
            parser.error(str(exc))
        if args.json:
            print(json.dumps(batch, ensure_ascii=False, indent=2))
        else:
            print(batch["message"])
            for item in batch["collected"]:
                print(f"- 运行 {item['runId']}: {item['home']} vs {item['away']} · {item['league']} · {item['kickoffBeijing']}")
        return 0

    if args.auto:
        if not args.home or not args.away:
            parser.error("--auto requires --home and --away.")
        try:
            auto_result = run_auto_prediction(
                args.home,
                args.away,
                api_key=args.api_key,
                fixture_id=args.fixture_id,
                collection_mode=args.collection_mode,
                market_weight=args.market_weight,
                bankroll=args.bankroll,
                unit_stake=args.unit,
                min_edge=args.min_edge,
                force_picks=args.force_picks,
            )
        except ApiFootballError as exc:
            parser.error(str(exc))
        if args.json:
            print(json.dumps(_auto_as_dict(auto_result), ensure_ascii=False, indent=2))
        else:
            print(format_auto_result(auto_result))
        return 0

    if not args.match_id:
        parser.error("CSV mode requires --match-id. Use --auto with --home and --away for API-Football mode.")

    teams = load_teams(args.teams)
    fixtures = load_fixtures(args.fixtures)
    if args.match_id not in fixtures:
        available = ", ".join(sorted(fixtures))
        parser.error(f"Unknown match id {args.match_id!r}. Available: {available}")

    fixture = fixtures[args.match_id]
    try:
        home = teams[fixture.home_team]
        away = teams[fixture.away_team]
    except KeyError as exc:
        parser.error(f"Fixture references a team missing from team CSV: {exc.args[0]}")

    config = ModelConfig(market_weight=clamp(args.market_weight, 0.0, 0.95))
    result = predict_match(home, away, fixture, config)

    if args.json:
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    else:
        print(format_result(result))
    return 0


def format_auto_result(auto_result) -> str:
    result = auto_result.result
    home = translate_team_display(result.home_team, "主队")
    away = translate_team_display(result.away_team, "客队")
    league = translate_league_display(auto_result.league_name, getattr(auto_result, "league_country", ""))
    kickoff = to_beijing_time(auto_result.kickoff) or auto_result.kickoff or "-"
    lines = [
        f"{result.match_id}: {home} vs {away}",
        f"赛事名称: {league or '-'}",
        f"开赛时间: {kickoff}",
        f"场地: {auto_result.venue or '-'}",
        "",
        format_result(result),
        "",
        "模拟舱",
        f"- 启动资金: {auto_result.portfolio.bankroll:.2f}",
        f"- 均注金额: {auto_result.portfolio.unit_stake:.2f}",
        f"- 本场模拟占用: {auto_result.portfolio.total_stake:.2f}",
        f"- 模拟期望收益: {auto_result.portfolio.expected_profit:.2f}",
        f"- 期望资金: {auto_result.portfolio.expected_bankroll:.2f}",
        f"- 正式 EV 状态: {auto_result.governance.gate_label}",
        "",
        "候选研究方向",
    ]
    for item in auto_result.recommendations:
        selection = localize_selection(item.selection, result.home_team, result.away_team)
        probability_label = item.model_probability_label or ("模型胜率" if item.market == "胜平负" else "正收益概率")
        lines.append(
            "- "
            + f"{item.market}: {selection} | 动作: {_action_label(item.action)} | "
            + f"赔率: {_odd(item.odds)} | {probability_label}: {_pct(item.model_probability)} | "
            + f"市场: {_pct_or_dash(item.market_probability)} | "
            + f"优势: {_pct_or_dash(item.edge)} | 研究试算EV/注: {_ev(item.expected_value_per_unit)} | "
            + f"纸上EV: {_ev(item.paper_expected_value_per_unit)} | "
            + item.reason
        )
        if item.ev_status in {"SUSPENDED_MODEL_DIVERGENCE", "MODEL_MARKET_CONFLICT", "SUSPENDED"}:
            lines.append(
                "  审计原始试算（不构成信号）: "
                + f"EV/注 {_ev(item.audit_expected_value_per_unit)} | "
                + f"纸上EV {_ev(item.audit_paper_expected_value_per_unit)}"
            )
    if auto_result.data_notes:
        lines.extend(["", "数据提示"])
        lines.extend(f"- {note}" for note in auto_result.data_notes)
    lines.extend(
        [
            "",
            "说明: 当前 pshr/pfinal 尚未完成校准验证，API 模式仅保留研究试算 EV 供复核，不连接真实投注账户，也不保证收益。",
        ]
    )
    return "\n".join(lines)


def format_result(result) -> str:
    final = result.final_probabilities
    model = result.model_probabilities
    market = result.market_probabilities
    home = translate_team_display(result.home_team, "主队")
    away = translate_team_display(result.away_team, "客队")

    lines = [
        f"{result.match_id}: {home} vs {away}",
        "",
        "展示融合概率（非 pfinal）",
        f"- {home} 胜: {_pct(final['home_win'])}",
        f"- 平局: {_pct(final['draw'])}",
        f"- {away} 胜: {_pct(final['away_win'])}",
        "",
        "pbase 基础概率",
        f"- {home} 胜: {_pct(model['home_win'])}",
        f"- 平局: {_pct(model['draw'])}",
        f"- {away} 胜: {_pct(model['away_win'])}",
        "",
        "预期进球",
        f"- {home}: {result.expected_goals_home:.2f}",
        f"- {away}: {result.expected_goals_away:.2f}",
        "",
        "最可能比分",
        "- " + ", ".join(f"{score} ({_pct(prob)})" for score, prob in result.top_scores[:6]),
    ]
    if market:
        lines.extend(
            [
                "",
                "qmkt 市场去水概率",
                f"- {home} 胜: {_pct(market['home_win'])}",
                f"- 平局: {_pct(market['draw'])}",
                f"- {away} 胜: {_pct(market['away_win'])}",
            ]
        )
    if result.notes:
        lines.extend(["", f"备注: {result.notes}"])
    lines.extend(
        [
            "",
            "重要提醒: 国家关系和商业收益是低权重情景变量，只适合表达假设，不应被当成已经发生的操盘证据。",
        ]
    )
    return "\n".join(lines)


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _pct_or_dash(value: float | None) -> str:
    if value is None:
        return "-"
    return _pct(value)


def _odd(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def _ev(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def _action_label(value: str) -> str:
    return {
        "BUY": "模型候选（未执行）",
        "PAPER_BUY": "纸上观察",
        "WATCH": "观望",
        "NO_MARKET": "市场缺失",
        "MODEL_CANDIDATE": "模型候选（未执行）",
        "RESEARCH_WATCH": "研究观察",
        "SUSPENDED": "暂停复核",
    }.get(value, value or "-")


def _auto_as_dict(auto_result) -> dict:
    result_dict = asdict(auto_result.result)
    return {
        "fixture_id": auto_result.fixture_id,
        "league_id": auto_result.league_id,
        "league_name": auto_result.league_name,
        "league_name_zh": translate_league_display(auto_result.league_name, getattr(auto_result, "league_country", "")),
        "season": auto_result.season,
        "kickoff": auto_result.kickoff,
        "kickoff_beijing": to_beijing_time(auto_result.kickoff),
        "venue": auto_result.venue,
        "prediction": result_dict,
        "market": asdict(auto_result.market),
        "recommendations": [asdict(item) for item in auto_result.recommendations],
        "paper_portfolio": asdict(auto_result.portfolio),
        "model_governance": auto_result.governance.to_dict(),
        "data_notes": list(auto_result.data_notes),
    }
