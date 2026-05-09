\
const api = async (action, data = {}) => {
  const res = await fetch(`/.netlify/functions/api?action=${encodeURIComponent(action)}`, {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify(data)
  });
  const text = await res.text();
  let json;
  try { json = JSON.parse(text); } catch { throw new Error(text || "Bad server response"); }
  if (!res.ok || json.ok === false) {
    throw new Error(json.error || "Request failed");
  }
  return json;
};

const state = {
  settings: null,
  appointments: [],
  selectedDate: new Date().toISOString().slice(0,10)
};

const $ = id => document.getElementById(id);
const message = (msg, type="ok") => {
  $("message").innerHTML = `<div class="notice ${type}">${escapeHtml(msg)}</div>`;
};
const clearMessage = () => $("message").innerHTML = "";
const escapeHtml = s => String(s ?? "").replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
const nowTime = () => new Date().toTimeString().slice(0,5);
const splitCsv = v => String(v||"").split(",").map(x=>x.trim()).filter(Boolean);
const joinCsv = arr => [...new Set((arr||[]).map(x=>String(x).trim()).filter(Boolean))].join(", ");

document.querySelectorAll(".tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    $(btn.dataset.tab).classList.add("active");
  });
});

async function init() {
  $("dateInput").value = state.selectedDate;
  $("startTime").value = nowTime();
  $("endTime").value = addHour(nowTime());
  wireEvents();
  await checkHealth(false);
  await loadSettings();
  await loadAppointments();
}

function addHour(hhmm){
  const [h,m] = hhmm.split(":").map(Number);
  const d = new Date(); d.setHours(h||0, m||0, 0, 0); d.setHours(d.getHours()+1);
  return d.toTimeString().slice(0,5);
}

function wireEvents() {
  $("dateInput").addEventListener("change", async e => {
    state.selectedDate = e.target.value;
    await loadAppointments();
  });
  $("refreshBtn").addEventListener("click", loadAppointments);
  $("toggleManualBtn").addEventListener("click", () => $("manualBox").classList.toggle("hidden"));
  $("addApptBtn").addEventListener("click", addAppointment);
  $("saveSettingsBtn").addEventListener("click", saveSettingsFromUI);
  $("resetDefaultsBtn").addEventListener("click", async () => {
    if (!confirm("Restore default staff, sizes, services, add-ons, and button labels?")) return;
    await api("resetSettings", {});
    await loadSettings();
    message("Default settings restored.", "ok");
  });
  $("loadRecordsBtn").addEventListener("click", renderRecords);
  $("healthBtn").addEventListener("click", () => checkHealth(true));
}

async function checkHealth(showSuccess=true) {
  try {
    const h = await api("health", {});
    if (showSuccess) message(`Connection OK. Sheet ID found. Settings source ready.`, "ok");
  } catch (err) {
    message(`Connection problem: ${err.message}`, "bad");
  }
}

async function loadSettings() {
  const res = await api("getSettings", {});
  state.settings = res.settings;
  populateManualOptions();
  renderSettings();
}

function optionsFor(category) {
  return (state.settings?.items || []).filter(x => x.category === category && x.active !== false).sort((a,b)=>(a.sort||0)-(b.sort||0)).map(x => x.value);
}
function settingValue(key, fallback) {
  const item = (state.settings?.items || []).find(x => x.category === "timer_label" && x.key === key);
  return item?.value || fallback;
}

function populateSelect(id, values, blank=false) {
  const el = $(id);
  el.innerHTML = "";
  if (blank) el.appendChild(new Option("", ""));
  values.forEach(v => el.appendChild(new Option(v, v)));
}

function populateManualOptions() {
  populateSelect("dogSize", optionsFor("dog_size"), true);
  populateSelect("primaryStaff", optionsFor("staff"), true);
  populateSelect("services", optionsFor("service"));
  populateSelect("addons", optionsFor("addon"));
}

async function loadAppointments() {
  clearMessage();
  const res = await api("getAppointments", {date: state.selectedDate});
  state.appointments = res.appointments || [];
  renderBoard();
}

