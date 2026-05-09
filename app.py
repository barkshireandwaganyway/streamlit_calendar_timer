import re
import time
import uuid
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ============================================================
# Lovely Grooming Appointment Timer
# Calendar Sync ON/OFF + Manual Appointment Entry
# Google Calendar / Manual Entry -> Streamlit -> Google Sheets Daily Log
# ============================================================

st.set_page_config(
    page_title="Lovely Grooming Appointment Timer",
    page_icon="⏱️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# -----------------------------
# Secrets compatibility helpers
# Supports both older/nested secrets and simple top-level secrets.
# -----------------------------
def secret_get(*path, default=None):
    current = st.secrets
    try:
        for key in path:
            current = current[key]
        return current
    except Exception:
        return default

LOCAL_TZ_NAME = (
    secret_get("app", "timezone", default=None)
    or secret_get("APP_TIMEZONE", default=None)
    or "America/Chicago"
)
LOCAL_TZ = ZoneInfo(LOCAL_TZ_NAME)

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

DEFAULT_GROOMERS = ["Kim", "Veronica", "Alex"]
DEFAULT_BATHERS = ["Bather1", "Bather 2", "Bather 3"]
DEFAULT_STAFF = DEFAULT_GROOMERS + DEFAULT_BATHERS

DOG_SIZES = ["", "Small", "Medium", "Large", "XL", "XXL", "XXXL"]
SERVICES = [
    "Bath",
    "De-shed",
    "De-shed + Classic cleanup",
    "Full haircut",
]
ADD_ON_ITEMS = [
    "Anal gland expression",
    "Ear plucking cleaning",
    "Nail trim",
]

HEADERS = [
    "appointment_id",
    "entry_source",
    "calendar_id",
    "google_event_id",
    "date",
    "calendar_start",
    "calendar_end",
    "employee_from_calendar",
    "assigned_employee_buttons",
    "appointment_title",
    "customer_name",
    "pet_name",
    "dog_size",
    "service_info",
    "selected_services",
    "add_on_items",
    "specific_shampoo_conditioner",
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
        .manual-pill, .calendar-pill, .status-pill {
            display: inline-block;
            padding: 3px 9px;
            border-radius: 999px;
            color: white;
            font-size: 0.78rem;
            font-weight: 700;
            margin: 4px 4px 4px 0;
        }
        .status-pill { background: #800d5c; }
        .manual-pill { background: #555; }
        .calendar-pill { background: #1f6feb; }
        div.stButton > button {
            border-radius: 12px;
            font-weight: 700;
            min-height: 42px;
            white-space: nowrap !important;
            padding-left: 0.85rem;
            padding-right: 0.85rem;
        }
        /* Keeps appointment columns readable instead of crushing the buttons. */
        [data-testid="stHorizontalBlock"] {
            gap: 0.85rem;
        }
        [data-testid="column"] {
            min-width: 230px;
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
    raw = secret_get("gcp_service_account", default=None)
    if raw is None:
        raw = secret_get("google_service_account", default=None)
    if raw is None:
        raise RuntimeError("Missing service account secrets. Add [google_service_account] to Streamlit secrets.")
    raw = dict(raw)
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
    sheet_id = secret_get("sheets", "spreadsheet_id", default=None) or secret_get("SPREADSHEET_ID", default=None)
    if not sheet_id:
        raise RuntimeError("Missing SPREADSHEET_ID in Streamlit secrets.")
    return gc.open_by_key(sheet_id)

# -----------------------------
# Config helpers
# -----------------------------
def get_employee_config():
    employees = secret_get("employees", default={}) or {}
    bathers = list(employees.get("bathers", DEFAULT_BATHERS))
    groomers = list(employees.get("groomers", DEFAULT_GROOMERS))

    # Force your requested defaults if secrets are not configured.
    if not bathers:
        bathers = DEFAULT_BATHERS
    if not groomers:
        groomers = DEFAULT_GROOMERS

    return bathers, groomers


def get_staff_list():
    bathers, groomers = get_employee_config()
    return groomers + bathers


def get_calendar_config():
    # New simple format:
    # [employee_calendars]
    # Kim = "calendar-id"
    simple_map = secret_get("employee_calendars", default=None)
    if simple_map:
        employee_calendar_map = {v: k for k, v in dict(simple_map).items() if v}
        calendar_ids = [v for v in dict(simple_map).values() if v]
        return calendar_ids, employee_calendar_map

    # Older nested format.
    calendars = secret_get("calendars", default={}) or {}
    ids = calendars.get("calendar_ids", [])
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
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
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


def fmt_duration(seconds):
    try:
        seconds = int(float(seconds))
    except Exception:
        return ""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


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
    if not start_raw:
        start = datetime.now(LOCAL_TZ)
    elif "T" in start_raw:
        start = parse_iso(start_raw)
    else:
        start = datetime.fromisoformat(start_raw).replace(tzinfo=LOCAL_TZ)

    if not end_raw:
        end = start + timedelta(hours=1)
    elif "T" in end_raw:
        end = parse_iso(end_raw)
    else:
        end = datetime.fromisoformat(end_raw).replace(tzinfo=LOCAL_TZ)
    return start, end


def infer_employee(event, calendar_id, employee_calendar_map, all_employees):
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


def extract_service_info(event):
    text = clean_text(event.get("description", ""))
    summary = event.get("summary", "")
    service_matches = re.findall(r"(?:service|appointment type|booking)[:\-]\s*([^\n\|]+)", text, flags=re.I)
    if service_matches:
        return service_matches[0].strip()
    return summary


def fetch_calendar_events(selected_date):
    calendar_ids, employee_calendar_map = get_calendar_config()
    if not calendar_ids:
        return []

    calendar_service = get_calendar_service()
    all_employees = get_staff_list()

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
                appointment_id = f"calendar::{calendar_id}::{event.get('id')}::{selected_date.isoformat()}"
                events.append({
                    "appointment_id": appointment_id,
                    "entry_source": "Calendar",
                    "calendar_id": calendar_id,
                    "google_event_id": event.get("id", ""),
                    "date": selected_date.isoformat(),
                    "calendar_start": start.isoformat(),
                    "calendar_end": end.isoformat(),
                    "employee_from_calendar": employee,
                    "assigned_employee_buttons": employee if employee != "Unassigned" else "",
                    "appointment_title": event.get("summary", "Untitled appointment"),
                    "customer_name": "",
                    "pet_name": "",
                    "dog_size": "",
                    "service_info": extract_service_info(event),
                    "selected_services": "",
                    "add_on_items": "",
                    "specific_shampoo_conditioner": "",
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
        ws = wb.add_worksheet(title=title, rows=1000, cols=len(HEADERS) + 5)
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
    for col in HEADERS:
        if col not in df.columns:
            df[col] = ""
    # Keep everything as text in the sheet. This prevents pandas/Streamlit dtype
    # errors when elapsed seconds are written after the sheet originally loaded
    # those columns as blank strings.
    df = df[HEADERS].astype(str)
    ws.clear()
    ws.update("A1", [HEADERS] + df.values.tolist())
    ws.freeze(rows=1)


def sync_events_to_sheet(selected_date):
    events = fetch_calendar_events(selected_date)
    _, df = load_day_log(selected_date)

    if df.empty:
        df = pd.DataFrame(columns=HEADERS)

    existing_ids = set(df["appointment_id"].astype(str).tolist()) if not df.empty else set()
    new_rows = []

    for event in events:
        if event["appointment_id"] not in existing_ids:
            new_rows.append(event)
        else:
            idx = df.index[df["appointment_id"] == event["appointment_id"]][0]
            calendar_fields = [
                "entry_source",
                "calendar_id",
                "google_event_id",
                "date",
                "calendar_start",
                "calendar_end",
                "employee_from_calendar",
                "appointment_title",
                "service_info",
                "description",
                "location",
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
    mask = df["appointment_id"].astype(str) == str(appointment_id)
    if not mask.any():
        return
    idx = df.index[mask][0]
    for key, value in updates.items():
        if key in df.columns:
            df.at[idx, key] = "" if value is None else str(value)
    df.at[idx, "last_updated"] = now_iso()
    save_day_log(selected_date, df)


def add_manual_appointment(selected_date, form_data):
    _, df = load_day_log(selected_date)

    start_dt = datetime.combine(selected_date, form_data["start_time"], tzinfo=LOCAL_TZ)
    end_dt = datetime.combine(selected_date, form_data["end_time"], tzinfo=LOCAL_TZ)
    if end_dt <= start_dt:
        end_dt = start_dt + timedelta(hours=1)

    customer = form_data.get("customer_name", "").strip()
    pet = form_data.get("pet_name", "").strip()
    title_parts = [x for x in [pet, customer] if x]
    appointment_title = " - ".join(title_parts) if title_parts else "Manual Appointment"

    selected_services = ", ".join(form_data.get("selected_services", []))
    add_ons = ", ".join(form_data.get("add_on_items", []))
    shampoo = form_data.get("specific_shampoo_conditioner", "").strip()

    service_bits = []
    if selected_services:
        service_bits.append(selected_services)
    if add_ons:
        service_bits.append(f"Add-ons: {add_ons}")
    if shampoo:
        service_bits.append(f"Specific shampoo/conditioner: {shampoo}")
    service_info = " | ".join(service_bits)

    assigned_staff_list = form_data.get("assigned_staff", []) or []
    assigned_staff = ", ".join(assigned_staff_list)
    display_employee = assigned_staff_list[0] if assigned_staff_list else "Unassigned"

    row = {
        "appointment_id": f"manual::{selected_date.isoformat()}::{uuid.uuid4().hex[:12]}",
        "entry_source": "Manual",
        "calendar_id": "",
        "google_event_id": "",
        "date": selected_date.isoformat(),
        "calendar_start": start_dt.isoformat(),
        "calendar_end": end_dt.isoformat(),
        "employee_from_calendar": display_employee,
        "assigned_employee_buttons": assigned_staff,
        "appointment_title": appointment_title,
        "customer_name": customer,
        "pet_name": pet,
        "dog_size": form_data.get("dog_size", ""),
        "service_info": service_info,
        "selected_services": selected_services,
        "add_on_items": add_ons,
        "specific_shampoo_conditioner": shampoo,
        "description": "Manual appointment entry",
        "location": "",
        "status": STATUS_NEW,
        "service_start_time": "",
        "ready_for_pickup_time": "",
        "service_seconds": "",
        "picked_up_time": "",
        "post_service_seconds": "",
        "notes": form_data.get("notes", "").strip(),
        "last_updated": now_iso(),
    }

    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df = df[HEADERS].sort_values(["calendar_start", "appointment_title"], kind="stable")
    save_day_log(selected_date, df)

# -----------------------------
# Action handlers
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
# Manual appointment form
# -----------------------------
def render_manual_entry_form(selected_date):
    with st.expander("Add Appointment", expanded=False):
        with st.form("manual_appointment_form", clear_on_submit=True):
            st.subheader("Manual Appointment Entry")
            st.caption("Nothing here is required. Add only what you know and the appointment will still be created.")

            col1, col2, col3 = st.columns(3)
            customer_name = col1.text_input("Customer name")
            pet_name = col2.text_input("Dog name")
            dog_size = col3.selectbox("Dog size", DOG_SIZES, index=0)

            col4, col5 = st.columns(2)
            default_start = datetime.now(LOCAL_TZ).replace(second=0, microsecond=0).time()
            default_end_dt = (datetime.combine(date.today(), default_start) + timedelta(hours=1)).time()
            start_time = col4.time_input("Appointment start time", value=default_start)
            end_time = col5.time_input("Appointment end time", value=default_end_dt)

            assigned_staff = st.multiselect("Staff buttons to pre-select", get_staff_list())
            selected_services = st.multiselect("Services", SERVICES)
            add_on_items = st.multiselect("Items / add-ons", ADD_ON_ITEMS)
            specific_shampoo_conditioner = st.text_input("Specific shampoo or conditioner")
            notes = st.text_area("Specific notes", height=90)

            submitted = st.form_submit_button("Add Appointment", use_container_width=True)
            if submitted:
                add_manual_appointment(selected_date, {
                    "customer_name": customer_name,
                    "pet_name": pet_name,
                    "dog_size": dog_size,
                    "start_time": start_time,
                    "end_time": end_time,
                    "assigned_staff": assigned_staff,
                    "selected_services": selected_services,
                    "add_on_items": add_on_items,
                    "specific_shampoo_conditioner": specific_shampoo_conditioner,
                    "notes": notes,
                })
                st.success("Appointment added.")
                time.sleep(0.5)
                st.rerun()

# -----------------------------
# Notes prompt
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
    if not employees:
        return
    cols = st.columns(max(1, min(3, len(employees))))
    for i, employee in enumerate(employees):
        label = f"✓ {employee}" if employee in selected else employee
        if cols[i % len(cols)].button(label, key=f"emp_{row['appointment_id']}_{employee}", use_container_width=True):
            toggle_employee(selected_date, row, employee)
            st.rerun()


def get_display_employee(row, employees):
    """Return the single board column this appointment should live under.

    The employee buttons can contain multiple people for tracking, but the card
    should only render once. Calendar/manual creation sets employee_from_calendar
    as the anchor column. If that is missing, use the first selected employee.
    """
    anchor = str(row.get("employee_from_calendar", "") or "").strip()
    if anchor in employees:
        return anchor

    selected = [x.strip() for x in str(row.get("assigned_employee_buttons", "")).split(",") if x.strip()]
    for employee in selected:
        if employee in employees:
            return employee

    return "Unassigned"


def render_appointment_card(selected_date, row, employees):
    appt_id = row["appointment_id"]
    title = row.get("appointment_title", "Untitled appointment") or "Untitled appointment"
    start = fmt_time(row.get("calendar_start"))
    end = fmt_time(row.get("calendar_end"))
    service = row.get("service_info", "")
    status = row.get("status", STATUS_NEW) or STATUS_NEW
    source = row.get("entry_source", "") or "Calendar"
    dog_size = row.get("dog_size", "")

    st.markdown("<div class='appt-card'>", unsafe_allow_html=True)
    st.markdown(f"<div class='appt-title'>{title}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='appt-meta'>{start} - {end}</div>", unsafe_allow_html=True)

    pill_class = "manual-pill" if source == "Manual" else "calendar-pill"
    st.markdown(
        f"<span class='{pill_class}'>{source}</span><span class='status-pill'>{status.replace('_', ' ')}</span>",
        unsafe_allow_html=True,
    )

    details = []
    if dog_size:
        details.append(f"Size: {dog_size}")
    if service and service != title:
        details.append(service)
    if details:
        st.caption(" | ".join(details))

    render_employee_buttons(selected_date, row, employees)

    start_disabled = status in [STATUS_STARTED, STATUS_READY, STATUS_PICKED_UP]
    ready_disabled = status in [STATUS_NEW, STATUS_READY, STATUS_PICKED_UP]
    pickup_disabled = status != STATUS_READY

    action_row_1 = st.columns([1, 2.4])
    if action_row_1[0].button("START", key=f"start_{appt_id}", disabled=start_disabled, use_container_width=True):
        start_service(selected_date, row)
        st.rerun()

    if action_row_1[1].button("READY FOR PICKUP", key=f"ready_{appt_id}", disabled=ready_disabled, use_container_width=True):
        ready_for_pickup(selected_date, row)
        st.rerun()

    action_row_2 = st.columns([1, 1.4])
    if action_row_2[0].button("NOTES", key=f"notes_btn_{appt_id}", use_container_width=True):
        st.session_state[f"show_notes_box_{appt_id}"] = not st.session_state.get(f"show_notes_box_{appt_id}", False)
        st.rerun()

    if action_row_2[1].button("PICKED UP", key=f"pickup_{appt_id}", disabled=pickup_disabled, use_container_width=True):
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
            time.sleep(0.4)
            st.rerun()

    if status == STATUS_READY:
        st.caption("Post-service timer is running in the backend until PICKED UP is pressed.")

    st.markdown("</div>", unsafe_allow_html=True)


def render_board(selected_date, df):
    employees = get_staff_list()
    active_df = df[df["status"].fillna(STATUS_NEW) != STATUS_PICKED_UP].copy()

    if active_df.empty:
        st.info("No active appointments for this day.")
        return

    employee_columns = employees + ["Unassigned"]
    cols = st.columns(len(employee_columns))

    for col, employee in zip(cols, employee_columns):
        with col:
            st.subheader(employee)
            if employee == "Unassigned":
                emp_df = active_df[
                    active_df["assigned_employee_buttons"].fillna("").astype(str).str.strip().eq("")
                ]
            else:
                emp_df = active_df[
                    active_df["assigned_employee_buttons"].fillna("").astype(str).str.contains(
                        rf"\b{re.escape(employee)}\b", case=False, regex=True
                    )
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
st.caption("Use calendar sync when available, or turn it off and add appointments manually.")

selected_date = st.date_input("Date", value=date.today())

if "calendar_sync_enabled" not in st.session_state:
    st.session_state["calendar_sync_enabled"] = True

control_cols = st.columns([1.4, 1, 1, 3])
with control_cols[0]:
    sync_enabled = st.toggle(
        "Sync with calendar",
        value=st.session_state["calendar_sync_enabled"],
        help="Turn this off when calendar access is not working or you want to enter appointments manually.",
    )
    st.session_state["calendar_sync_enabled"] = sync_enabled

manual_refresh_clicked = False
with control_cols[1]:
    if st.button("Refresh", use_container_width=True):
        manual_refresh_clicked = True

with control_cols[2]:
    if sync_enabled and st.button("Sync now", use_container_width=True):
        st.session_state["force_sync_now"] = True

try:
    if sync_enabled:
        with st.spinner("Syncing calendar appointments..."):
            df = sync_events_to_sheet(selected_date)
        st.success("Calendar sync is ON. Same-day appointments can be pulled in with Refresh or Sync now.")
    else:
        _, df = load_day_log(selected_date)
        st.warning("Calendar sync is OFF. Use Add Appointment for manual entries.")
        render_manual_entry_form(selected_date)

    prompt_id = st.session_state.get("notes_prompt_appt")
    if prompt_id:
        match = df[df["appointment_id"] == prompt_id]
        if not match.empty:
            show_notes_prompt(selected_date, match.iloc[0].to_dict())

    render_board(selected_date, df)

    with st.expander("Backend daily sheet preview"):
        preview = df.copy()
        if not preview.empty:
            if "service_seconds" in preview.columns:
                preview["service_duration"] = preview["service_seconds"].apply(fmt_duration)
            if "post_service_seconds" in preview.columns:
                preview["post_service_duration"] = preview["post_service_seconds"].apply(fmt_duration)
        st.dataframe(preview, use_container_width=True, hide_index=True)

except Exception as exc:
    st.error("The app could not load. Check Google credentials, spreadsheet sharing, and calendar sharing if sync is ON.")
    st.exception(exc)
