from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BankrollPlan:
    starting_bankroll: float
    current_bankroll: float
    parts: int
    profit_reinvest_rate: float
    available_for_unit: float
    unit_stake: float
    max_match_exposure: float
    realized_pnl: float = 0.0
    reserved_stake: float = 0.0
    cash: float = 0.0
    staking_bankroll: float = 0.0
    max_daily_exposure: float = 0.0
    max_market_exposure: float = 0.0
    max_league_exposure: float = 0.0
    max_longshot_exposure: float = 0.0
    risk_mode: str = "research_locked"


def dynamic_unit_stake(
    current_bankroll: float,
    *,
    starting_bankroll: float = 1000.0,
    parts: int = 5,
    profit_reinvest_rate: float = 0.50,
    max_match_exposure_rate: float = 0.40,
    realized_pnl: float | None = None,
    reserved_stake: float = 0.0,
    max_daily_exposure_rate: float = 0.60,
    max_market_exposure_rate: float = 0.25,
    max_league_exposure_rate: float = 0.30,
    max_longshot_exposure_rate: float = 0.10,
) -> BankrollPlan:
    bankroll = max(0.0, float(current_bankroll or 0.0))
    start = max(1.0, float(starting_bankroll or 1000.0))
    parts = max(1, int(parts or 5))
    reinvest = min(max(float(profit_reinvest_rate), 0.0), 1.0)
    exposure_rate = min(max(float(max_match_exposure_rate), 0.0), 1.0)
    reserved = min(max(float(reserved_stake or 0.0), 0.0), bankroll)
    cash = max(0.0, bankroll - reserved)
    pnl = float(realized_pnl) if realized_pnl is not None else bankroll - start
    daily_rate = min(max(float(max_daily_exposure_rate), 0.0), 1.0)
    market_rate = min(max(float(max_market_exposure_rate), 0.0), 1.0)
    league_rate = min(max(float(max_league_exposure_rate), 0.0), 1.0)
    longshot_rate = min(max(float(max_longshot_exposure_rate), 0.0), 1.0)

    if bankroll >= start:
        profit = bankroll - start
        available = start + profit * reinvest
    else:
        available = bankroll

    staking_bankroll = min(available, cash)
    unit = max(0.0, min(staking_bankroll / parts, cash))
    max_exposure = cash * exposure_rate
    unit = min(unit, max_exposure)
    return BankrollPlan(
        starting_bankroll=start,
        current_bankroll=bankroll,
        parts=parts,
        profit_reinvest_rate=reinvest,
        available_for_unit=available,
        unit_stake=unit,
        max_match_exposure=max_exposure,
        realized_pnl=pnl,
        reserved_stake=reserved,
        cash=cash,
        staking_bankroll=staking_bankroll,
        max_daily_exposure=cash * daily_rate,
        max_market_exposure=cash * market_rate,
        max_league_exposure=cash * league_rate,
        max_longshot_exposure=cash * longshot_rate,
    )