async function addAppointment() {
  const appointment = {
    date: state.selectedDate,
    source: "Manual",
    customer_name: $("customerName").value.trim(),
    dog_name: $("dogName").value.trim(),
    dog_size: $("dogSize").value,
    start_time: $("startTime").value,
    end_time: $("endTime").value,
    primary_staff: $("primaryStaff").value || optionsFor("staff")[0] || "Unassigned",
    assigned_staff: $("primaryStaff").value ? $("primaryStaff").value : "",
    services: joinCsv([...$("services").selectedOptions].map(o=>o.value)),
    addons: joinCsv([...$("addons").selectedOptions].map(o=>o.value)),
    shampoo: $("shampoo").value.trim(),
    notes: $("notes").value.trim()
  };
  await api("addAppointment", {appointment});
  $("customerName").value = "";
  $("dogName").value = "";
  $("notes").value = "";
  $("shampoo").value = "";
  await loadAppointments();
  message("Appointment added.", "ok");
}

function renderBoard() {
  const staff = optionsFor("staff");
  const board = $("board");
  board.innerHTML = "";
  const columns = staff.length ? staff : ["Unassigned"];
  columns.forEach(name => {
    const col = document.createElement("div");
    col.className = "column";
    col.innerHTML = `<h2>${escapeHtml(name)}</h2>`;
    const mine = state.appointments.filter(a => (a.primary_staff || "Unassigned") === name && a.status !== "Picked Up");
    if (!mine.length) col.innerHTML += `<div class="small">No active appointments.</div>`;
    mine.forEach(a => col.appendChild(renderAppointmentCard(a, staff)));
    board.appendChild(col);
  });
}

function renderAppointmentCard(a, staff) {
  const div = document.createElement("div");
  div.className = "appt";
  const assigned = splitCsv(a.assigned_staff);
  const title = a.dog_name || a.customer_name || "Manual Appointment";
  const time = [a.start_time, a.end_time].filter(Boolean).join(" - ");
  const labels = [
    a.source, a.status || "Not Started", a.dog_size ? `Size: ${a.dog_size}` : "", 
    a.services ? `Services: ${a.services}` : "", a.addons ? `Add-ons: ${a.addons}` : "",
    a.shampoo ? `Shampoo/conditioner: ${a.shampoo}` : ""
  ].filter(Boolean);
  div.innerHTML = `
    <h3>${escapeHtml(title)}</h3>
    <div class="meta">${escapeHtml(a.customer_name || "")}</div>
    <div class="meta">${escapeHtml(time)}</div>
    <div class="badges">${labels.map(x=>`<span class="badge">${escapeHtml(x)}</span>`).join("")}</div>
    ${a.notes ? `<div class="meta"><b>Notes:</b> ${escapeHtml(a.notes)}</div>` : ""}
    <div class="staff-buttons"></div>
    <div class="timer-buttons"></div>
  `;
  const staffWrap = div.querySelector(".staff-buttons");
  staff.forEach(name => {
    const b = document.createElement("button");
    b.className = "staff-btn" + (assigned.includes(name) ? " selected" : "");
    b.textContent = name;
    b.addEventListener("click", () => toggleStaff(a.id, name));
    staffWrap.appendChild(b);
  });
  const timer = div.querySelector(".timer-buttons");
  const start = document.createElement("button");
  start.className = "success";
  start.textContent = settingValue("start", "START");
  start.disabled = Boolean(a.service_start_at);
  start.onclick = () => updateTimer(a.id, "start");
  timer.appendChild(start);

  const ready = document.createElement("button");
  ready.className = "warning";
  ready.textContent = settingValue("ready", "READY FOR PICKUP");
  ready.disabled = !a.service_start_at || Boolean(a.ready_at);
  ready.onclick = async () => {
    let note = "";
    if (confirm("Would you like to add notes?")) note = prompt("Appointment notes:", a.notes || "") || "";
    await updateTimer(a.id, "ready", {notes: note});
  };
  timer.appendChild(ready);

  const notes = document.createElement("button");
  notes.className = "secondary";
  notes.textContent = "NOTES";
  notes.onclick = async () => {
    const note = prompt("Appointment notes:", a.notes || "");
    if (note !== null) await api("updateAppointment", {date: state.selectedDate, id:a.id, updates:{notes: note}}).then(loadAppointments);
  };
  timer.appendChild(notes);

  const picked = document.createElement("button");
  picked.className = "danger";
  picked.textContent = settingValue("picked", "PICKED UP");
  picked.disabled = !a.ready_at || Boolean(a.picked_up_at);
  picked.onclick = () => updateTimer(a.id, "picked");
  timer.appendChild(picked);

  return div;
}

