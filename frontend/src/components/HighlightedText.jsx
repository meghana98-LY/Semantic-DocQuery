// Highlights query terms inside a text snippet AND renders solid blocks
// for backend redaction markers like [EMAIL REDACTED], [PAN REDACTED], etc.

const REDACT_RE = /(\[(?:[A-Z0-9-]+ )*REDACTED\])/g;

export default function HighlightedText({ text, query }) {
  if (!text) return null;

  // Build highlight regex from query words
  const words = query
    ? query
        .split(/\s+/)
        .filter((w) => w.length > 2)
        .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    : [];
  const highlightRe = words.length
    ? new RegExp(`(${words.join("|")})`, "gi")
    : null;

  // First split on redaction markers (capturing group → odd indices are markers)
  const redactParts = text.split(REDACT_RE);

  return (
    <span>
      {redactParts.map((part, i) => {
        // Odd index = redaction marker → render solid block
        if (i % 2 === 1) {
          return (
            <span
              key={i}
              className="redact-block"
              title="Sensitive data — redacted"
              aria-label="Redacted"
            />
          );
        }

        if (!part) return null;

        // Even index = plain text → apply keyword highlighting
        if (!highlightRe) return <span key={i}>{part}</span>;

        const hlParts = part.split(highlightRe);
        return (
          <span key={i}>
            {hlParts.map((hlPart, j) =>
              j % 2 === 1 ? (
                <mark key={j} className="snippet-highlight">
                  {hlPart}
                </mark>
              ) : (
                <span key={j}>{hlPart}</span>
              )
            )}
          </span>
        );
      })}
    </span>
  );
}
