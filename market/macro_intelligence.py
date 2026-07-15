"""
MACRO INTELLIGENCE ENGINE (Phase 1 — rule-based)

Detects macro/geopolitical themes in news headlines (oil supply shocks,
wars, sanctions, rate decisions, etc.) and maps them to SECTOR-LEVEL bias
— never a direct BUY/SELL signal. This bias is one input among several
that nudges a stock's news/context score, it does not decide the trade.

Example: "Strait of Hormuz blocked" ->
    Positive: Oil & Gas, Energy, Defence
    Negative: Airlines, Paints, Chemicals, Tyres, Logistics

This is intentionally a starting point, not a comprehensive world-events
model: it's a curated keyword -> theme -> sector-bias table. Two known
limitations to be aware of:
  - No event decay yet (a theme detected today has the same weight
    whether the underlying news is from today or a week-old re-report).
  - No source/recency weighting — every matching headline counts equally.
Both are natural Phase 2 extensions once there's a real event-timestamp
feed to work from.
"""

from __future__ import annotations

# Each theme: (keywords to match in headline text, {sector: bias in [-1, 1]})
THEMES: list[tuple[list[str], dict[str, float]]] = [
    (
        ["strait of hormuz", "oil supply", "opec cut", "opec+ cut", "crude surge", "oil embargo"],
        {
            "Energy": 0.8, "Oil & Gas": 0.8, "Oil": 0.8,
            "Defence": 0.4, "Defense": 0.4,
            "Airlines": -0.8, "Aviation": -0.8,
            "Paints": -0.6, "Chemicals": -0.5, "Tyres": -0.6,
            "Logistics": -0.5, "FMCG": -0.2,
        },
    ),
    (
        ["war", "military conflict", "missile strike", "invasion", "airstrike"],
        {
            "Defence": 0.7, "Defense": 0.7,
            "Energy": 0.4, "Oil & Gas": 0.4,
            "Airlines": -0.6, "Aviation": -0.6, "Tourism": -0.6,
            "Insurance": -0.3,
        },
    ),
    (
        ["sanctions", "trade ban", "export ban", "tariff"],
        {
            "IT": -0.3, "Information Technology": -0.3,
            "Metals": -0.3, "Auto": -0.3, "Automobile": -0.3,
            "Defence": 0.2, "Defense": 0.2,
        },
    ),
    (
        ["rate hike", "fed hikes", "rbi hikes", "interest rate increase"],
        {
            "Banks": -0.3, "Banking": -0.3, "Realty": -0.5, "Real Estate": -0.5,
            "Auto": -0.3, "Automobile": -0.3, "NBFC": -0.4,
        },
    ),
    (
        ["rate cut", "fed cuts", "rbi cuts", "interest rate decrease"],
        {
            "Banks": 0.3, "Banking": 0.3, "Realty": 0.5, "Real Estate": 0.5,
            "Auto": 0.3, "Automobile": 0.3, "NBFC": 0.4,
        },
    ),
    (
        ["gold rally", "gold surges", "safe haven demand"],
        {"Gold": 0.6, "Jewellery": 0.4, "Mining": 0.3},
    ),
    (
        ["chip shortage", "semiconductor shortage"],
        {"Auto": -0.4, "Automobile": -0.4, "Electronics": -0.4, "IT": 0.2},
    ),
]


def sector_bias(headlines: list[str], sector: str | None) -> float:
    """Scan headlines for known macro themes and return the net bias in
    [-1, 1] for the given sector. Returns 0.0 if no theme matches or the
    stock's sector isn't in the affected list for any matched theme."""
    if not headlines or not sector:
        return 0.0

    sector = sector.strip()
    text = " ".join(h.lower() for h in headlines if h)

    total = 0.0
    matches = 0
    for keywords, sector_map in THEMES:
        if any(kw in text for kw in keywords):
            for sec_name, bias in sector_map.items():
                if sec_name.lower() == sector.lower():
                    total += bias
                    matches += 1

    if matches == 0:
        return 0.0
    return round(max(-1.0, min(1.0, total / matches)), 3)
