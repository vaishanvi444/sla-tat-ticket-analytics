"""SLA/TAT analytics for MDM request tickets.

Reads data/mdm_tickets.csv, loads it into SQLite, runs the KPI queries in sql/kpi_queries.sql and writes:
  outputs/kpi_results/*.csv       - one CSV per SQL query
  outputs/tat_percentiles.csv     - P50/P90 TAT by priority (pandas)
  outputs/SLA_TAT_Report.xlsx     - Excel report (one sheet per KPI)
  docs/dashboard.png              - one-page dashboard
  docs/insights.md                - auto-generated key findings
"""
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.generate_tickets import SNAPSHOT

ROOT = Path(__file__).resolve().parents[1]
DATA, OUT, DOCS, SQL = ROOT / "data", ROOT / "outputs", ROOT / "docs", ROOT / "sql"


def load_queries(path: Path) -> dict[str, str]:
    blocks = path.read_text().split("-- name:")[1:]
    return {b.split("\n", 1)[0].strip(): b.split("\n", 1)[1] for b in blocks}


def run_kpis(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    OUT.mkdir(exist_ok=True)
    con = sqlite3.connect(OUT / "mdm_tickets.db")
    df.to_sql("tickets", con, if_exists="replace", index=False)
    params = {"snapshot": SNAPSHOT.strftime("%Y-%m-%d %H:%M")}
    results = {}
    for name, query in load_queries(SQL / "kpi_queries.sql").items():
        results[name] = pd.read_sql_query(query, con, params=params if ":snapshot" in query else None)
    con.close()
    (OUT / "kpi_results").mkdir(exist_ok=True)
    for name, frame in results.items():
        frame.to_csv(OUT / "kpi_results" / f"{name}.csv", index=False)
    return results


def tat_percentiles(df: pd.DataFrame) -> pd.DataFrame:
    closed = df.dropna(subset=["tat_hours"])
    out = closed.groupby("priority")["tat_hours"].describe(percentiles=[0.5, 0.9])[["count", "50%", "90%", "max"]]
    out = out.rename(columns={"50%": "p50_tat_hours", "90%": "p90_tat_hours", "max": "max_tat_hours"}).round(2)
    out["sla_target_hours"] = closed.groupby("priority")["sla_target_hours"].first()
    return out.reset_index()


def write_excel(results: dict[str, pd.DataFrame], percentiles: pd.DataFrame):
    sheets = {**results, "tat_percentiles": percentiles}
    with pd.ExcelWriter(OUT / "SLA_TAT_Report.xlsx", engine="openpyxl") as xl:
        for name, frame in sheets.items():
            sheet = name.replace("_", " ").title()[:31]
            frame.to_excel(xl, sheet_name=sheet, index=False)
            ws = xl.sheets[sheet]
            ws.freeze_panes = "A2"
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 45)


def dashboard(r: dict[str, pd.DataFrame]):
    k = r["kpi_overview"].iloc[0]
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig = plt.figure(figsize=(16, 11), constrained_layout=True)
    top, bottom = fig.subfigures(2, 1, height_ratios=[0.6, 4])
    fig.suptitle("MDM Request Desk: SLA & TAT Dashboard (Jan 2025 - Sep 2026)", fontsize=18, fontweight="bold")
    tiles = {
        "Tickets": f"{int(k.total_tickets):,}",
        "SLA compliance": f"{k.sla_compliance_pct:.1f}%",
        "Avg TAT (hours)": f"{k.avg_tat_hours:.1f}",
        "First-time-right": f"{k.first_time_right_pct:.1f}%",
        "Rejection rate": f"{k.rejection_rate_pct:.1f}%",
        "Open backlog": f"{int(k.open_backlog)}",
    }
    for ax, (label, value) in zip(top.subplots(1, len(tiles)), tiles.items()):
        ax.axis("off")
        ax.add_patch(plt.Rectangle((0.03, 0), 0.94, 1, color="#1f4e79", transform=ax.transAxes))
        ax.text(0.5, 0.62, value, ha="center", va="center", fontsize=20, color="white", fontweight="bold")
        ax.text(0.5, 0.22, label, ha="center", va="center", fontsize=11, color="white")

    grid = bottom.add_gridspec(2, 3)
    m = r["monthly_trend"]
    ax = bottom.add_subplot(grid[0, :2])
    ax.bar(m["month"], m["tickets"], color="#9dc3e6", label="Tickets")
    ax.set_ylabel("Tickets")
    ax.tick_params(axis="x", rotation=45)
    ax2 = ax.twinx()
    ax2.plot(m["month"], m["sla_compliance_pct"], "o-", color="#c00000", label="SLA compliance %")
    ax2.axhline(90, ls="--", color="grey", lw=1)
    ax2.text(-0.4, 90.4, "90% target", ha="left", color="grey")
    ax2.set_ylim(70, 100)
    ax2.set_ylabel("SLA compliance %")
    ax.set_title("Monthly ticket volume and SLA compliance")
    ax.legend(loc="upper left")
    ax2.legend(loc="lower right")

    t = r["sla_by_request_type"]
    ax = bottom.add_subplot(grid[0, 2])
    ax.barh(t["request_type"], t["sla_compliance_pct"], color="#2e75b6")
    ax.set_xlim(t["sla_compliance_pct"].min() - 5, 100)
    ax.set_title("SLA compliance % by request type")
    for y, v in enumerate(t["sla_compliance_pct"]):
        ax.text(v, y, f" {v:.1f}", va="center")

    e = r["sla_by_erp"]
    ax = bottom.add_subplot(grid[1, 0])
    ax.bar(e["erp_system"], e["sla_compliance_pct"], color="#548235")
    ax.set_ylim(e["sla_compliance_pct"].min() - 5, 100)
    ax.set_title("SLA compliance % by ERP")
    for x, v in enumerate(e["sla_compliance_pct"]):
        ax.text(x, v, f"{v:.1f}", ha="center", va="bottom")

    p = r["rejection_pareto"]
    ax = bottom.add_subplot(grid[1, 1])
    labels = p["rejection_reason"].str.replace(" (GSTIN/VAT)", "").str.replace(" / record exists", "")
    ax.bar(labels, p["rejections"], color="#ed7d31")
    ax.tick_params(axis="x", rotation=30)
    for lbl in ax.get_xticklabels():
        lbl.set_ha("right")
    ax2 = ax.twinx()
    ax2.plot(labels, p["cumulative_pct"], "o-", color="#1f4e79")
    ax2.set_ylim(0, 105)
    ax.set_title("Rejection reasons (Pareto)")

    q = r["quarter_end_impact"]
    ax = bottom.add_subplot(grid[1, 2])
    ax.bar(q["period"], q["sla_compliance_pct"], color=["#a5a5a5", "#c00000"])
    ax.set_ylim(q["sla_compliance_pct"].min() - 10, 100)
    for x, (v, vol) in enumerate(zip(q["sla_compliance_pct"], q["avg_tickets_per_day"])):
        ax.text(x, v, f"{v:.1f}%\n({vol:.1f} tickets/day)", ha="center", va="bottom")
    ax.set_title("Quarter-end rush vs normal days (SLA %)")

    DOCS.mkdir(exist_ok=True)
    fig.savefig(DOCS / "dashboard.png", dpi=110)
    plt.close(fig)


