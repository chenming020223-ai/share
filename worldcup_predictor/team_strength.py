from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .models import TeamProfile, clamp


@dataclass(frozen=True)
class TeamStrengthPrior:
    canonical_name: str
    elo: float
    fifa_rank: float
    attack_rating: float
    defense_rating: float
    source: str = "internal_strength_prior_v1"


_TEAM_PRIORS: dict[str, TeamStrengthPrior] = {
    # World Cup level anchors.
    "argentina": TeamStrengthPrior("Argentina", 1870, 1, 1.40, 1.36),
    "france": TeamStrengthPrior("France", 1860, 2, 1.40, 1.34),
    "spain": TeamStrengthPrior("Spain", 1840, 3, 1.35, 1.33),
    "england": TeamStrengthPrior("England", 1835, 4, 1.34, 1.32),
    "brazil": TeamStrengthPrior("Brazil", 1830, 5, 1.36, 1.30),
    "portugal": TeamStrengthPrior("Portugal", 1815, 6, 1.33, 1.29),
    "netherlands": TeamStrengthPrior("Netherlands", 1805, 7, 1.30, 1.30),
    "belgium": TeamStrengthPrior("Belgium", 1785, 8, 1.28, 1.25),
    "italy": TeamStrengthPrior("Italy", 1780, 9, 1.24, 1.31),
    "germany": TeamStrengthPrior("Germany", 1775, 10, 1.30, 1.24),
    "croatia": TeamStrengthPrior("Croatia", 1750, 12, 1.18, 1.22),
    "mexico": TeamStrengthPrior("Mexico", 1715, 16, 1.14, 1.16),
    "united states": TeamStrengthPrior("United States", 1720, 15, 1.15, 1.16),
    "usa": TeamStrengthPrior("United States", 1720, 15, 1.15, 1.16),
    "canada": TeamStrengthPrior("Canada", 1660, 31, 1.07, 1.04),
    "uruguay": TeamStrengthPrior("Uruguay", 1780, 11, 1.22, 1.25),
    "colombia": TeamStrengthPrior("Colombia", 1760, 13, 1.20, 1.22),
    "japan": TeamStrengthPrior("Japan", 1725, 17, 1.13, 1.17),
    "korea republic": TeamStrengthPrior("Korea Republic", 1690, 23, 1.09, 1.10),
    "south korea": TeamStrengthPrior("Korea Republic", 1690, 23, 1.09, 1.10),
    "morocco": TeamStrengthPrior("Morocco", 1710, 14, 1.10, 1.18),
    "senegal": TeamStrengthPrior("Senegal", 1685, 20, 1.07, 1.12),
    "australia": TeamStrengthPrior("Australia", 1650, 28, 1.04, 1.08),
    "switzerland": TeamStrengthPrior("Switzerland", 1700, 18, 1.09, 1.13),
    "denmark": TeamStrengthPrior("Denmark", 1695, 19, 1.08, 1.14),
    "austria": TeamStrengthPrior("Austria", 1690, 22, 1.10, 1.10),
    "turkey": TeamStrengthPrior("Turkey", 1665, 26, 1.08, 1.05),
    "poland": TeamStrengthPrior("Poland", 1645, 30, 1.05, 1.04),
    "ukraine": TeamStrengthPrior("Ukraine", 1660, 27, 1.06, 1.07),
    "serbia": TeamStrengthPrior("Serbia", 1655, 29, 1.08, 1.03),
    "wales": TeamStrengthPrior("Wales", 1605, 38, 0.99, 1.03),
    "scotland": TeamStrengthPrior("Scotland", 1615, 36, 1.00, 1.05),
    "ireland": TeamStrengthPrior("Ireland", 1580, 55, 0.96, 0.99),
    "northern ireland": TeamStrengthPrior("Northern Ireland", 1545, 72, 0.91, 0.96),
    "norway": TeamStrengthPrior("Norway", 1625, 35, 1.08, 0.99),
    "sweden": TeamStrengthPrior("Sweden", 1630, 34, 1.01, 1.07),
    "russia": TeamStrengthPrior("Russia", 1580, 60, 0.98, 0.99),
    "czech republic": TeamStrengthPrior("Czech Republic", 1635, 33, 1.02, 1.06),
    "romania": TeamStrengthPrior("Romania", 1605, 43, 0.99, 1.03),
    "hungary": TeamStrengthPrior("Hungary", 1650, 32, 1.03, 1.08),
    "slovakia": TeamStrengthPrior("Slovakia", 1595, 45, 0.97, 1.02),
    "slovenia": TeamStrengthPrior("Slovenia", 1600, 44, 0.98, 1.03),
    "albania": TeamStrengthPrior("Albania", 1565, 62, 0.93, 1.00),
    "bosnia and herzegovina": TeamStrengthPrior("Bosnia and Herzegovina", 1550, 70, 0.94, 0.97),
    "finland": TeamStrengthPrior("Finland", 1545, 69, 0.92, 0.99),
    "iceland": TeamStrengthPrior("Iceland", 1535, 73, 0.91, 0.98),
    "greece": TeamStrengthPrior("Greece", 1605, 42, 0.97, 1.05),
    "israel": TeamStrengthPrior("Israel", 1575, 58, 0.96, 0.98),
    # Mid and lower international anchors used to stop recent-form overfitting.
    "kosovo": TeamStrengthPrior("Kosovo", 1535, 94, 0.92, 0.95),
    "luxembourg": TeamStrengthPrior("Luxembourg", 1505, 87, 0.90, 0.94),
    "belarus": TeamStrengthPrior("Belarus", 1495, 98, 0.89, 0.93),
    "kazakhstan": TeamStrengthPrior("Kazakhstan", 1510, 100, 0.91, 0.93),
    "armenia": TeamStrengthPrior("Armenia", 1485, 96, 0.89, 0.91),
    "azerbaijan": TeamStrengthPrior("Azerbaijan", 1460, 112, 0.86, 0.90),
    "georgia": TeamStrengthPrior("Georgia", 1610, 46, 1.00, 1.03),
    "north macedonia": TeamStrengthPrior("North Macedonia", 1520, 70, 0.91, 0.95),
    "moldova": TeamStrengthPrior("Moldova", 1430, 150, 0.82, 0.87),
    "latvia": TeamStrengthPrior("Latvia", 1435, 137, 0.83, 0.88),
    "lithuania": TeamStrengthPrior("Lithuania", 1440, 138, 0.83, 0.88),
    "estonia": TeamStrengthPrior("Estonia", 1410, 123, 0.81, 0.86),
    "faroe islands": TeamStrengthPrior("Faroe Islands", 1425, 136, 0.82, 0.88),
    "malta": TeamStrengthPrior("Malta", 1370, 170, 0.76, 0.82),
    "andorra": TeamStrengthPrior("Andorra", 1320, 175, 0.72, 0.80),
    "san marino": TeamStrengthPrior("San Marino", 1050, 210, 0.56, 0.62),
    "liechtenstein": TeamStrengthPrior("Liechtenstein", 1230, 200, 0.65, 0.72),
    "gibraltar": TeamStrengthPrior("Gibraltar", 1300, 198, 0.74, 0.80),
    "cayman islands": TeamStrengthPrior("Cayman Islands", 900, 205, 0.53, 0.58),
    "british virgin islands": TeamStrengthPrior("British Virgin Islands", 960, 208, 0.56, 0.61),
    "us virgin islands": TeamStrengthPrior("US Virgin Islands", 980, 207, 0.57, 0.62),
    "anguilla": TeamStrengthPrior("Anguilla", 940, 209, 0.55, 0.60),
    "bermuda": TeamStrengthPrior("Bermuda", 1335, 168, 0.76, 0.79),
    "jamaica": TeamStrengthPrior("Jamaica", 1580, 53, 0.99, 1.00),
    "haiti": TeamStrengthPrior("Haiti", 1505, 86, 0.91, 0.93),
    "trinidad and tobago": TeamStrengthPrior("Trinidad and Tobago", 1495, 99, 0.90, 0.92),
    "guatemala": TeamStrengthPrior("Guatemala", 1510, 103, 0.91, 0.93),
    "honduras": TeamStrengthPrior("Honduras", 1520, 82, 0.93, 0.94),
    "panama": TeamStrengthPrior("Panama", 1610, 41, 1.01, 1.02),
    "costa rica": TeamStrengthPrior("Costa Rica", 1615, 39, 1.00, 1.04),
    "el salvador": TeamStrengthPrior("El Salvador", 1445, 145, 0.84, 0.87),
    "nicaragua": TeamStrengthPrior("Nicaragua", 1415, 134, 0.82, 0.85),
    "suriname": TeamStrengthPrior("Suriname", 1475, 133, 0.88, 0.89),
    "curacao": TeamStrengthPrior("Curacao", 1540, 88, 0.94, 0.96),
    "dominican republic": TeamStrengthPrior("Dominican Republic", 1390, 150, 0.80, 0.84),
    "puerto rico": TeamStrengthPrior("Puerto Rico", 1350, 156, 0.78, 0.81),
    "myanmar": TeamStrengthPrior("Myanmar", 1320, 164, 0.77, 0.81),
    "guam": TeamStrengthPrior("Guam", 1040, 203, 0.58, 0.63),
    "hong kong": TeamStrengthPrior("Hong Kong", 1335, 154, 0.78, 0.81),
    "chinese taipei": TeamStrengthPrior("Chinese Taipei", 1240, 165, 0.70, 0.75),
    "singapore": TeamStrengthPrior("Singapore", 1285, 161, 0.74, 0.78),
    "malaysia": TeamStrengthPrior("Malaysia", 1380, 132, 0.82, 0.84),
    "thailand": TeamStrengthPrior("Thailand", 1480, 101, 0.89, 0.91),
    "vietnam": TeamStrengthPrior("Vietnam", 1470, 115, 0.88, 0.91),
    "indonesia": TeamStrengthPrior("Indonesia", 1430, 134, 0.86, 0.87),
    "philippines": TeamStrengthPrior("Philippines", 1300, 147, 0.75, 0.80),
    "cambodia": TeamStrengthPrior("Cambodia", 1180, 180, 0.67, 0.71),
    "laos": TeamStrengthPrior("Laos", 1130, 186, 0.64, 0.69),
    "brunei": TeamStrengthPrior("Brunei", 1040, 191, 0.59, 0.64),
    "mongolia": TeamStrengthPrior("Mongolia", 1125, 189, 0.64, 0.68),
    "nepal": TeamStrengthPrior("Nepal", 1160, 178, 0.66, 0.70),
    "india": TeamStrengthPrior("India", 1395, 127, 0.82, 0.85),
    "china": TeamStrengthPrior("China", 1460, 92, 0.88, 0.90),
    "qatar": TeamStrengthPrior("Qatar", 1610, 40, 1.01, 1.02),
    "saudi arabia": TeamStrengthPrior("Saudi Arabia", 1635, 56, 1.01, 1.05),
    "iran": TeamStrengthPrior("Iran", 1710, 20, 1.11, 1.14),
    "iraq": TeamStrengthPrior("Iraq", 1585, 59, 0.98, 1.00),
    "jordan": TeamStrengthPrior("Jordan", 1570, 64, 0.97, 0.99),
    "oman": TeamStrengthPrior("Oman", 1540, 76, 0.94, 0.97),
    "united arab emirates": TeamStrengthPrior("United Arab Emirates", 1560, 67, 0.96, 0.98),
    "uae": TeamStrengthPrior("United Arab Emirates", 1560, 67, 0.96, 0.98),
    "kuwait": TeamStrengthPrior("Kuwait", 1450, 137, 0.85, 0.88),
    "bahrain": TeamStrengthPrior("Bahrain", 1545, 81, 0.94, 0.98),
}


