const BASE_URL = "http://localhost:8000";

function getToken() {
  return localStorage.getItem("token");
}

function authHeaders() {
  return {
    Authorization: `Bearer ${getToken()}`,
    "Content-Type": "application/json",
  };
}

async function handleResponse(res) {
  if (!res.ok) {
    let detail = `Request failed with status ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

// ─── Auth ─────────────────────────────────────────────────────────────────────

export async function registerUser(email, password) {
  const res = await fetch(`${BASE_URL}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  return handleResponse(res);
}

export async function loginUser(email, password) {
  const res = await fetch(`${BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  return handleResponse(res); // { access_token, token_type }
}

// ─── Sessions ─────────────────────────────────────────────────────────────────

export async function createSession(title = "New Chat") {
  const res = await fetch(`${BASE_URL}/sessions`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ title }),
  });
  return handleResponse(res);
}

export async function listSessions() {
  const res = await fetch(`${BASE_URL}/sessions`, {
    headers: authHeaders(),
  });
  return handleResponse(res);
}

export async function deleteSession(sessionId) {
  const res = await fetch(`${BASE_URL}/sessions/${sessionId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (res.status === 204) return;
  return handleResponse(res);
}

// ─── Session details ──────────────────────────────────────────────────────────

export async function getSessionMessages(sessionId) {
  const res = await fetch(`${BASE_URL}/sessions/${sessionId}/messages`, {
    headers: authHeaders(),
  });
  return handleResponse(res);
}

export async function getSessionDocuments(sessionId) {
  const res = await fetch(`${BASE_URL}/sessions/${sessionId}/documents`, {
    headers: authHeaders(),
  });
  return handleResponse(res);
}

// ─── Upload ───────────────────────────────────────────────────────────────────

export async function uploadDocuments(sessionId, files) {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }
  const res = await fetch(`${BASE_URL}/upload?session_id=${sessionId}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${getToken()}` }, // no Content-Type; browser sets multipart boundary
    body: formData,
  });
  return handleResponse(res);
}

// ─── Query ────────────────────────────────────────────────────────────────────

export async function askQuestion(sessionId, question, pageRange = null, topK = 5) {
  const body = { session_id: sessionId, question, top_k: topK };
  if (pageRange && pageRange.trim()) {
    body.page_range = pageRange.trim();
  }
  const res = await fetch(`${BASE_URL}/query`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  return handleResponse(res); // { answer, sources }
}