def write_insights(r: dict[str, pd.DataFrame], pct: pd.DataFrame):
    k = r["kpi_overview"].iloc[0]
    m = r["monthly_trend"]
    before = m[m["month"] < "2025-07"]["sla_compliance_pct"].mean()
    after = m[m["month"] >= "2025-07"]["sla_compliance_pct"].mean()
    worst_type = r["sla_by_request_type"].iloc[0]
    worst_erp = r["sla_by_erp"].iloc[0]
    q = r["quarter_end_impact"].set_index("period")["sla_compliance_pct"]
    top2 = r["rejection_pareto"].head(2)
    backlog = r["open_backlog_ageing"]
    lines = [
        "# Key insights (auto-generated by `src/analyze.py`)",
        "",
        f"- **{int(k.total_tickets):,} tickets** analysed; overall **SLA compliance {k.sla_compliance_pct:.1f}%**, "
        f"average TAT **{k.avg_tat_hours:.1f} h**, first-time-right **{k.first_time_right_pct:.1f}%**.",
        f"- SLA compliance averaged **{before:.1f}%** before July 2025 and **{after:.1f}%** after the process "
        f"automation rollout (+{after - before:.1f} pts).",
        f"- **{worst_type.request_type}** requests have the lowest SLA compliance ({worst_type.sla_compliance_pct:.1f}%), "
        "so they are the first candidates for checklist and approval automation.",
        f"- **{worst_erp.erp_system}** is the slowest ERP ({worst_erp.sla_compliance_pct:.1f}% SLA; average TAT "
        f"{worst_erp.avg_tat_pct_of_sla:.0f}% of the SLA target).",
        f"- Quarter-end rush drops SLA compliance to **{q.get('Quarter-end (25th onward)', float('nan')):.1f}%** "
        f"vs {q.get('Normal days', float('nan')):.1f}% on normal days, so plan extra capacity for the last week of each quarter.",
        f"- The top 2 rejection reasons (**{top2.rejection_reason.iat[0]}**, **{top2.rejection_reason.iat[1]}**) cause "
        f"{top2.cumulative_pct.iat[1]:.0f}% of rejections; a mandatory-document checklist at intake would cut most rework.",
        f"- Open backlog: **{len(backlog)}** tickets, of which **{(backlog.sla_status == 'Breached').sum()}** "
        "have already breached SLA.",
        "",
        "## TAT percentiles by priority",
        "",
        pct.to_markdown(index=False),
    ]
    (DOCS / "insights.md").write_text("\n".join(lines) + "\n")
    return "\n".join(lines)


def main():
    df = pd.read_csv(DATA / "mdm_tickets.csv")
    results = run_kpis(df)
    pct = tat_percentiles(df)
    pct.to_csv(OUT / "tat_percentiles.csv", index=False)
    write_excel(results, pct)
    dashboard(results)
    print(write_insights(results, pct))


if __name__ == "__main__":
    main()
