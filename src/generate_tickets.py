"""Generate a synthetic ServiceNow-style ticket log for a Customer & Vendor MDM team.

Output: data/mdm_tickets.csv (one row per request ticket)
"""
import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 7
START, END = datetime(2025, 1, 1), datetime(2026, 9, 30, 18, 0)
SNAPSHOT = END  # "as of" date for the open-ticket backlog
ROOT = Path(__file__).resolve().parents[1]

SLA_HOURS = {"P1": 4, "P2": 8, "P3": 24, "P4": 48}
PRIORITY_MIX = {"P1": 0.03, "P2": 0.15, "P3": 0.60, "P4": 0.22}
REQUEST_TYPES = {  # type: (share, median TAT multiplier vs SLA)
    "Create": (0.34, 0.55), "Modify": (0.28, 0.45), "Extend": (0.12, 0.40),
    "Deactivate": (0.10, 0.35), "Block/Unblock": (0.08, 0.30), "Bank Details Change": (0.08, 0.75),
}
ERPS = {"Oracle": 0.35, "JDE": 0.25, "AS400": 0.18, "Sage 500": 0.12, "ADAGE": 0.10}
ERP_DELAY = {"Oracle": 1.0, "JDE": 1.05, "AS400": 1.25, "Sage 500": 1.1, "ADAGE": 1.3}
REGIONS = {"North America": 0.40, "EMEA": 0.30, "APAC": 0.20, "LATAM": 0.10}
AGENTS = [f"Analyst {chr(65 + i)}" for i in range(12)]
AGENT_SPEED = dict(zip(AGENTS, np.linspace(0.8, 1.3, len(AGENTS))))
REJECTION_REASONS = {
    "Missing supporting documents": 0.32, "Duplicate request / record exists": 0.22,
    "Invalid bank details": 0.16, "Incorrect tax ID (GSTIN/VAT)": 0.15, "Approval missing": 0.15,
}

rng = random.Random(SEED)
np_rng = np.random.default_rng(SEED)


def pick(weights: dict):
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def daily_volume(day: datetime) -> int:
    base = 18 if day.weekday() < 5 else 2
    month_end_rush = 1.6 if day.day >= 25 and day.month in (3, 6, 9, 12) else 1.0
    growth = 1 + 0.25 * (day - START).days / (END - START).days
    return int(np_rng.poisson(base * month_end_rush * growth))


def main():
    rows, seq = [], 1
    day = START
    total_days = (END - START).days
    while day <= END:
        for _ in range(daily_volume(day)):
            opened = day + timedelta(hours=rng.uniform(8, 19))
            if opened > END:
                continue
            priority = pick(PRIORITY_MIX)
            req_type = rng.choices(list(REQUEST_TYPES), weights=[v[0] for v in REQUEST_TYPES.values()])[0]
            erp, agent = pick(ERPS), rng.choice(AGENTS)
            sla = SLA_HOURS[priority]
            # Process improvement after automation rollout (Jul 2025) lowers TAT gradually.
            improvement = 1.0 if opened < datetime(2025, 7, 1) else 0.85 - 0.1 * (opened - START).days / total_days
            rush = 1.35 if opened.day >= 25 and opened.month in (3, 6, 9, 12) else 1.0
            median = sla * REQUEST_TYPES[req_type][1] * ERP_DELAY[erp] * AGENT_SPEED[agent] * improvement * rush
            tat = float(np_rng.lognormal(np.log(median), 0.6))

            rejected = rng.random() < (0.12 if req_type in ("Create", "Bank Details Change") else 0.06)
            reopened = 0 if rejected else int(rng.random() < 0.04)
            resolved = opened + timedelta(hours=tat)
            if resolved > SNAPSHOT:
                state, resolved_at, tat_hours = rng.choice(["Open", "Work in Progress", "Pending Requester"]), None, None
            else:
                state = "Closed - Rejected" if rejected else "Closed - Complete"
                resolved_at, tat_hours = resolved, round(tat, 2)
            rows.append({
                "ticket_id": f"RITM{1000000 + seq}",
                "opened_at": opened.strftime("%Y-%m-%d %H:%M"),
                "resolved_at": resolved_at.strftime("%Y-%m-%d %H:%M") if resolved_at else None,
                "domain": "Vendor" if rng.random() < 0.55 else "Customer",
                "request_type": req_type,
                "priority": priority,
                "sla_target_hours": sla,
                "erp_system": erp,
                "region": pick(REGIONS),
                "assignment_group": "MDM - Vendor" if req_type == "Bank Details Change" else rng.choice(["MDM - Vendor", "MDM - Customer"]),
                "assigned_to": agent,
                "state": state,
                "tat_hours": tat_hours,
                "rejection_reason": pick(REJECTION_REASONS) if rejected and resolved_at else None,
                "reopen_count": reopened if resolved_at else 0,
            })
            seq += 1
        day += timedelta(days=1)

    df = pd.DataFrame(rows)
    df.loc[df["assignment_group"].str.contains("Customer") & (df["domain"] == "Vendor"), "assignment_group"] = "MDM - Vendor"
    df.loc[df["assignment_group"].str.contains("Vendor") & (df["domain"] == "Customer"), "assignment_group"] = "MDM - Customer"
    (ROOT / "data").mkdir(exist_ok=True)
    df.to_csv(ROOT / "data" / "mdm_tickets.csv", index=False)
    print(f"Generated {len(df):,} tickets from {df.opened_at.min()} to {df.opened_at.max()} "
          f"({df.resolved_at.isna().sum()} open as of {SNAPSHOT:%Y-%m-%d})")


if __name__ == "__main__":
    main()