_AGE_SUFFIX_RE = re.compile(r"\s+(u|under\s*)\d{2}\b", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^a-z0-9]+")


def normalize_team_name_for_prior(name: str) -> str:
    text = str(name or "").strip().casefold()
    text = text.replace("&", " and ")
    text = text.replace("u.s.", "us")
    text = _AGE_SUFFIX_RE.sub("", text)
    text = _PUNCT_RE.sub(" ", text)
    return " ".join(text.split())


def team_strength_prior(name: str) -> TeamStrengthPrior | None:
    normalized = normalize_team_name_for_prior(name)
    if not normalized:
        return None
    direct = _TEAM_PRIORS.get(normalized)
    if direct:
        return _apply_youth_adjustment(name, direct)
    aliases = {
        "usa": "united states",
        "usmnt": "united states",
        "u s a": "united states",
        "czechia": "czech republic",
        "south korea": "korea republic",
        "korea": "korea republic",
        "bosnia": "bosnia and herzegovina",
        "uae": "united arab emirates",
        "hk": "hong kong",
    }
    alias = aliases.get(normalized)
    if alias and alias in _TEAM_PRIORS:
        return _apply_youth_adjustment(name, _TEAM_PRIORS[alias])
    return None


def opponent_strength_elo(name: str, default: float = 1500.0) -> float:
    prior = team_strength_prior(name)
    return prior.elo if prior else default


