import HighlightedText from "./HighlightedText";
import RedactedText from "./RedactedText";

// Source cards rendered below an assistant answer.
export default function SourceCards({ sources, query }) {
  if (!sources || sources.length === 0) return null;

  return (
    <div className="sources-panel">
      <p className="sources-label">Top {sources.length} Relevant Chunk{sources.length !== 1 ? "s" : ""}</p>
      {sources.map((src, i) => (
        <div key={i} className="source-card">
          {/* Header row: rank · doc name · page · similarity */}
          <div className="source-meta">
            <span className="source-rank">#{i + 1}</span>
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
              title="Cosine similarity score (0–1)"
            >
              {typeof src.similarity_score === "number"
                ? src.similarity_score.toFixed(4)
                : "—"}
            </span>
          </div>

          {/* Per-chunk relevant summary — shown first, prominently */}
          {src.summary && (
            <div className="chunk-section chunk-summary-section">
              <span className="chunk-section-label">Summary</span>
              <p className="chunk-summary">
                <RedactedText text={src.summary} />
              </p>
            </div>
          )}

          {/* Raw chunk text with keyword highlighting */}
          <div className="chunk-section">
            <span className="chunk-section-label">Raw Chunk</span>
            <p className="source-snippet">
              <HighlightedText text={src.snippet} query={query} />
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

