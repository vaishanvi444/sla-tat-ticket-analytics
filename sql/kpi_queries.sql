-- KPI queries run by src/analyze.py against outputs/mdm_tickets.db (SQLite).
-- Each query block is preceded by a "name" marker comment used as the output file name.
-- A ticket meets SLA when it is closed and tat_hours <= sla_target_hours.

-- name: kpi_overview
SELECT COUNT(*)                                                         AS total_tickets,
       SUM(resolved_at IS NOT NULL)                                     AS closed_tickets,
       SUM(resolved_at IS NULL)                                         AS open_backlog,
       ROUND(100.0 * SUM(tat_hours <= sla_target_hours) / SUM(resolved_at IS NOT NULL), 2) AS sla_compliance_pct,
       ROUND(AVG(tat_hours), 2)                                         AS avg_tat_hours,
       ROUND(100.0 * SUM(state = 'Closed - Rejected') / SUM(resolved_at IS NOT NULL), 2) AS rejection_rate_pct,
       ROUND(100.0 * SUM(state = 'Closed - Complete' AND reopen_count = 0)
             / SUM(state = 'Closed - Complete'), 2)                     AS first_time_right_pct
FROM tickets;

-- name: monthly_trend
SELECT strftime('%Y-%m', opened_at)                                     AS month,
       COUNT(*)                                                         AS tickets,
       ROUND(100.0 * SUM(tat_hours <= sla_target_hours) / SUM(resolved_at IS NOT NULL), 2) AS sla_compliance_pct,
       ROUND(AVG(tat_hours), 2)                                         AS avg_tat_hours,
       SUM(tat_hours > sla_target_hours)                                AS sla_breaches
FROM tickets
GROUP BY month
ORDER BY month;

-- name: sla_by_request_type
SELECT request_type,
       COUNT(*)                                                         AS tickets,
       ROUND(AVG(tat_hours), 2)                                         AS avg_tat_hours,
       ROUND(100.0 * SUM(tat_hours <= sla_target_hours) / SUM(resolved_at IS NOT NULL), 2) AS sla_compliance_pct
FROM tickets
GROUP BY request_type
ORDER BY sla_compliance_pct;

-- name: sla_by_priority
SELECT priority, sla_target_hours,
       COUNT(*)                                                         AS tickets,
       ROUND(AVG(tat_hours), 2)                                         AS avg_tat_hours,
       ROUND(100.0 * SUM(tat_hours <= sla_target_hours) / SUM(resolved_at IS NOT NULL), 2) AS sla_compliance_pct
FROM tickets
GROUP BY priority, sla_target_hours
ORDER BY priority;

-- name: sla_by_erp
SELECT erp_system,
       COUNT(*)                                                         AS tickets,
       ROUND(AVG(tat_hours / sla_target_hours) * 100, 1)                AS avg_tat_pct_of_sla,
       ROUND(100.0 * SUM(tat_hours <= sla_target_hours) / SUM(resolved_at IS NOT NULL), 2) AS sla_compliance_pct
FROM tickets
GROUP BY erp_system
ORDER BY sla_compliance_pct;

-- name: quarter_end_impact
SELECT CASE WHEN CAST(strftime('%d', opened_at) AS INT) >= 25
             AND CAST(strftime('%m', opened_at) AS INT) IN (3, 6, 9, 12)
            THEN 'Quarter-end (25th onward)' ELSE 'Normal days' END     AS period,
       COUNT(*) * 1.0 / COUNT(DISTINCT date(opened_at))                 AS avg_tickets_per_day,
       ROUND(100.0 * SUM(tat_hours <= sla_target_hours) / SUM(resolved_at IS NOT NULL), 2) AS sla_compliance_pct
FROM tickets
GROUP BY period;

-- name: rejection_pareto
WITH r AS (
    SELECT rejection_reason, COUNT(*) AS rejections
    FROM tickets
    WHERE rejection_reason IS NOT NULL
    GROUP BY rejection_reason
)
SELECT rejection_reason, rejections,
       ROUND(100.0 * SUM(rejections) OVER (ORDER BY rejections DESC ROWS UNBOUNDED PRECEDING)
             / SUM(rejections) OVER (), 1)                              AS cumulative_pct
FROM r
ORDER BY rejections DESC;

-- name: agent_performance
SELECT assigned_to,
       SUM(resolved_at IS NOT NULL)                                     AS closed_tickets,
       ROUND(AVG(tat_hours), 2)                                         AS avg_tat_hours,
       ROUND(100.0 * SUM(tat_hours <= sla_target_hours) / SUM(resolved_at IS NOT NULL), 2) AS sla_compliance_pct,
       SUM(reopen_count)                                                AS reopens
FROM tickets
GROUP BY assigned_to
ORDER BY sla_compliance_pct DESC;

-- name: open_backlog_ageing
SELECT ticket_id, opened_at, request_type, priority, state, assigned_to,
       ROUND((julianday(:snapshot) - julianday(opened_at)) * 24, 1)      AS age_hours,
       CASE WHEN (julianday(:snapshot) - julianday(opened_at)) * 24 > sla_target_hours
            THEN 'Breached' ELSE 'Within SLA' END                       AS sla_status
FROM tickets
WHERE resolved_at IS NULL
ORDER BY age_hours DESC;
