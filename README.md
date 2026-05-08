# Lovely Grooming Streamlit Calendar Appointment Timer

This app reads appointments from Google Calendar, displays them in employee columns, and logs START, READY FOR PICKUP, PICKED UP, employee button selections, and optional notes into a Google Sheets workbook.

## Files

- `app.py` - Streamlit app
- `requirements.txt` - Python dependencies
- `.streamlit/secrets.toml.example` - copy to `.streamlit/secrets.toml` locally, or paste into Streamlit Cloud Secrets

## Google setup

1. Create a Google Cloud project.
2. Enable these APIs:
   - Google Calendar API
   - Google Sheets API
   - Google Drive API
3. Create a Service Account.
4. Create a JSON key for the Service Account.
5. Copy the JSON fields into Streamlit secrets.
6. Share the Google Calendar with the Service Account email.
   - Permission needed: See all event details.
7. Create a Google Sheets workbook.
8. Share the workbook with the Service Account email.
   - Permission needed: Editor.
9. Paste the Sheet ID into `spreadsheet_id`.

## GitHub / Streamlit Cloud setup

1. Create a GitHub repository.
2. Upload `app.py`, `requirements.txt`, and the `.streamlit/secrets.toml.example` file.
3. Do not upload your real `secrets.toml` to GitHub.
4. In Streamlit Cloud, deploy the GitHub repo.
5. Open the app settings and paste your real secrets into the Secrets box.

## How the app works

- Every selected day gets its own worksheet tab named `YYYY-MM-DD`.
- Same-day appointments are added when the calendar sync runs.
- Existing appointments keep their clock times and notes even if the calendar refreshes.
- PICKED UP marks the appointment complete and removes it from the active screen.
- The completed record stays in the daily sheet.

## Employee assignment

Best option: separate Google Calendars per employee and map each Calendar ID to an employee in secrets.

Fallback option: the app tries to infer the employee name from the event title, description, location, creator, or organizer.

## Spreadsheet columns

The daily worksheet records:

- Appointment ID
- Calendar ID
- Google Event ID
- Date
- Calendar start/end
- Employee from calendar
- Employee button selections
- Appointment title
- Service info
- Description
- Location
- Status
- Service start time
- Ready for pickup time
- Service seconds
- Picked up time
- Post-service seconds
- Notes
- Last updated
