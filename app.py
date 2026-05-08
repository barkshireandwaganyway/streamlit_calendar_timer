import json
import re
import time
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ============================================================
# Lovely Grooming Calendar Appointment Timer
# Google Calendar -> Streamlit -> Google Sheets Daily Log
# ============================================================

st.set_page_config(
    page_title="Lovely Grooming Appointment Timer",
    page_icon="⏱️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

LOCAL_TZ = ZoneInfo(st.secrets.get("app", {}).get("timezone", "America/Chicago"))
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

DEFAULT_BATHERS = ["Emily"]
DEFAULT_GROOMERS = ["Kim", "Veronica", "Alex"]

HEADERS = [
    "appointment_id",
    "calendar_id",
    "google_event_id",
    "date",
    "calendar_start",
    "calendar_end",
    "employee_from_calendar",
    "assigned_employee_buttons",
    "appointment_title",
    "service_info",
    "description",
    "location",
    "status",
    "service_start_time",
    "ready_for_pickup_time",
    "service_seconds",
    "picked_up_time",
    "post_service_seconds",
    "notes",
    "last_updated",
]

STATUS_NEW = "NOT_STARTED"
STATUS_STARTED = "IN_SERVICE"
STATUS_READY = "READY_FOR_PICKUP"
STATUS_PICKED_UP = "PICKED_UP"

# -----------------------------
# Styling
# -----------------------------
st.markdown(
    """
    <style>
        .main .block-container { padding-top: 1rem; }
        .appt-card {
            border: 1px solid #ddd;
            border-radius: 16px;
            padding: 14px;
            margin-bottom: 14px;
            background: #ffffff;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }
        .appt-title {
            font-size: 1.05rem;
            font-weight: 800;
            margin-bottom: 4px;
            color: #2c2c2c;
        }
        .appt-meta {
            font-size: 0.9rem;
            color: #555;
            margin-bottom: 8px;
        }
        .status-pill {
            display: inline-block;
            padding: 3px 9px;
            border-radius: 999px;
            background: #800d5c;
            color: white;
            font-size: 0.78rem;
            font-weight: 700;
            margin-top: 4px;
        }
        div.stButton > button {
            border-radius: 12px;
            font-weight: 700;
            min-height: 38px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# Auth and clients
# -----------------------------
@st.cache_resource(show_spinner=False)
def get_credentials():
    raw = dict(st.secrets["gcp_service_account"])
    if "private_key" in raw:
        raw["private_key"] = raw["private_key"].replace("\\n", "\n")
    return Credentials.from_service_account_info(raw, scopes=SCOPES)


@st.cache_resource(show_spinner=False)
def get_calendar_service():
    return build("calendar", "v3", credentials=get_credentials(), cache_discovery=False)


@st.cache_resource(show_spinner=False)
def get_gspread_client():
    return gspread.authorize(get_credentials())


@st.cache_resource(show_spinner=False)
def get_workbook():
    gc = get_gspread_client()
    sheet_id = st.secrets["sheets"]["spreadsheet_id"]
    return gc.open_by_key(sheet_id)

# -----------------------------
# Config helpers
# -----------------------------
def get_employee_config():
    people = st.secrets.get("employees", {})
    bathers = list(people.get("bathers", DEFAULT_BATHERS))
    groomers = list(people.get("groomers", DEFAULT_GROOMERS))
    return bathers, groomers


def get_calendar_config():
    calendars = st.secrets.get("calendars", {})
    ids = calendars.get("calendar_ids", ["primary"])
    if isinstance(ids, str):
        ids = [x.strip() for x in ids.split(",") if x.strip()]
    employee_calendar_map = dict(calendars.get("employee_calendar_map", {}))
    return ids, employee_calendar_map


def now_iso():
    return datetime.now(LOCAL_TZ).replace(microsecond=0).isoformat()


def parse_iso(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=LOCAL_TZ)
        return dt.astimezone(LOCAL_TZ)
    except Exception:
        return None


def seconds_between(start_iso, end_iso):
    start = parse_iso(start_iso)
    end = parse_iso(end_iso)
    if not start or not end:
        return ""
    return max(0, int((end - start).total_seconds()))


def fmt_time(dt_iso_or_obj):
    if not dt_iso_or_obj:
        return ""
    if isinstance(dt_iso_or_obj, str):
        dt = parse_iso(dt_iso_or_obj)
    else:
        dt = dt_iso_or_obj
    if not dt:
        return ""
    return dt.astimezone(LOCAL_TZ).strftime("%-I:%M %p")


def clean_text(value):
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", str(value))
    value = re.sub(r"\s+", " ", value).strip()
    return value

# -----------------------------
# Calendar sync
# -----------------------------
def event_start_end(event):
    start_raw = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
    end_raw = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")
    start = parse_iso(start_raw) if "T" in start_raw else datetime.fromisoformat(start_raw).replace(tzinfo=LOCAL_TZ)
    end = parse_iso(end_raw) if "T" in end_raw else datetime.fromisoformat(end_raw).replace(tzinfo=LOCAL_TZ)
    return start, end


def infer_employee(event, calendar_id, employee_calendar_map, all_employees):
    # 1. Calendar ID mapping is the most reliable when each employee has their own calendar.
    if calendar_id in employee_calendar_map:
        return employee_calendar_map[calendar_id]

    text = " ".join([
        event.get("summary", ""),
        clean_text(event.get("description", "")),
        event.get("location", ""),
        event.get("creator", {}).get("displayName", ""),
        event.get("organizer", {}).get("displayName", ""),
    ]).lower()

    for employee in all_employees:
        if re.search(rf"\b{re.escape(employee.lower())}\b", text):
            return employee
    return "Unassigned"


def fetch_calendar_events(selected_date):
    calendar_service = get_calendar_service()
    calendar_ids, employee_calendar_map = get_calendar_config()
    bathers, groomers = get_employee_config()
    all_employees = bathers + groomers

    day_start = datetime.combine(selected_date, datetime.min.time(), tzinfo=LOCAL_TZ)
    day_end = day_start + timedelta(days=1)

    events = []
    for calendar_id in calendar_ids:
        page_token = None
        while True:
            response = calendar_service.events().list(
                calendarId=calendar_id,
                timeMin=day_start.astimezone(timezone.utc).isoformat(),
                timeMax=day_end.astimezone(timezone.utc).isoformat(),
                singleEvents=True,
                orderBy="startTime",
                pageToken=page_token,
            ).execute()
            for event in response.get("items", []):
                if event.get("status") == "cancelled":
                    continue
                start, end = event_start_end(event)
                employee = infer_employee(event, calendar_id, employee_calendar_map, all_employees)
                appointment_id = f"{calendar_id}::{event.get('id')}::{selected_date.isoformat()}"
                events.append({
                    "appointment_id": appointment_id,
                    "calendar_id": calendar_id,
                    "google_event_id": event.get("id", ""),
                    "date": selected_date.isoformat(),
                    "calendar_start": start.isoformat(),
                    "calendar_end": end.isoformat(),
                    "employee_from_calendar": employee,
                    "assigned_employee_buttons": employee if employee != "Unassigned" else "",
                    "appointment_title": event.get("summary", "Untitled appointment"),
                    "service_info": extract_service_info(event),
                    "description": clean_text(event.get("description", "")),
                    "location": event.get("location", ""),
                    "status": STATUS_NEW,
                    "service_start_time": "",
                    "ready_for_pickup_time": "",
                    "service_seconds": "",
                    "picked_up_time": "",
                    "post_service_seconds": "",
                    "notes": "",
                    "last_updated": now_iso(),
                })
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    events.sort(key=lambda x: x["calendar_start"])
    return events


def extract_service_info(event):
    text = clean_text(event.get("description", ""))
    summary = event.get("summary", "")
    # Basic fallback: Square/Calendar entries often put service in title or description.
    service_matches = re.findall(r"(?:service|appointment type|booking)[:\-]\s*([^\n\|]+)", text, flags=re.I)
    if service_matches:
        return service_matches[0].strip()
    return summary

# -----------------------------
# Sheets sync
# -----------------------------
def sheet_name_for(selected_date):
    return selected_date.strftime("%Y-%m-%d")


def get_or_create_day_sheet(selected_date):
    wb = get_workbook()
    title = sheet_name_for(selected_date)
    try:
        ws = wb.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = wb.add_worksheet(title=title, rows=1000, cols=len(HEADERS) + 3)
        ws.append_row(HEADERS)
        ws.freeze(rows=1)
    existing_headers = ws.row_values(1)
    if existing_headers != HEADERS:
        ws.resize(cols=max(len(HEADERS), len(existing_headers)))
        ws.update("A1", [HEADERS])
    return ws


def load_day_log(selected_date):
    ws = get_or_create_day_sheet(selected_date)
    values = ws.get_all_records(expected_headers=HEADERS)
    df = pd.DataFrame(values)
    if df.empty:
        df = pd.DataFrame(columns=HEADERS)
    for col in HEADERS:
        if col not in df.columns:
            df[col] = ""
    return ws, df[HEADERS]


def save_day_log(selected_date, df):
    ws = get_or_create_day_sheet(selected_date)
    df = df.fillna("")
    ws.clear()
    ws.update("A1", [HEADERS] + df[HEADERS].values.tolist())
    ws.freeze(rows=1)


def sync_events_to_sheet(selected_date):
    events = fetch_calendar_events(selected_date)
    ws, df = load_day_log(selected_date)

    if df.empty:
        df = pd.DataFrame(columns=HEADERS)

    existing_ids = set(df["appointment_id"].astype(str).tolist()) if not df.empty else set()
    new_rows = []
    for event in events:
        if event["appointment_id"] not in existing_ids:
            new_rows.append(event)
        else:
            idx = df.index[df["appointment_id"] == event["appointment_id"]][0]
            # Keep clock/status/notes fields, but refresh live calendar fields.
            calendar_fields = [
                "calendar_id", "google_event_id", "date", "calendar_start", "calendar_end",
                "employee_from_calendar", "appointment_title", "service_info", "description", "location"
            ]
            for field in calendar_fields:
                df.at[idx, field] = event[field]
            if not df.at[idx, "assigned_employee_buttons"]:
                df.at[idx, "assigned_employee_buttons"] = event["assigned_employee_buttons"]
            df.at[idx, "last_updated"] = now_iso()

    if new_rows:
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)

    if not df.empty:
        df = df[HEADERS].sort_values(["calendar_start", "appointment_title"], kind="stable")

    save_day_log(selected_date, df)
    return df


def update_row(selected_date, appointment_id, updates):
    _, df = load_day_log(selected_date)
    mask = df["appointment_id"] == appointment_id
    if not mask.any():
        return
    idx = df.index[mask][0]
    for key, value in updates.items():
        df.at[idx, key] = value
    df.at[idx, "last_updated"] = now_iso()
    save_day_log(selected_date, df)

# -----------------------------
# Streamlit state/action handlers
# -----------------------------
def start_service(selected_date, row):
    if row.get("status") in [STATUS_STARTED, STATUS_READY, STATUS_PICKED_UP]:
        return
    update_row(selected_date, row["appointment_id"], {
        "status": STATUS_STARTED,
        "service_start_time": now_iso(),
    })


def ready_for_pickup(selected_date, row):
    ready_time = now_iso()
    updates = {
        "status": STATUS_READY,
        "ready_for_pickup_time": ready_time,
        "service_seconds": seconds_between(row.get("service_start_time"), ready_time),
    }
    if not row.get("service_start_time"):
        # If someone skipped START, still record READY and leave service duration blank.
        updates["service_seconds"] = ""
    update_row(selected_date, row["appointment_id"], updates)
    st.session_state["notes_prompt_appt"] = row["appointment_id"]


def picked_up(selected_date, row):
    picked_time = now_iso()
    update_row(selected_date, row["appointment_id"], {
        "status": STATUS_PICKED_UP,
        "picked_up_time": picked_time,
        "post_service_seconds": seconds_between(row.get("ready_for_pickup_time"), picked_time),
    })


def save_notes(selected_date, appointment_id, notes):
    update_row(selected_date, appointment_id, {"notes": notes})


def toggle_employee(selected_date, row, employee):
    current = [x.strip() for x in str(row.get("assigned_employee_buttons", "")).split(",") if x.strip()]
    if employee in current:
        current.remove(employee)
    else:
        current.append(employee)
    update_row(selected_date, row["appointment_id"], {"assigned_employee_buttons": ", ".join(current)})

# -----------------------------
# Modal notes prompt
# -----------------------------
def show_notes_prompt(selected_date, row):
    appt_id = row["appointment_id"]

    if hasattr(st, "dialog"):
        @st.dialog("Would you like to add notes?")
        def notes_dialog():
            st.write(row.get("appointment_title", "Appointment"))
            col_yes, col_no = st.columns(2)
            if col_yes.button("Yes, add notes", key=f"yes_notes_{appt_id}"):
                st.session_state[f"show_notes_box_{appt_id}"] = True
                st.session_state.pop("notes_prompt_appt", None)
                st.rerun()
            if col_no.button("No notes", key=f"no_notes_{appt_id}"):
                st.session_state.pop("notes_prompt_appt", None)
                st.rerun()
        notes_dialog()
    else:
        st.warning("Would you like to add notes?")
        col_yes, col_no = st.columns(2)
        if col_yes.button("Yes, add notes", key=f"yes_notes_{appt_id}"):
            st.session_state[f"show_notes_box_{appt_id}"] = True
            st.session_state.pop("notes_prompt_appt", None)
            st.rerun()
        if col_no.button("No notes", key=f"no_notes_{appt_id}"):
            st.session_state.pop("notes_prompt_appt", None)
            st.rerun()

# -----------------------------
# UI rendering
# -----------------------------
def render_employee_buttons(selected_date, row, employees):
    selected = [x.strip() for x in str(row.get("assigned_employee_buttons", "")).split(",") if x.strip()]
    cols = st.columns(max(1, min(4, len(employees))))
    for i, employee in enumerate(employees):
        label = f"✓ {employee}" if employee in selected else employee
        if cols[i % len(cols)].button(label, key=f"emp_{row['appointment_id']}_{employee}"):
            toggle_employee(selected_date, row, employee)
            st.rerun()


def render_appointment_card(selected_date, row, employees):
    appt_id = row["appointment_id"]
    title = row.get("appointment_title", "Untitled appointment")
    start = fmt_time(row.get("calendar_start"))
    end = fmt_time(row.get("calendar_end"))
    service = row.get("service_info", "")
    status = row.get("status", STATUS_NEW) or STATUS_NEW

    st.markdown("<div class='appt-card'>", unsafe_allow_html=True)
    st.markdown(f"<div class='appt-title'>{title}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='appt-meta'>{start} - {end}</div>", unsafe_allow_html=True)
    if service and service != title:
        st.caption(service)
    st.markdown(f"<span class='status-pill'>{status.replace('_', ' ')}</span>", unsafe_allow_html=True)

    st.write("")
    render_employee_buttons(selected_date, row, employees)

    action_cols = st.columns(4)
    start_disabled = status in [STATUS_STARTED, STATUS_READY, STATUS_PICKED_UP]
    ready_disabled = status in [STATUS_NEW, STATUS_READY, STATUS_PICKED_UP]
    pickup_disabled = status != STATUS_READY

    if action_cols[0].button("START", key=f"start_{appt_id}", disabled=start_disabled):
        start_service(selected_date, row)
        st.rerun()

    if action_cols[1].button("READY FOR PICKUP", key=f"ready_{appt_id}", disabled=ready_disabled):
        ready_for_pickup(selected_date, row)
        st.rerun()

    if action_cols[2].button("NOTES", key=f"notes_btn_{appt_id}"):
        st.session_state[f"show_notes_box_{appt_id}"] = not st.session_state.get(f"show_notes_box_{appt_id}", False)
        st.rerun()

    if action_cols[3].button("PICKED UP", key=f"pickup_{appt_id}", disabled=pickup_disabled):
        picked_up(selected_date, row)
        st.rerun()

    if st.session_state.get(f"show_notes_box_{appt_id}", False):
        existing_notes = row.get("notes", "")
        notes = st.text_area("Appointment notes", value=existing_notes, key=f"notes_text_{appt_id}", height=100)
        note_cols = st.columns([1, 3])
        if note_cols[0].button("Save notes", key=f"save_notes_{appt_id}"):
            save_notes(selected_date, appt_id, notes)
            st.session_state[f"show_notes_box_{appt_id}"] = False
            st.success("Notes saved.")
            time.sleep(0.5)
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def render_board(selected_date, df):
    bathers, groomers = get_employee_config()
    employees = bathers + groomers

    active_df = df[df["status"].fillna(STATUS_NEW) != STATUS_PICKED_UP].copy()
    if active_df.empty:
        st.info("No active appointments for this day.")
        return

    # Make one column per employee plus Unassigned.
    employee_columns = employees + ["Unassigned"]
    cols = st.columns(len(employee_columns))

    for col, employee in zip(cols, employee_columns):
        with col:
            st.subheader(employee)
            if employee == "Unassigned":
                emp_df = active_df[
                    (active_df["employee_from_calendar"].fillna("") == "Unassigned") &
                    (active_df["assigned_employee_buttons"].fillna("") == "")
                ]
            else:
                emp_df = active_df[
                    active_df["assigned_employee_buttons"].fillna("").str.contains(rf"\b{re.escape(employee)}\b", case=False, regex=True) |
                    active_df["employee_from_calendar"].fillna("").str.contains(rf"\b{re.escape(employee)}\b", case=False, regex=True)
                ]
            emp_df = emp_df.sort_values("calendar_start")
            if emp_df.empty:
                st.caption("No appointments")
            for _, row in emp_df.iterrows():
                render_appointment_card(selected_date, row.to_dict(), employees)

# -----------------------------
# Main app
# -----------------------------
st.title("Lovely Grooming Appointment Timer")
st.caption("Calendar appointments are pulled into a daily Google Sheets log. Buttons record service and pickup timing.")

selected_date = st.date_input("Date", value=date.today())
left, right = st.columns([1, 4])
with left:
    if st.button("Sync calendar", use_container_width=True):
        with st.spinner("Syncing calendar appointments..."):
            sync_events_to_sheet(selected_date)
        st.rerun()
with right:
    auto_sync = st.toggle("Auto-sync on refresh", value=True)

try:
    if auto_sync:
        df = sync_events_to_sheet(selected_date)
    else:
        _, df = load_day_log(selected_date)

    prompt_id = st.session_state.get("notes_prompt_appt")
    if prompt_id:
        match = df[df["appointment_id"] == prompt_id]
        if not match.empty:
            show_notes_prompt(selected_date, match.iloc[0].to_dict())

    render_board(selected_date, df)

    with st.expander("Backend daily sheet preview"):
        st.dataframe(df, use_container_width=True, hide_index=True)

except Exception as exc:
    st.error("The app could not load. Check Google credentials, shared calendar access, and spreadsheet sharing.")
    st.exception(exc)
