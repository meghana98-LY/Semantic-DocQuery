import { useState, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  getSessionMessages,
  getSessionDocuments,
  uploadDocuments,
  askQuestion,
} from "../api/client";

// ── Highlight query terms inside a snippet ───────────────────────────────────
function HighlightedText({ text, query }) {
  if (!query || !text) return <span>{text}</span>;

  const words = query
    .split(/\s+/)
    .filter((w) => w.length > 2)
    .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));

  if (!words.length) return <span>{text}</span>;

  const pattern = new RegExp(`(${words.join("|")})`, "gi");
  const parts = text.split(pattern);

  return (
    <span>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <mark key={i} className="snippet-highlight">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </span>
  );
}

// ── Source cards rendered below an assistant answer ──────────────────────────
function SourceCards({ sources, query }) {
  if (!sources || sources.length === 0) return null;

  return (
    <div className="sources-panel">
      <p className="sources-label">Supporting Chunks</p>
      {sources.map((src, i) => (
        <div key={i} className="source-card">
          {/* ── Header row: doc name · page · closeness ── */}
          <div className="source-meta">
            <span className="source-doc" title={src.document_name}>
              {src.document_name}
            </span>
            <span className="source-page">p.&nbsp;{src.page_number}</span>
            <span
              className={`similarity-badge ${
                src.similarity_score >= 0.7
                  ? "sim-high"
                  : src.similarity_score >= 0.4
                  ? "sim-mid"
                  : "sim-low"
              }`}
            >
              {src.similarity_percent} match
            </span>
          </div>

          {/* ── Raw chunk text with keyword highlighting ── */}
          <div className="chunk-section">
            <span className="chunk-section-label">Raw Chunk</span>
            <p className="source-snippet">
              <HighlightedText text={src.snippet} query={query} />
            </p>
          </div>

          {/* ── Per-chunk relevant summary ── */}
          {src.summary && (
            <div className="chunk-section chunk-summary-section">
              <span className="chunk-section-label">Relevant Summary</span>
              <p className="chunk-summary">{src.summary}</p>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Render structured assistant response ─────────────────────────────────────
// The backend returns a clean short summary sentence as `answer`.
// Source cards with raw chunks + per-chunk summaries are rendered below it.
function AssistantContent({ content, sources, query }) {
  return (
    <>
      <p className="message-content">{content}</p>
      {sources && sources.length > 0 && (
        <SourceCards sources={sources} query={query} />
      )}
    </>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export default function SessionChat() {
  const { sessionId } = useParams();
  const navigate = useNavigate();

  const [messages, setMessages] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [question, setQuestion] = useState("");
  const [pageRange, setPageRange] = useState("");
  const [files, setFiles] = useState([]);

  const [uploading, setUploading] = useState(false);
  const [asking, setAsking] = useState(false);
  const [chatError, setChatError] = useState("");
  const [uploadError, setUploadError] = useState("");

  const messagesEndRef = useRef(null);
  const pollRef = useRef(null);

  // ── Load session data on mount ────────────────────────────────────────────
  useEffect(() => {
    loadSession();
    return () => clearInterval(pollRef.current);
  }, [sessionId]);

  // ── Scroll to bottom on new messages ─────────────────────────────────────
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, asking]);

  const loadSession = async () => {
    try {
      const [msgs, docs] = await Promise.all([
        getSessionMessages(sessionId),
        getSessionDocuments(sessionId),
      ]);
      setMessages(msgs);
      setDocuments(docs);
      if (docs.some((d) => d.status === "processing")) {
        startPolling();
      }
    } catch (err) {
      if (err.message.includes("404")) {
        navigate("/dashboard");
      } else if (err.message.includes("401")) {
        localStorage.removeItem("token");
        navigate("/login");
      }
    }
  };

  // ── Poll document status every 3 s until all are done ────────────────────
  const startPolling = () => {
    clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const docs = await getSessionDocuments(sessionId);
        setDocuments(docs);
        if (docs.every((d) => d.status !== "processing")) {
          clearInterval(pollRef.current);
        }
      } catch (_) {
        clearInterval(pollRef.current);
      }
    }, 3000);
  };

  // ── Handle file upload ────────────────────────────────────────────────────
  const handleUpload = async (e) => {
    e.preventDefault();
    if (!files.length) return;
    setUploading(true);
    setUploadError("");
    try {
      const result = await uploadDocuments(sessionId, files);
      const newDocs = result.documents.map((d) => ({
        id: d.document_id,
        filename: d.filename,
        status: d.status,
        session_id: sessionId,
      }));
      setDocuments((prev) => [...prev, ...newDocs]);
      setFiles([]);
      startPolling();
    } catch (err) {
      setUploadError(err.message);
    } finally {
      setUploading(false);
    }
  };

  // ── Handle question submission ────────────────────────────────────────────
  const handleAsk = async (e) => {
    e.preventDefault();
    if (!question.trim() || asking) return;
    setChatError("");
    setAsking(true);

    const currentQuestion = question;
    const currentPageRange = pageRange.trim() || null;

    const userMsg = {
      id: `tmp-${Date.now()}`,
      role: "user",
      content: currentQuestion,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setQuestion("");

    try {
      const data = await askQuestion(sessionId, currentQuestion, currentPageRange);

      const assistantMsg = {
        id: `tmp-${Date.now() + 1}`,
        role: "assistant",
        content: data.answer,
        sources: data.sources || [],
        // Attach original question for highlighting
        _query: currentQuestion,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      setChatError(err.message);
      setMessages((prev) => prev.filter((m) => m.id !== userMsg.id));
      setQuestion(currentQuestion);
    } finally {
      setAsking(false);
    }
  };

  const completedDocs = documents.filter((d) => d.status === "completed");
  const hasCompletedDocs = completedDocs.length > 0;
  const processingCount = documents.filter((d) => d.status === "processing").length;

  return (
    <div className="session-page">
      {/* ── Document Panel ───────────────────────────────────────────────── */}
      <aside className="doc-panel">
        <h3>Documents</h3>

        <form onSubmit={handleUpload} className="upload-form">
          <input
            type="file"
            accept=".pdf"
            multiple
            key={files.length === 0 ? "reset" : "active"}
            onChange={(e) => setFiles(Array.from(e.target.files))}
          />
          {files.length > 0 && (
            <p className="file-hint">{files.length} file(s) selected</p>
          )}
          <button type="submit" disabled={uploading || files.length === 0}>
            {uploading ? "Uploading…" : "Upload PDF(s)"}
          </button>
        </form>

        {uploadError && <p className="form-error">{uploadError}</p>}

        {processingCount > 0 && (
          <p className="processing-hint">
            ⏳ {processingCount} document(s) processing…
          </p>
        )}

        {documents.length === 0 && (
          <p className="empty-hint">Upload PDFs to start chatting.</p>
        )}

        <ul className="doc-list">
          {documents.map((doc) => (
            <li key={doc.id} className="doc-item">
              <span className="doc-name" title={doc.filename}>
                {doc.filename}
              </span>
              <span className={`badge badge-${doc.status}`}>{doc.status}</span>
            </li>
          ))}
        </ul>

        <button
          type="button"
          className="back-btn"
          onClick={() => navigate("/dashboard")}
        >
          ← Back to Session
        </button>
      </aside>

      {/* ── Chat Panel ───────────────────────────────────────────────────── */}
      <div className="chat-panel">
        <div className="messages">
          {messages.length === 0 && (
            <p className="empty-hint">
              {hasCompletedDocs
                ? "Ask a question about your documents."
                : "Upload and wait for documents to process, then ask a question."}
            </p>
          )}

          {messages.map((msg, idx) => (
            <div key={msg.id} className={`message message-${msg.role}`}>
              <span className="message-label">
                {msg.role === "user" ? "You" : "Assistant"}
              </span>
              {msg.role === "assistant" ? (
                <AssistantContent
                  content={msg.content}
                  sources={msg.sources}
                  query={msg._query || (idx > 0 ? messages[idx - 1].content : "")}
                />
              ) : (
                <p className="message-content">{msg.content}</p>
              )}
            </div>
          ))}

          {asking && (
            <div className="message message-assistant">
              <span className="message-label">Assistant</span>
              <p className="message-content thinking">Thinking…</p>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {chatError && <p className="form-error chat-error">{chatError}</p>}

        {/* ── Ask form with optional page range ──────────────────────── */}
        <form onSubmit={handleAsk} className="ask-form">
          <div className="ask-inputs">
            <input
              type="text"
              className="ask-question-input"
              placeholder={
                hasCompletedDocs
                  ? "Ask a question about your documents…"
                  : "Waiting for documents to finish processing…"
              }
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              disabled={!hasCompletedDocs || asking}
            />
            <input
              type="text"
              className="ask-pagerange-input"
              placeholder="Pages (e.g. 2-5)"
              value={pageRange}
              onChange={(e) => setPageRange(e.target.value)}
              disabled={!hasCompletedDocs || asking}
              title="Optional: restrict search to specific pages. Examples: 3  |  2-5  |  1,3,5"
            />
          </div>
          <button
            type="submit"
            disabled={!hasCompletedDocs || asking || !question.trim()}
          >
            {asking ? "…" : "Ask"}
          </button>
        </form>
      </div>
    </div>
  );
}
