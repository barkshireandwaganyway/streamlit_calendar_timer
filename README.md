# Lovely Grooming Appointment Timer

This Streamlit app supports two operating modes:

1. **Sync with calendar ON**  
   Pulls same-day appointments from Google Calendar and writes them to the daily Google Sheet tab.

2. **Sync with calendar OFF**  
   Lets you manually add appointments using the Add Appointment form.

The same START, READY FOR PICKUP, NOTES, and PICKED UP buttons work for both calendar appointments and manual appointments.

## Manual appointment fields

Manual appointments can include:

- Staff buttons: Kim, Veronica, Alex, Bather1, Bather 2, Bather 3
- Dog size: Small, Medium, Large, XL, XXL, XXXL
- Services: Bath, De-shed, De-shed + Classic cleanup, Full haircut
- Items/add-ons: Specific shampoo or conditioner, anal gland expression, ear plucking cleaning, nail trim
- Specific notes

None of the manual fields are required. If no customer or dog name is entered, the appointment will be created as `Manual Appointment`.

## Google Sheet logging

Each date gets its own sheet tab named like:

```text
2026-05-08
```

The log stores:

- Appointment source, Calendar or Manual
- Appointment info
- Staff button selections
- Dog size
- Services and add-ons
- Notes
- START time
- READY FOR PICKUP time
- Service duration
- PICKED UP time
- Post-service duration

## Streamlit secrets

Paste the contents of `.streamlit/secrets.toml.example` into Streamlit Cloud > App settings > Secrets, then replace the placeholder service account values.

Do not upload your real secrets to GitHub.
