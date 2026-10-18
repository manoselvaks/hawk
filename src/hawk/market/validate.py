"""Sanity checks run on the market data before anything is written."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

BANK_RATE_BOUNDS = (0.0, 20.0)
GILT_YIELD_BOUNDS = (-2.0, 20.0)


@dataclass
class ValidationReport:
    """Errors stop the collector; flags are expected oddities worth reading."""

    errors: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _check_dates(
    report: ValidationReport, name: str, frame: pd.DataFrame, today: pd.Timestamp
) -> None:
    dates = frame["date"]
    if dates.duplicated().any():
        dupes = sorted(dates[dates.duplicated()].dt.date.astype(str).unique())
        report.errors.append(f"{name}: duplicate dates {dupes[:5]}")
    if not dates.is_monotonic_increasing:
        report.errors.append(f"{name}: dates are not sorted")
    if len(dates) and dates.max() > today:
        report.errors.append(f"{name}: dates after today ({dates.max().date()})")


def _check_bounds(
    report: ValidationReport, name: str, values: pd.Series, bounds: tuple[float, float]
) -> None:
    low, high = bounds
    bad = values.dropna()[(values.dropna() < low) | (values.dropna() > high)]
    if len(bad):
        report.errors.append(f"{name}: {len(bad)} values outside [{low}, {high}]")


def validate(
    bank_rate: pd.DataFrame,
    decisions: pd.DataFrame,
    gilts: pd.DataFrame,
    today: pd.Timestamp | None = None,
) -> ValidationReport:
    """Check the three output tables, separately and against each other."""
    today = today or pd.Timestamp.today().normalize()
    report = ValidationReport()

    for name, frame in [
        ("bank_rate", bank_rate),
        ("mpc_decisions", decisions),
        ("gilt_yields", gilts),
    ]:
        _check_dates(report, name, frame, today)

    _check_bounds(report, "bank_rate.rate_pct", bank_rate["rate_pct"], BANK_RATE_BOUNDS)
    _check_bounds(
        report, "mpc_decisions.rate_pct", decisions["rate_pct"], BANK_RATE_BOUNDS
    )
    for column in gilts.columns.drop("date"):
        _check_bounds(report, f"gilt_yields.{column}", gilts[column], GILT_YIELD_BOUNDS)
    if (gilts["date"].dt.dayofweek >= 5).any():
        report.errors.append("gilt_yields: weekend dates present")

    for _, change in bank_rate.iterrows():
        day = change["date"].date()
        move = f"{day}: {change['prev_rate_pct']}% -> {change['rate_pct']}%"
        match change["mpc_match"]:
            case "unmatched":
                report.errors.append(
                    f"Bank Rate change with no matching MPC decision, {move}"
                )
            case "unscheduled":
                report.flags.append(f"Unscheduled (emergency) MPC move, {move}")
            case "pre_mpc":
                report.flags.append(f"Change set before the MPC existed, {move}")

    changes = set(bank_rate["date"])
    for _, decision in decisions[
        decisions["decision"].isin(["hike", "cut"])
    ].iterrows():
        if decision["date"] not in changes:
            day = decision["date"].date()
            report.errors.append(
                f"MPC {decision['decision']} on {day} has no Bank Rate change"
            )
    if decisions["prev_rate_pct"].isna().any():
        report.errors.append("mpc_decisions: previous rate unknown for some decisions")
    return report