def blend_profile_with_prior(
    profile: TeamProfile,
    prior: TeamStrengthPrior | None,
    *,
    recent_weight: float,
) -> TeamProfile:
    if prior is None:
        return profile
    recent_weight = clamp(recent_weight, 0.0, 0.65)
    prior_weight = 1.0 - recent_weight
    return replace(
        profile,
        elo=(profile.elo * recent_weight) + (prior.elo * prior_weight),
        fifa_rank=prior.fifa_rank,
        attack_rating=clamp(
            (profile.attack_rating * recent_weight) + (prior.attack_rating * prior_weight),
            0.50,
            1.65,
        ),
        defense_rating=clamp(
            (profile.defense_rating * recent_weight) + (prior.defense_rating * prior_weight),
            0.50,
            1.65,
        ),
    )


def _apply_youth_adjustment(source_name: str, prior: TeamStrengthPrior) -> TeamStrengthPrior:
    text = str(source_name or "").casefold()
    if not re.search(r"\b(u|under\s*)\d{2}\b", text):
        return prior
    return replace(
        prior,
        canonical_name=f"{prior.canonical_name} Youth",
        elo=prior.elo - 120.0,
        attack_rating=clamp(prior.attack_rating * 0.92, 0.50, 1.65),
        defense_rating=clamp(prior.defense_rating * 0.92, 0.50, 1.65),
        source=f"{prior.source}:youth_adjusted",
    )
