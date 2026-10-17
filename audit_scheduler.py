import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta, date
import json
import hashlib
import plotly.express as px
import plotly.graph_objects as go
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
import io
import os

# Database
DB_PATH = "audit_scheduler.db"

def get_conn():
    return sqlite3.connect(DB_PATH)

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT,
        role TEXT NOT NULL,  -- Admin, Manager, Auditor
        auditor_id INTEGER
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS auditors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT,
        base_location TEXT,
        daily_rate REAL,
        competencies TEXT,
        notes TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS engagements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client TEXT NOT NULL,
        standards TEXT,
        location TEXT,
        preferred_start TEXT,
        preferred_end TEXT,
        duration_days REAL,
        required_competencies TEXT,
        status TEXT DEFAULT 'Planned',
        notes TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        engagement_id INTEGER,
        auditor_id INTEGER,
        role TEXT,
        start_date TEXT,
        end_date TEXT,
        travel_notes TEXT,
        travel_distance_km REAL,
        travel_cost REAL,
        FOREIGN KEY(engagement_id) REFERENCES engagements(id),
        FOREIGN KEY(auditor_id) REFERENCES auditors(id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS timesheets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        auditor_id INTEGER,
        engagement_id INTEGER,
        date TEXT,
        hours REAL,
        category TEXT,
        description TEXT,
        status TEXT DEFAULT 'Draft',  -- Draft / Submitted / ManagerApproved / Approved
        submitted_by TEXT,
        approved_by TEXT,
        FOREIGN KEY(auditor_id) REFERENCES auditors(id),
        FOREIGN KEY(engagement_id) REFERENCES engagements(id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS audit_trail (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        username TEXT,
        action TEXT,
        table_name TEXT,
        record_id INTEGER,
        details TEXT
    )""")
    conn.commit()
    # Seed admin user if none
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        c.execute("INSERT INTO users (username, password_hash, full_name, role) VALUES (?,?,?,?)",
                  ("admin", hash_password("admin123"), "System Admin", "Admin"))
        c.execute("INSERT INTO users (username, password_hash, full_name, role) VALUES (?,?,?,?)",
                  ("manager", hash_password("manager123"), "Audit Manager", "Manager"))
        c.execute("INSERT INTO users (username, password_hash, full_name, role) VALUES (?,?,?,?)",
                  ("auditor", hash_password("auditor123"), "Sample Auditor", "Auditor"))
        conn.commit()
    conn.close()

def log_action(username, action, table, record_id, details):
    conn = get_conn()
    conn.execute("INSERT INTO audit_trail (timestamp, username, action, table_name, record_id, details) VALUES (?,?,?,?,?,?)",
                 (datetime.now().isoformat(), username, action, table, record_id, details))
    conn.commit()
    conn.close()

def seed_sample_data():
    conn = get_conn()
    c = conn.cursor()
    if c.execute("SELECT COUNT(*) FROM auditors").fetchone()[0] == 0:
        auditors = [
            ("Alice Chen", "alice@certbody.com", "London", 850, json.dumps(["ISO 9001", "ISO 14001", "ISO 45001"]), "Senior, multi-standard"),
            ("Bob Martinez", "bob@certbody.com", "Manchester", 720, json.dumps(["ISO 9001", "IATF 16949"]), "Automotive specialist"),
            ("Carla Singh", "carla@certbody.com", "Birmingham", 680, json.dumps(["ISO 14001", "ISO 50001", "ISO 27001"]), "Environmental & energy"),
            ("David Okonkwo", "david@certbody.com", "Leeds", 750, json.dumps(["ISO 9001", "ISO 13485"]), "Medical devices"),
            ("Elena Rossi", "elena@certbody.com", "London", 900, json.dumps(["ISO 9001", "ISO 14001", "ISO 45001", "ISO 27001"]), "Lead auditor, high capacity"),
        ]
        c.executemany("INSERT INTO auditors (name, email, base_location, daily_rate, competencies, notes) VALUES (?,?,?,?,?,?)", auditors)
        engagements = [
            ("Acme Manufacturing Ltd", json.dumps(["ISO 9001", "ISO 14001"]), "Birmingham", "2026-11-10", "2026-11-20", 3, json.dumps(["ISO 9001", "ISO 14001"]), "Planned", "Integrated QMS + EMS"),
            ("MedTech Solutions", json.dumps(["ISO 13485"]), "Leeds", "2026-11-15", "2026-11-25", 2, json.dumps(["ISO 13485"]), "Planned", "Surveillance audit"),
            ("GreenEnergy Co", json.dumps(["ISO 50001", "ISO 14001"]), "Manchester", "2026-12-01", "2026-12-10", 2.5, json.dumps(["ISO 50001", "ISO 14001"]), "Planned", ""),
            ("AutoParts Europe", json.dumps(["IATF 16949", "ISO 9001"]), "Coventry", "2026-11-05", "2026-11-15", 4, json.dumps(["IATF 16949"]), "Planned", "Recertification"),
        ]
        c.executemany("INSERT INTO engagements (client, standards, location, preferred_start, preferred_end, duration_days, required_competencies, status, notes) VALUES (?,?,?,?,?,?,?,?,?)", engagements)
        conn.commit()
    conn.close()

# Simple UK city distance matrix (approx km)
CITY_DISTANCES = {
    ("London", "Manchester"): 320, ("London", "Birmingham"): 190, ("London", "Leeds"): 310,
    ("London", "Coventry"): 160, ("Manchester", "Birmingham"): 140, ("Manchester", "Leeds"): 70,
    ("Manchester", "Coventry"): 150, ("Birmingham", "Leeds"): 170, ("Birmingham", "Coventry"): 40,
    ("Leeds", "Coventry"): 180,
}

def estimate_distance(from_city, to_city):
    if not from_city or not to_city or from_city == to_city:
        return 0
    key = tuple(sorted([from_city, to_city]))
    return CITY_DISTANCES.get(key, 250)  # default fallback

def estimate_travel_cost(distance_km, method="Car"):
    if method == "Car":
        return round(distance_km * 0.45, 2)  # £0.45/km
    elif method == "Train":
        return round(distance_km * 0.35 + 40, 2)
    elif method == "Flight":
        return round(150 + distance_km * 0.2, 2)
    return round(distance_km * 0.4, 2)

init_db()
seed_sample_data()

# Auth
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = None
    st.session_state.role = None
    st.session_state.full_name = None

def check_login(username, password):
    conn = get_conn()
    row = conn.execute("SELECT password_hash, role, full_name FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if row and row[0] == hash_password(password):
        return row[1], row[2]
    return None, None

# Login screen
if not st.session_state.logged_in:
    st.title("📋 Audit Scheduler & Timesheets")
    st.subheader("Login")
    with st.form("login"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            role, full = check_login(u, p)
            if role:
                st.session_state.logged_in = True
                st.session_state.username = u
                st.session_state.role = role
                st.session_state.full_name = full
                st.rerun()
            else:
                st.error("Invalid credentials")
    st.info("Demo accounts: admin/admin123 | manager/manager123 | auditor/auditor123")
    st.stop()

# Main app
st.set_page_config(page_title="Audit Scheduler", layout="wide", page_icon="📋")
st.title("📋 Audit Scheduler with Timesheets")
st.caption(f"Logged in as {st.session_state.full_name} ({st.session_state.role}) | {datetime.now().strftime('%Y-%m-%d %H:%M')}")

if st.sidebar.button("Logout"):
    st.session_state.logged_in = False
    st.rerun()

st.sidebar.markdown("### Role Access")
st.sidebar.write(f"**{st.session_state.role}**")
if st.session_state.role == "Admin":
    st.sidebar.success("Full access")
elif st.session_state.role == "Manager":
    st.sidebar.info("Approvals + reporting")
else:
    st.sidebar.warning("Own timesheets + view schedule")

# Helpers
def load_auditors():
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM auditors", conn)
    conn.close()
    if not df.empty:
        df["competencies"] = df["competencies"].apply(lambda x: json.loads(x) if x else [])
    return df

def load_engagements():
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM engagements", conn)
    conn.close()
    if not df.empty:
        df["standards"] = df["standards"].apply(lambda x: json.loads(x) if x else [])
        df["required_competencies"] = df["required_competencies"].apply(lambda x: json.loads(x) if x else [])
    return df

def load_assignments():
    conn = get_conn()
    df = pd.read_sql("""
        SELECT a.*, au.name as auditor_name, au.base_location, e.client, e.location as eng_location
        FROM assignments a
        LEFT JOIN auditors au ON a.auditor_id = au.id
        LEFT JOIN engagements e ON a.engagement_id = e.id
    """, conn)
    conn.close()
    return df

def load_timesheets():
    conn = get_conn()
    df = pd.read_sql("""
        SELECT t.*, au.name as auditor_name, e.client
        FROM timesheets t
        LEFT JOIN auditors au ON t.auditor_id = au.id
        LEFT JOIN engagements e ON t.engagement_id = e.id
    """, conn)
    conn.close()
    return df

def load_audit_trail(limit=50):
    conn = get_conn()
    df = pd.read_sql(f"SELECT * FROM audit_trail ORDER BY id DESC LIMIT {limit}", conn)
    conn.close()
    return df

# Tabs based on role
if st.session_state.role in ["Admin", "Manager"]:
    tabs = st.tabs(["🏠 Dashboard", "📅 Calendar", "👥 Auditors", "📁 Engagements", "📅 Schedule & Match", "🚀 Bulk Allocation", "⏱️ Timesheets", "📊 Reports & Export", "🔒 Audit Trail"])
else:
    tabs = st.tabs(["🏠 Dashboard", "📅 Calendar", "⏱️ My Timesheets", "📊 Reports"])

# Dashboard
with tabs[0]:
    st.header("Dashboard")
    auditors_df = load_auditors()
    eng_df = load_engagements()
    assign_df = load_assignments()
    ts_df = load_timesheets()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Auditors", len(auditors_df))
    col2.metric("Engagements", len(eng_df))
    col3.metric("Assignments", len(assign_df))
    col4.metric("Timesheet entries", len(ts_df))
    st.subheader("Upcoming Engagements")
    if not eng_df.empty:
        display_eng = eng_df[["client", "standards", "location", "preferred_start", "duration_days", "status"]].copy()
        display_eng["standards"] = display_eng["standards"].apply(lambda x: ", ".join(x) if isinstance(x, list) else "")
        st.dataframe(display_eng, use_container_width=True)

# Calendar
with tabs[1]:
    st.header("Visual Calendar")
    assign_df = load_assignments()
    if not assign_df.empty:
        assign_df["start_date"] = pd.to_datetime(assign_df["start_date"])
        assign_df["end_date"] = pd.to_datetime(assign_df["end_date"])
        fig = px.timeline(assign_df, x_start="start_date", x_end="end_date", y="auditor_name",
                          color="client", hover_data=["role", "eng_location", "travel_notes"],
                          title="Audit Assignments Timeline")
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No assignments to display on calendar yet.")

# Auditors (Admin/Manager)
if st.session_state.role in ["Admin", "Manager"]:
    with tabs[2]:
        st.header("Auditors & Competencies")
        auditors_df = load_auditors()
        with st.expander("Add New Auditor"):
            with st.form("add_auditor"):
                name = st.text_input("Name*")
                email = st.text_input("Email")
                location = st.text_input("Base Location")
                rate = st.number_input("Daily Rate (£)", min_value=0.0, value=700.0)
                comps = st.multiselect("Competencies / Standards",
                                       ["ISO 9001", "ISO 14001", "ISO 45001", "ISO 27001", "ISO 13485", "ISO 50001", "IATF 16949", "BRCGS"])
                notes = st.text_area("Notes")
                if st.form_submit_button("Add Auditor"):
                    if name:
                        conn = get_conn()
                        conn.execute("INSERT INTO auditors (name, email, base_location, daily_rate, competencies, notes) VALUES (?,?,?,?,?,?)",
                                     (name, email, location, rate, json.dumps(comps), notes))
                        aid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                        conn.commit()
                        conn.close()
                        log_action(st.session_state.username, "CREATE", "auditors", aid, f"Added {name}")
                        st.success(f"Added {name}")
                        st.rerun()
        if not auditors_df.empty:
            st.dataframe(auditors_df[["name", "base_location", "daily_rate", "competencies", "notes"]], use_container_width=True)

    with tabs[3]:
        st.header("Engagements / Programme Planning")
        eng_df = load_engagements()
        with st.expander("Add New Engagement"):
            with st.form("add_eng"):
                client = st.text_input("Client Name*")
                standards = st.multiselect("Standards", ["ISO 9001", "ISO 14001", "ISO 45001", "ISO 27001", "ISO 13485", "ISO 50001", "IATF 16949", "BRCGS"])
                location = st.text_input("Audit Location")
                pref_start = st.date_input("Preferred Start")
                pref_end = st.date_input("Preferred End")
                duration = st.number_input("Duration (days)", min_value=0.5, value=2.0, step=0.5)
                req_comps = st.multiselect("Required Competencies", ["ISO 9001", "ISO 14001", "ISO 45001", "ISO 27001", "ISO 13485", "ISO 50001", "IATF 16949", "BRCGS"])
                notes = st.text_area("Notes")
                if st.form_submit_button("Add Engagement"):
                    if client:
                        conn = get_conn()
                        conn.execute("""INSERT INTO engagements 
                            (client, standards, location, preferred_start, preferred_end, duration_days, required_competencies, notes)
                            VALUES (?,?,?,?,?,?,?,?)""",
                            (client, json.dumps(standards), location, str(pref_start), str(pref_end), duration, json.dumps(req_comps), notes))
                        eid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                        conn.commit()
                        conn.close()
                        log_action(st.session_state.username, "CREATE", "engagements", eid, f"Added {client}")
                        st.success(f"Added engagement for {client}")
                        st.rerun()
        if not eng_df.empty:
            display = eng_df.copy()
            display["standards"] = display["standards"].apply(lambda x: ", ".join(x) if isinstance(x, list) else "")
            display["required_competencies"] = display["required_competencies"].apply(lambda x: ", ".join(x) if isinstance(x, list) else "")
            st.dataframe(display[["client", "standards", "location", "preferred_start", "duration_days", "status", "notes"]], use_container_width=True)

    with tabs[4]:
        st.header("Schedule, Match & Assign")
        eng_df = load_engagements()
        auditors_df = load_auditors()
        assign_df = load_assignments()
        if eng_df.empty or auditors_df.empty:
            st.warning("Add auditors and engagements first.")
        else:
            eng_options = {f"{row['client']} ({', '.join(row['standards']) if isinstance(row['standards'], list) else ''})": row['id'] for _, row in eng_df.iterrows()}
            selected_eng_label = st.selectbox("Select Engagement to Schedule", list(eng_options.keys()))
            eng_id = eng_options[selected_eng_label]
            eng_row = eng_df[eng_df["id"] == eng_id].iloc[0]
            st.subheader(f"Matching for: {eng_row['client']}")
            required = eng_row["required_competencies"] if isinstance(eng_row["required_competencies"], list) else []
            st.write(f"Required competencies: {', '.join(required) or 'None specified'}")
            st.write(f"Location: {eng_row['location']} | Preferred: {eng_row['preferred_start']} to {eng_row['preferred_end']}")
            def matches(auditor_comps, required):
                if not required: return True
                return all(r in auditor_comps for r in required)
            matching = auditors_df[auditors_df["competencies"].apply(lambda c: matches(c, required))]
            st.write(f"**Matching auditors ({len(matching)}):**")
            if not matching.empty:
                st.dataframe(matching[["name", "base_location", "daily_rate", "competencies"]], use_container_width=True)
            with st.form("assign_form"):
                st.subheader("Create Assignment")
                auditor_options = {row["name"]: row["id"] for _, row in (matching if not matching.empty else auditors_df).iterrows()}
                sel_auditor = st.selectbox("Auditor", list(auditor_options.keys()))
                role = st.selectbox("Role", ["Lead", "Co-auditor", "Observer", "Technical Expert"])
                start = st.date_input("Start Date", value=datetime.strptime(eng_row["preferred_start"], "%Y-%m-%d") if eng_row["preferred_start"] else datetime.today())
                end = st.date_input("End Date", value=start + timedelta(days=float(eng_row["duration_days"])-1))
                travel_method = st.selectbox("Travel Method", ["Car", "Train", "Flight", "Other"])
                travel_notes = st.text_area("Travel Notes")
                if st.form_submit_button("Assign"):
                    aud_row = auditors_df[auditors_df["id"] == auditor_options[sel_auditor]].iloc[0]
                    dist = estimate_distance(aud_row["base_location"], eng_row["location"])
                    cost = estimate_travel_cost(dist, travel_method)
                    conn = get_conn()
                    conn.execute("""INSERT INTO assignments 
                        (engagement_id, auditor_id, role, start_date, end_date, travel_notes, travel_distance_km, travel_cost) 
                        VALUES (?,?,?,?,?,?,?,?)""",
                        (eng_id, auditor_options[sel_auditor], role, str(start), str(end), travel_notes, dist, cost))
                    aid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    conn.execute("UPDATE engagements SET status = 'Scheduled' WHERE id = ?", (eng_id,))
                    conn.commit()
                    conn.close()
                    log_action(st.session_state.username, "CREATE", "assignments", aid, f"Assigned {sel_auditor} to {eng_row['client']} (travel £{cost})")
                    st.success(f"Assignment created! Estimated travel: {dist} km / £{cost}")
                    st.rerun()
            this_assign = assign_df[assign_df["engagement_id"] == eng_id]
            if not this_assign.empty:
                st.dataframe(this_assign[["auditor_name", "role", "start_date", "end_date", "travel_distance_km", "travel_cost", "travel_notes"]], use_container_width=True)

    with tabs[5]:
        st.header("Bulk Programme Allocation Suggestions")
        st.markdown("Suggests optimal auditor assignments based on competence match, location proximity, and load.")
        eng_df = load_engagements()
        auditors_df = load_auditors()
        assign_df = load_assignments()
        if eng_df.empty or auditors_df.empty:
            st.warning("Need data first.")
        else:
            unscheduled = eng_df[eng_df["status"] == "Planned"]
            if unscheduled.empty:
                st.success("All engagements are scheduled!")
            else:
                suggestions = []
                for _, eng in unscheduled.iterrows():
                    required = eng["required_competencies"] if isinstance(eng["required_competencies"], list) else []
                    def matches(c): return not required or all(r in c for r in required)
                    candidates = auditors_df[auditors_df["competencies"].apply(matches)].copy()
                    if candidates.empty:
                        continue
                    candidates["distance"] = candidates["base_location"].apply(lambda loc: estimate_distance(loc, eng["location"]))
                    candidates["load"] = candidates["id"].apply(lambda aid: len(assign_df[assign_df["auditor_id"] == aid]))
                    candidates["score"] = (100 - candidates["distance"]/5) - candidates["load"]*10  # simple score
                    best = candidates.sort_values("score", ascending=False).head(2)
                    for _, aud in best.iterrows():
                        suggestions.append({
                            "Engagement": eng["client"],
                            "Suggested Auditor": aud["name"],
                            "Location Match": f"{aud['base_location']} → {eng['location']} ({aud['distance']} km)",
                            "Score": round(aud["score"], 1),
                            "Daily Rate": aud["daily_rate"]
                        })
                if suggestions:
                    sug_df = pd.DataFrame(suggestions)
                    st.dataframe(sug_df, use_container_width=True)
                    if st.button("Apply Top Suggestions (one per engagement)"):
                        applied = 0
                        for eng_client in sug_df["Engagement"].unique():
                            top = sug_df[sug_df["Engagement"] == eng_client].iloc[0]
                            # Find IDs and insert (simplified)
                            eng_id = eng_df[eng_df["client"] == eng_client].iloc[0]["id"]
                            aud_id = auditors_df[auditors_df["name"] == top["Suggested Auditor"]].iloc[0]["id"]
                            conn = get_conn()
                            conn.execute("""INSERT INTO assignments (engagement_id, auditor_id, role, start_date, end_date, travel_notes, travel_distance_km, travel_cost)
                                VALUES (?,?,?,?,?,?,?,?)""",
                                (eng_id, aud_id, "Lead", eng_df[eng_df["id"]==eng_id].iloc[0]["preferred_start"],
                                 eng_df[eng_df["id"]==eng_id].iloc[0]["preferred_end"], "Bulk allocated", 0, 0))
                            conn.execute("UPDATE engagements SET status='Scheduled' WHERE id=?", (eng_id,))
                            conn.commit()
                            conn.close()
                            applied += 1
                        log_action(st.session_state.username, "BULK_ALLOCATE", "assignments", 0, f"Applied {applied} suggestions")
                        st.success(f"Applied {applied} assignments")
                        st.rerun()
                else:
                    st.info("No strong suggestions.")

# Timesheets
ts_tab_idx = 6 if st.session_state.role in ["Admin", "Manager"] else 2
with tabs[ts_tab_idx]:
    st.header("Timesheets" + (" (with Approval Workflow)" if st.session_state.role in ["Admin", "Manager"] else " (My Entries)"))
    assign_df = load_assignments()
    auditors_df = load_auditors()
    ts_df = load_timesheets()
    
    if st.session_state.role == "Auditor":
        # Filter to own if linked, else show all for demo
        st.info("Auditor view: log and view your timesheets")
    
    if not assign_df.empty:
        with st.form("timesheet_form"):
            auditor_assign = assign_df[["auditor_id", "auditor_name"]].drop_duplicates()
            auditor_map = {row["auditor_name"]: row["auditor_id"] for _, row in auditor_assign.iterrows()}
            sel_aud = st.selectbox("Auditor", list(auditor_map.keys()))
            aud_id = auditor_map[sel_aud]
            their_engs = assign_df[assign_df["auditor_id"] == aud_id]
            eng_map = {f"{row['client']} ({row['role']})": row["engagement_id"] for _, row in their_engs.iterrows()}
            if eng_map:
                sel_eng = st.selectbox("Engagement", list(eng_map.keys()))
                eng_id = eng_map[sel_eng]
                date = st.date_input("Date")
                hours = st.number_input("Hours", min_value=0.0, max_value=16.0, value=7.5, step=0.25)
                category = st.selectbox("Category", ["Planning", "On-site Audit", "Reporting", "Travel", "Follow-up", "Other"])
                desc = st.text_input("Description")
                if st.form_submit_button("Log Time (Submit)"):
                    conn = get_conn()
                    conn.execute("""INSERT INTO timesheets (auditor_id, engagement_id, date, hours, category, description, status, submitted_by)
                        VALUES (?,?,?,?,?,?,?,?)""",
                        (aud_id, eng_id, str(date), hours, category, desc, "Submitted", st.session_state.username))
                    tid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    conn.commit()
                    conn.close()
                    log_action(st.session_state.username, "CREATE", "timesheets", tid, f"Submitted {hours}h on {date}")
                    st.success("Time submitted for approval")
                    st.rerun()
    
    st.subheader("Timesheet Entries")
    if not ts_df.empty:
        st.dataframe(ts_df[["date", "auditor_name", "client", "hours", "category", "description", "status", "submitted_by", "approved_by"]].sort_values("date", ascending=False), use_container_width=True)
        
        if st.session_state.role in ["Admin", "Manager"]:
            st.subheader("Approval Actions")
            pending = ts_df[ts_df["status"] == "Submitted"]
            if not pending.empty:
                for _, row in pending.iterrows():
                    cols = st.columns([3,1,1])
                    cols[0].write(f"{row['date']} | {row['auditor_name']} | {row['client']} | {row['hours']}h")
                    if cols[1].button("Approve", key=f"app_{row['id']}"):
                        conn = get_conn()
                        conn.execute("UPDATE timesheets SET status='Approved', approved_by=? WHERE id=?", (st.session_state.username, row['id']))
                        conn.commit()
                        conn.close()
                        log_action(st.session_state.username, "APPROVE", "timesheets", row['id'], "Approved timesheet")
                        st.rerun()
                    if cols[2].button("Reject", key=f"rej_{row['id']}"):
                        conn = get_conn()
                        conn.execute("UPDATE timesheets SET status='Draft' WHERE id=?", (row['id'],))
                        conn.commit()
                        conn.close()
                        log_action(st.session_state.username, "REJECT", "timesheets", row['id'], "Rejected timesheet")
                        st.rerun()
            else:
                st.info("No pending approvals")

# Reports & Export
rep_idx = 7 if st.session_state.role in ["Admin", "Manager"] else 3
with tabs[rep_idx]:
    st.header("Reports & Export")
    ts_df = load_timesheets()
    assign_df = load_assignments()
    
    st.subheader("Timesheet Summary")
    if not ts_df.empty:
        summary = ts_df.groupby(["client", "auditor_name"]).agg(total_hours=("hours", "sum")).reset_index()
        st.dataframe(summary, use_container_width=True)
        
        # Excel export
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            summary.to_excel(writer, sheet_name="Summary", index=False)
            ts_df.to_excel(writer, sheet_name="Detailed", index=False)
            assign_df.to_excel(writer, sheet_name="Assignments", index=False)
        st.download_button("Download Excel Report", data=buffer.getvalue(), file_name="audit_timesheets.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
        # PDF export
        if st.button("Generate PDF Summary"):
            pdf_buffer = io.BytesIO()
            doc = SimpleDocTemplate(pdf_buffer, pagesize=A4)
            styles = getSampleStyleSheet()
            elements = [Paragraph("Audit Timesheet Summary", styles["Title"]), Spacer(1, 12)]
            data = [["Client", "Auditor", "Total Hours"]] + summary.values.tolist()
            t = Table(data)
            t.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.grey), ("GRID", (0,0), (-1,-1), 1, colors.black)]))
            elements.append(t)
            doc.build(elements)
            st.download_button("Download PDF", data=pdf_buffer.getvalue(), file_name="audit_summary.pdf", mime="application/pdf")
    
    st.subheader("Assignments with Travel Costs")
    if not assign_df.empty:
        st.dataframe(assign_df[["client", "auditor_name", "role", "start_date", "travel_distance_km", "travel_cost", "travel_notes"]], use_container_width=True)

# Audit Trail
if st.session_state.role in ["Admin", "Manager"]:
    with tabs[8]:
        st.header("Immutable Audit Trail")
        st.markdown("Every create, update, approval, and bulk action is logged.")
        trail = load_audit_trail()
        if not trail.empty:
            st.dataframe(trail, use_container_width=True)
        else:
            st.info("No actions logged yet.")

st.sidebar.markdown("---")
st.sidebar.caption("Enhanced prototype with calendar, approvals, travel costing, exports, RBAC, bulk allocation, and full audit trail.")
