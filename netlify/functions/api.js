const { google } = require("googleapis");

const SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"];
const SETTINGS_SHEET = "APP_SETTINGS";

const headers = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Allow-Methods": "POST, OPTIONS"
};

function json(statusCode, body) {
  return { statusCode, headers, body: JSON.stringify(body) };
}

function requiredEnv() {
  const missing = [];
  if (!process.env.SPREADSHEET_ID) missing.push("SPREADSHEET_ID");
  if (!process.env.GOOGLE_SERVICE_ACCOUNT_JSON && !process.env.GOOGLE_SERVICE_ACCOUNT_JSON_BASE64) {
    const need = ["GOOGLE_PROJECT_ID", "GOOGLE_PRIVATE_KEY_ID", "GOOGLE_PRIVATE_KEY", "GOOGLE_SERVICE_ACCOUNT_EMAIL", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_X509_CERT_URL"];
    need.forEach(k => { if (!process.env[k]) missing.push(k); });
  }
  return missing;
}

function getServiceAccount() {
  if (process.env.GOOGLE_SERVICE_ACCOUNT_JSON_BASE64) {
    const raw = Buffer.from(process.env.GOOGLE_SERVICE_ACCOUNT_JSON_BASE64, "base64").toString("utf8");
    const sa = JSON.parse(raw);
    if (sa.private_key) sa.private_key = sa.private_key.replace(/\\n/g, "\n");
    return sa;
  }
  if (process.env.GOOGLE_SERVICE_ACCOUNT_JSON) {
    const sa = JSON.parse(process.env.GOOGLE_SERVICE_ACCOUNT_JSON);
    if (sa.private_key) sa.private_key = sa.private_key.replace(/\\n/g, "\n");
    return sa;
  }
  return {
    type: "service_account",
    project_id: process.env.GOOGLE_PROJECT_ID,
    private_key_id: process.env.GOOGLE_PRIVATE_KEY_ID,
    private_key: (process.env.GOOGLE_PRIVATE_KEY || "").replace(/\\n/g, "\n"),
    client_email: process.env.GOOGLE_SERVICE_ACCOUNT_EMAIL,
    client_id: process.env.GOOGLE_CLIENT_ID,
    auth_uri: "https://accounts.google.com/o/oauth2/auth",
    token_uri: "https://oauth2.googleapis.com/token",
    auth_provider_x509_cert_url: "https://www.googleapis.com/oauth2/v1/certs",
    client_x509_cert_url: process.env.GOOGLE_CLIENT_X509_CERT_URL,
    universe_domain: "googleapis.com"
  };
}

async function sheetsClient() {
  const missing = requiredEnv();
  if (missing.length) {
    throw new Error("Missing required environment variable(s): " + missing.join(", "));
  }
  const sa = getServiceAccount();
  const auth = new google.auth.JWT(sa.client_email, null, sa.private_key, SCOPES, null);
  return google.sheets({ version: "v4", auth });
}

function todaySheetName(date) {
  return String(date || new Date().toISOString().slice(0,10));
}

const dayHeaders = [
  "id","date","source","status","customer_name","dog_name","dog_size","start_time","end_time",
  "primary_staff","assigned_staff","services","addons","shampoo","notes",
  "service_start_at","ready_at","picked_up_at","service_minutes","post_service_minutes","created_at","updated_at"
];

const defaultSettings = [
  ["staff","", "Kim", true, 1],
  ["staff","", "Veronica", true, 2],
  ["staff","", "Alex", true, 3],
  ["staff","", "Bather1", true, 4],
  ["staff","", "Bather 2", true, 5],
  ["staff","", "Bather 3", true, 6],
  ["dog_size","", "Small", true, 1],
  ["dog_size","", "Medium", true, 2],
  ["dog_size","", "Large", true, 3],
  ["dog_size","", "XL", true, 4],
  ["dog_size","", "XXL", true, 5],
  ["dog_size","", "XXXL", true, 6],
  ["service","", "Bath", true, 1],
  ["service","", "De-shed", true, 2],
  ["service","", "De-shed + Classic cleanup", true, 3],
  ["service","", "Full haircut", true, 4],
  ["addon","", "Anal gland expression", true, 1],
  ["addon","", "Ear plucking cleaning", true, 2],
  ["addon","", "Nail trim", true, 3],
  ["addon","", "Specific shampoo or conditioner", true, 4],
  ["timer_label","start", "START", true, 1],
  ["timer_label","ready", "READY FOR PICKUP", true, 2],
  ["timer_label","picked", "PICKED UP", true, 3],
];

async function getSpreadsheetMeta(sheets) {
  const res = await sheets.spreadsheets.get({ spreadsheetId: process.env.SPREADSHEET_ID });
  return res.data;
}
async function sheetExists(sheets, title) {
  const meta = await getSpreadsheetMeta(sheets);
  return meta.sheets.some(s => s.properties.title === title);
}
async function ensureSheet(sheets, title, headerRow) {
  const exists = await sheetExists(sheets, title);
  if (!exists) {
    await sheets.spreadsheets.batchUpdate({
      spreadsheetId: process.env.SPREADSHEET_ID,
      requestBody: { requests: [{ addSheet: { properties: { title } } }] }
    });
  }
  if (headerRow?.length) {
    const cur = await sheets.spreadsheets.values.get({ spreadsheetId: process.env.SPREADSHEET_ID, range: `${q(title)}!1:1` }).catch(()=>({data:{values:[]}}));
    if (!cur.data.values || !cur.data.values[0] || cur.data.values[0].length === 0) {
      await sheets.spreadsheets.values.update({
        spreadsheetId: process.env.SPREADSHEET_ID,
        range: `${q(title)}!A1`,
        valueInputOption: "RAW",
        requestBody: { values: [headerRow] }
      });
    }
  }
}
function q(title) { return `'${String(title).replace(/'/g, "''")}'`; }

async function ensureSettings(sheets) {
  await ensureSheet(sheets, SETTINGS_SHEET, ["category","key","value","active","sort"]);
  const rows = await sheets.spreadsheets.values.get({ spreadsheetId: process.env.SPREADSHEET_ID, range: `${q(SETTINGS_SHEET)}!A2:E` });
  if (!rows.data.values || rows.data.values.length === 0) {
    await sheets.spreadsheets.values.update({
      spreadsheetId: process.env.SPREADSHEET_ID,
      range: `${q(SETTINGS_SHEET)}!A2`,
      valueInputOption: "RAW",
      requestBody: { values: defaultSettings }
    });
  }
}

function rowsToObjects(values, headers) {
  return (values || []).map(row => {
    const o = {};
    headers.forEach((h,i) => o[h] = row[i] ?? "");
    return o;
  });
}
function objToRow(o, headers) { return headers.map(h => o[h] ?? ""); }

async function getAppointments(sheets, date) {
  const title = todaySheetName(date);
  await ensureSheet(sheets, title, dayHeaders);
  const res = await sheets.spreadsheets.values.get({ spreadsheetId: process.env.SPREADSHEET_ID, range: `${q(title)}!A2:V` });
  return rowsToObjects(res.data.values, dayHeaders);
}

async function writeAppointments(sheets, date, appointments) {
  const title = todaySheetName(date);
  await ensureSheet(sheets, title, dayHeaders);
  const values = appointments.map(a => objToRow(a, dayHeaders));
  await sheets.spreadsheets.values.clear({ spreadsheetId: process.env.SPREADSHEET_ID, range: `${q(title)}!A2:V` });
  if (values.length) {
    await sheets.spreadsheets.values.update({
      spreadsheetId: process.env.SPREADSHEET_ID,
      range: `${q(title)}!A2`,
      valueInputOption: "RAW",
      requestBody: { values }
    });
  }
}

function isoNow() { return new Date().toISOString(); }
function minutesBetween(a,b) {
  if (!a || !b) return "";
  const diff = (new Date(b).getTime() - new Date(a).getTime()) / 60000;
  if (!Number.isFinite(diff) || diff < 0) return "";
  return String(Math.round(diff));
}

exports.handler = async function(event) {
  if (event.httpMethod === "OPTIONS") return { statusCode: 204, headers };
  let body = {};
  try { body = event.body ? JSON.parse(event.body) : {}; } catch {}
  const action = event.queryStringParameters?.action || body.action || "health";
  try {
    const sheets = await sheetsClient();

    if (action === "health") {
      const meta = await getSpreadsheetMeta(sheets);
      return json(200, { ok:true, spreadsheetTitle: meta.properties.title });
    }

    if (action === "getSettings") {
      await ensureSettings(sheets);
      const res = await sheets.spreadsheets.values.get({ spreadsheetId: process.env.SPREADSHEET_ID, range: `${q(SETTINGS_SHEET)}!A2:E` });
      const items = (res.data.values || []).map(r => ({ category:r[0]||"", key:r[1]||"", value:r[2]||"", active:String(r[3]).toUpperCase() !== "FALSE", sort:Number(r[4]||0) }));
      return json(200, { ok:true, settings:{items} });
    }

    if (action === "saveSettings") {
      const items = body.items || [];
      await ensureSheet(sheets, SETTINGS_SHEET, ["category","key","value","active","sort"]);
      await sheets.spreadsheets.values.clear({ spreadsheetId: process.env.SPREADSHEET_ID, range: `${q(SETTINGS_SHEET)}!A2:E` });
      const values = items.map((x,i)=>[x.category||"", x.key||"", x.value||"", x.active !== false, x.sort || i+1]);
      if (values.length) {
        await sheets.spreadsheets.values.update({ spreadsheetId: process.env.SPREADSHEET_ID, range:`${q(SETTINGS_SHEET)}!A2`, valueInputOption:"RAW", requestBody:{values} });
      }
      return json(200, {ok:true});
    }

    if (action === "resetSettings") {
      await ensureSheet(sheets, SETTINGS_SHEET, ["category","key","value","active","sort"]);
      await sheets.spreadsheets.values.clear({ spreadsheetId: process.env.SPREADSHEET_ID, range: `${q(SETTINGS_SHEET)}!A2:E` });
      await sheets.spreadsheets.values.update({ spreadsheetId: process.env.SPREADSHEET_ID, range:`${q(SETTINGS_SHEET)}!A2`, valueInputOption:"RAW", requestBody:{values:defaultSettings} });
      return json(200, {ok:true});
    }

    if (action === "getAppointments") {
      const appointments = await getAppointments(sheets, body.date);
      return json(200, {ok:true, appointments});
    }

    if (action === "addAppointment") {
      const appt = body.appointment || {};
      const date = appt.date || body.date || new Date().toISOString().slice(0,10);
      const appointments = await getAppointments(sheets, date);
      const now = isoNow();
      const id = "manual_" + Date.now() + "_" + Math.random().toString(36).slice(2,8);
      const newAppt = {
        id, date, source: appt.source || "Manual", status: "Not Started",
        customer_name: appt.customer_name || "", dog_name: appt.dog_name || "", dog_size: appt.dog_size || "",
        start_time: appt.start_time || "", end_time: appt.end_time || "",
        primary_staff: appt.primary_staff || "Unassigned", assigned_staff: appt.assigned_staff || appt.primary_staff || "",
        services: appt.services || "", addons: appt.addons || "", shampoo: appt.shampoo || "", notes: appt.notes || "",
        service_start_at:"", ready_at:"", picked_up_at:"", service_minutes:"", post_service_minutes:"",
        created_at: now, updated_at: now
      };
      appointments.push(newAppt);
      await writeAppointments(sheets, date, appointments);
      return json(200, {ok:true, appointment:newAppt});
    }

    if (action === "updateAppointment") {
      const date = body.date;
      const appointments = await getAppointments(sheets, date);
      const idx = appointments.findIndex(a => a.id === body.id);
      if (idx < 0) return json(404, {ok:false, error:"Appointment not found"});
      appointments[idx] = {...appointments[idx], ...(body.updates||{}), updated_at: isoNow()};
      await writeAppointments(sheets, date, appointments);
      return json(200, {ok:true, appointment:appointments[idx]});
    }

    if (action === "timerAction") {
      const date = body.date;
      const appointments = await getAppointments(sheets, date);
      const idx = appointments.findIndex(a => a.id === body.id);
      if (idx < 0) return json(404, {ok:false, error:"Appointment not found"});
      const a = appointments[idx];
      const now = isoNow();
      if (body.stage === "start") {
        a.service_start_at = a.service_start_at || now;
        a.status = "In Service";
      } else if (body.stage === "ready") {
        a.ready_at = a.ready_at || now;
        a.status = "Ready For Pickup";
        a.service_minutes = minutesBetween(a.service_start_at, a.ready_at);
        if (body.notes) a.notes = body.notes;
      } else if (body.stage === "picked") {
        a.picked_up_at = a.picked_up_at || now;
        a.status = "Picked Up";
        a.post_service_minutes = minutesBetween(a.ready_at, a.picked_up_at);
      }
      a.updated_at = now;
      appointments[idx] = a;
      await writeAppointments(sheets, date, appointments);
      return json(200, {ok:true, appointment:a});
    }

    return json(400, {ok:false, error:"Unknown action: " + action});
  } catch (err) {
    return json(500, {ok:false, error: err.message || String(err)});
  }
};
