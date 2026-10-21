/* api.js - Frontend client for the multi-agent ticket system. */
const apiBase = "/api/v1";
let authToken = null;

async function getToken() {
  if (authToken) return authToken;
  try {
    const r = await fetch(apiBase + "/auth/token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sub: "dashboard", roles: ["admin"] }),
    });
    if (!r.ok) throw new Error("auth/token " + r.status);
    const data = await r.json();
    authToken = data.access_token;
    return authToken;
  } catch (e) {
    console.warn("[api] unable to obtain auth token:", e.message);
    return null;
  }
}

async function call(method, path, body) {
  const token = await getToken();
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = "Bearer " + token;
  const r = await fetch(apiBase + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) {
    let msg = "HTTP " + r.status;
    try {
      const j = await r.json();
      if (Array.isArray(j.detail)) {
        // Pydantic validation error: surface the first human-readable message
        msg = j.detail.map(d => d.msg || JSON.stringify(d)).join("; ");
      } else {
        msg = j.message || j.detail || msg;
      }
    } catch (_) {}
    const err = new Error(msg);
    err.status = r.status;
    throw err;
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("application/json") ? r.json() : r.text();
}

/**
 * WebSocket live-stream for a single ticket. Sends one message every
 * second with the parent + all sub-tickets + state-transition events.
 * Stops automatically when every sub-ticket reaches a terminal state.
 *
 * @param {string} ticketId
 * @param {(msg: object) => void} onState  called on every "ticket_state"
 * @param {(ev: object) => void} onEvent   called on each transition event
 * @returns {() => void} close function
 */
function streamTicket(ticketId, onState, onEvent) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const token = authToken ? "?token=" + encodeURIComponent(authToken) : "";
  const ws = new WebSocket(`${proto}://${location.host}${apiBase}/tickets/${ticketId}/stream${token}`);
  let closed = false;
  const close = () => { closed = true; try { ws.close(); } catch (_) {} };
  ws.onmessage = (ev) => {
    if (closed) return;
    const msg = JSON.parse(ev.data);
    if (msg.type === "ticket_state") {
      onState && onState(msg);
      if (Array.isArray(msg.events)) msg.events.forEach(e => onEvent && onEvent(e));
    } else if (msg.type === "error") {
      close();
      onEvent && onEvent({ type: "error", message: msg.message });
    }
  };
  ws.onclose = () => { closed = true; };
  return close;
}

const api = {
  submitTicket: (body) => call("POST", "/tickets/submit", body),
  listTickets: () => call("GET", "/tickets?limit=50"),
  getTicket: (id) => call("GET", "/tickets/" + id),
  updateTicket: (id, body) => call("PATCH", "/tickets/" + encodeURIComponent(id), body),
  deleteTicket: (id) => call("DELETE", "/tickets/" + encodeURIComponent(id)),
  getSubTickets: (id) => call("GET", "/tickets/" + id + "/sub-tickets"),
  getTicketResult: (id) => call("GET", "/tickets/" + id + "/result"),
  listAgents: () => call("GET", "/agents"),
  analyzeTicket: (body) => call("POST", "/copilot/analyze", body),
  agentStatus: (type) => call("GET", "/agents/" + type + "/status"),
  /** Append follow-up info to a sub-ticket parked in waiting_info. */
  appendInfo: (ticketId, subId, text) => call("POST",
    `/tickets/${ticketId}/sub-tickets/${subId}/append-info`, { text }),
  ping: async () => { const r = await fetch("/health"); if (!r.ok) throw new Error("health " + r.status); return r.json(); },
};
