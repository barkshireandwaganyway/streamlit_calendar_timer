# Lovely Grooming Netlify Appointment Timer - Clean Start

This version is designed to avoid the Streamlit-to-Netlify environment variable confusion.

## What to upload to GitHub

Upload all files in this folder:

- `index.html`
- `styles.css`
- `app.js`
- `package.json`
- `netlify.toml`
- `netlify/functions/api.js`

## Netlify build settings

Use:

- Build command: `npm install`
- Publish directory: `.`
- Functions directory: `netlify/functions`

## Required Netlify environment variables

Use the Netlify visual editor. Add each key separately. Do not type `KEY=` inside the value box.

Required:

- `APP_TIMEZONE`
- `SPREADSHEET_ID`
- `GOOGLE_PROJECT_ID`
- `GOOGLE_PRIVATE_KEY_ID`
- `GOOGLE_PRIVATE_KEY`
- `GOOGLE_SERVICE_ACCOUNT_EMAIL`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_X509_CERT_URL`

This app also supports a simpler alternative:

- `SPREADSHEET_ID`
- `GOOGLE_SERVICE_ACCOUNT_JSON`

For `GOOGLE_SERVICE_ACCOUNT_JSON`, paste the full Google service account JSON as one value.

## Important

The Google Sheet must be shared with the service account email as Editor.

After changing environment variables, trigger a fresh deploy:

Deploys -> Trigger deploy -> Clear cache and deploy site
