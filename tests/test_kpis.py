import sqlite3

import pandas as pd

from src.analyze import load_queries, tat_percentiles
from src.generate_tickets import SNAPSHOT
from pathlib import Path

QUERIES = load_queries(Path(__file__).resolve().parents[1] / "sql" / "kpi_queries.sql")


def tickets():
    return pd.DataFrame([
        # met SLA
        {"ticket_id": "T1", "opened_at": "2026-01-05 09:00", "resolved_at": "2026-01-05 12:00", "request_type": "Create",
         "priority": "P1", "sla_target_hours": 4, "erp_system": "JDE", "assigned_to": "A", "state": "Closed - Complete",
         "tat_hours": 3.0, "rejection_reason": None, "reopen_count": 0},
        # breached SLA
        {"ticket_id": "T2", "opened_at": "2026-01-06 09:00", "resolved_at": "2026-01-06 19:00", "request_type": "Create",
         "priority": "P1", "sla_target_hours": 4, "erp_system": "JDE", "assigned_to": "A", "state": "Closed - Complete",
         "tat_hours": 10.0, "rejection_reason": None, "reopen_count": 1},
        # rejected within SLA
        {"ticket_id": "T3", "opened_at": "2026-02-02 09:00", "resolved_at": "2026-02-02 10:00", "request_type": "Modify",
         "priority": "P3", "sla_target_hours": 24, "erp_system": "Oracle", "assigned_to": "B", "state": "Closed - Rejected",
         "tat_hours": 1.0, "rejection_reason": "Approval missing", "reopen_count": 0},
        # open and already breached at snapshot
        {"ticket_id": "T4", "opened_at": "2026-09-28 09:00", "resolved_at": None, "request_type": "Modify",
         "priority": "P3", "sla_target_hours": 24, "erp_system": "Oracle", "assigned_to": "B", "state": "Open",
         "tat_hours": None, "rejection_reason": None, "reopen_count": 0},
    ])


def run(name):
    con = sqlite3.connect(":memory:")
    tickets().to_sql("tickets", con, index=False)
    params = {"snapshot": SNAPSHOT.strftime("%Y-%m-%d %H:%M")} if ":snapshot" in QUERIES[name] else None
    return pd.read_sql_query(QUERIES[name], con, params=params)


def test_overview_kpis():
    k = run("kpi_overview").iloc[0]
    assert k.total_tickets == 4 and k.closed_tickets == 3 and k.open_backlog == 1
    assert round(k.sla_compliance_pct, 2) == 66.67
    assert round(k.rejection_rate_pct, 2) == 33.33
    assert k.first_time_right_pct == 50.0


def test_sla_by_priority():
    p = run("sla_by_priority").set_index("priority")
    assert p.loc["P1", "sla_compliance_pct"] == 50.0
    assert p.loc["P3", "sla_compliance_pct"] == 100.0


def test_backlog_ageing_flags_breach():
    b = run("open_backlog_ageing")
    assert list(b.ticket_id) == ["T4"]
    assert b.sla_status.iat[0] == "Breached"


def test_rejection_pareto_cumulative():
    p = run("rejection_pareto")
    assert p.cumulative_pct.iat[-1] == 100.0


def test_tat_percentiles():
    pct = tat_percentiles(tickets()).set_index("priority")
    assert pct.loc["P1", "p50_tat_hours"] == 6.5
    assert pct.loc["P3", "count"] == 1
