// Replaces backend redaction markers like [EMAIL REDACTED], [REDACTED], etc.
// with a solid colored bar that visually covers the sensitive area.
const REDACT_RE = /(\[(?:[A-Z0-9-]+ )*REDACTED\])/g;

export default function RedactedText({ text }) {
  if (!text) return null;

  const parts = text.split(REDACT_RE);

  return (
    <span>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <span
            key={i}
            className="redact-block"
            title="Sensitive data — redacted"
            aria-label="Redacted"
          />
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </span>
  );
}
