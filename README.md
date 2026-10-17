# Audit Scheduler with Built-in Timesheets (Enhanced)

**Full prototype for certification / external audit teams**

## Features

- **Visual calendar** — Plotly timeline of all assignments
- **Competence matching** — filters auditors by required standards
- **Programme planning** & client scheduling with travel notes
- **Travel cost/distance** — estimated km and £ cost (Car/Train/Flight) using UK city matrix
- **Multi-level timesheet workflow** — Submit → Manager Approve (with reject)
- **Immutable audit trail** — every create, assign, approve, bulk action logged
- **User logins & roles** — Admin / Manager / Auditor (demo accounts included)
- **Bulk programme allocation** — suggests best auditor matches by competence + proximity + load; one-click apply
- **Excel & PDF export** — for billing / payroll summaries
- Timesheets tied to engagements by category

## Quick Start

```bash
pip install streamlit pandas plotly reportlab openpyxl
streamlit run audit_scheduler.py
```

**Demo logins:**
- admin / admin123 (full access)
- manager / manager123 (approvals + reports)
- auditor / auditor123 (limited view)

Sample data loads automatically. Data stored in local `audit_scheduler.db`.

## Notes

This is a feature-rich prototype. Production use would add:
- Proper password hashing (bcrypt), HTTPS, session security
- Real mapping API for distances
- Calendar sync, email notifications
- More granular role permissions and multi-step approval chains
- Conflict detection (double-booking, rotation rules)

All core requested capabilities are implemented and functional.