async function toggleStaff(id, name) {
  const a = state.appointments.find(x => x.id === id);
  let assigned = splitCsv(a.assigned_staff);
  if (assigned.includes(name)) assigned = assigned.filter(x => x !== name);
  else assigned.push(name);
  const updates = { assigned_staff: joinCsv(assigned) };
  if (!a.primary_staff || a.primary_staff === "Unassigned") updates.primary_staff = name;
  await api("updateAppointment", {date: state.selectedDate, id, updates});
  await loadAppointments();
}

async function updateTimer(id, stage, extra={}) {
  await api("timerAction", {date: state.selectedDate, id, stage, ...extra});
  await loadAppointments();
}

function renderSettings() {
  const categories = [
    ["staff", "Staff names"],
    ["dog_size", "Dog sizes"],
    ["service", "Services"],
    ["addon", "Items / add-ons"]
  ];
  const grid = $("settingsGrid");
  grid.innerHTML = "";
  categories.forEach(([cat,label]) => {
    const box = document.createElement("div");
    box.className = "card";
    box.innerHTML = `<h3>${label}</h3><div class="list" data-cat="${cat}"></div><div class="list-editor"><input placeholder="Add new ${label.toLowerCase()}"><button class="secondary">Add</button></div>`;
    const list = box.querySelector(".list");
    const renderList = () => {
      list.innerHTML = "";
      optionsFor(cat).forEach(v => {
        const row = document.createElement("div");
        row.className = "list-row";
        row.innerHTML = `<input value="${escapeHtml(v)}"><button class="secondary up">↑</button><button class="danger remove">Remove</button>`;
        row.querySelector(".remove").onclick = () => { row.remove(); };
        row.querySelector(".up").onclick = () => { if (row.previousElementSibling) list.insertBefore(row, row.previousElementSibling); };
        list.appendChild(row);
      });
    };
    renderList();
    box.querySelector(".list-editor button").onclick = () => {
      const inp = box.querySelector(".list-editor input");
      if (!inp.value.trim()) return;
      const row = document.createElement("div");
      row.className = "list-row";
      row.innerHTML = `<input value="${escapeHtml(inp.value.trim())}"><button class="secondary up">↑</button><button class="danger remove">Remove</button>`;
      row.querySelector(".remove").onclick = () => row.remove();
      row.querySelector(".up").onclick = () => { if (row.previousElementSibling) list.insertBefore(row, row.previousElementSibling); };
      list.appendChild(row);
      inp.value = "";
    };
    grid.appendChild(box);
  });

  const timerBox = document.createElement("div");
  timerBox.className = "card";
  timerBox.innerHTML = `
    <h3>Timer button labels</h3>
    <label>Start button</label><input id="labelStart" value="${escapeHtml(settingValue("start","START"))}">
    <label>Ready button</label><input id="labelReady" value="${escapeHtml(settingValue("ready","READY FOR PICKUP"))}">
    <label>Picked up button</label><input id="labelPicked" value="${escapeHtml(settingValue("picked","PICKED UP"))}">
  `;
  grid.appendChild(timerBox);
}

async function saveSettingsFromUI() {
  const items = [];
  let sort = 1;
  document.querySelectorAll(".list[data-cat]").forEach(list => {
    const cat = list.dataset.cat;
    [...list.querySelectorAll(".list-row input")].forEach(input => {
      const value = input.value.trim();
      if (value) items.push({category: cat, value, active: true, sort: sort++});
    });
  });
  items.push({category:"timer_label", key:"start", value:$("labelStart").value.trim() || "START", active:true, sort:1});
  items.push({category:"timer_label", key:"ready", value:$("labelReady").value.trim() || "READY FOR PICKUP", active:true, sort:2});
  items.push({category:"timer_label", key:"picked", value:$("labelPicked").value.trim() || "PICKED UP", active:true, sort:3});
  await api("saveSettings", {items});
  await loadSettings();
  await loadAppointments();
  message("Settings saved.", "ok");
}

function renderRecords() {
  const tbl = $("recordsTable");
  if (!state.appointments.length) { tbl.innerHTML = "<tr><td>No records loaded.</td></tr>"; return; }
  const keys = ["status","source","customer_name","dog_name","primary_staff","assigned_staff","services","addons","service_start_at","ready_at","picked_up_at","service_minutes","post_service_minutes","notes"];
  tbl.innerHTML = `<thead><tr>${keys.map(k=>`<th>${escapeHtml(k)}</th>`).join("")}</tr></thead><tbody>${state.appointments.map(a=>`<tr>${keys.map(k=>`<td>${escapeHtml(a[k]||"")}</td>`).join("")}</tr>`).join("")}</tbody>`;
}

init();
