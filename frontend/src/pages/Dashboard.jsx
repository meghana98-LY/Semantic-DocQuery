import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { listSessions, createSession, deleteSession } from "../api/client";

export default function Dashboard() {
  const [sessions, setSessions] = useState([]);
  const [title, setTitle] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    fetchSessions();
  }, []);

  const fetchSessions = async (retry = true) => {
    setError("");
    try {
      const data = await listSessions();
      setSessions(data);
    } catch (err) {
      if (err.message.includes("401") || err.message.toLowerCase().includes("unauthorized")) {
        localStorage.removeItem("token");
        navigate("/login");
      } else if (retry) {
        // Auto-retry once after a short delay (handles cold-start / first-request lag)
        setTimeout(() => fetchSessions(false), 1500);
      } else {
        setError("Failed to load sessions. Check your connection and try again.");
      }
    }
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const session = await createSession(title.trim() || "New Chat");
      navigate(`/session/${session.id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (e, sessionId) => {
    e.stopPropagation();
    if (!window.confirm("Delete this session and all its documents?")) return;
    try {
      await deleteSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <h2>Your Chat Sessions</h2>
        <p>Select a session to continue, or create a new one below.</p>
      </div>

      <form onSubmit={handleCreate} className="create-session-form">
        <input
          type="text"
          placeholder="Session title (optional)"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <button type="submit" disabled={loading}>
          {loading ? "Creating…" : "+ New Session"}
        </button>
      </form>

      {error && (
        <div className="form-error">
          <p>{error}</p>
          <button onClick={() => fetchSessions()} style={{ marginTop: "0.5rem" }}>
            Try Again
          </button>
        </div>
      )}

      {sessions.length === 0 ? (
        <p className="empty-hint">No sessions yet. Create one to get started.</p>
      ) : (
        <ul className="session-list">
          {sessions.map((s) => (
            <li key={s.id} onClick={() => navigate(`/session/${s.id}`)}>
              <div className="session-info">
                <span className="session-title">{s.title}</span>
                <span className="session-date">
                  {new Date(s.created_at).toLocaleDateString()}
                </span>
              </div>
              <button
                className="delete-btn"
                onClick={(e) => handleDelete(e, s.id)}
                title="Delete session"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
