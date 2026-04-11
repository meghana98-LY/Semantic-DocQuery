import { Link } from "react-router-dom";

const STEPS = [
  {
    num: "01",
    title: "Upload your PDFs",
    desc: "Bring in one or more PDF files — digital or scanned. OCR ensures complete text extraction from every page.",
  },
  {
    num: "02",
    title: "Ask in plain language",
    desc: "Type any question. Semantic search and BM25 keyword matching find the most relevant passages across all your documents.",
  },
  {
    num: "03",
    title: "Get cited answers",
    desc: "Every response references its source — document name, similarity score, and the matched passage — so you can verify instantly.",
  },
];

export default function Landing() {
  return (
    <div className="land">
      {/* ── Inline nav ── */}
      <header className="land-nav">
        <span className="land-nav-brand">DocQuery</span>
        <nav className="land-nav-links">
          <Link to="/login">Sign in</Link>
          <Link to="/register" className="land-nav-cta">Get started</Link>
        </nav>
      </header>

      {/* ── Hero ── */}
      <section className="land-hero">
        <span className="land-eyebrow">Document Intelligence</span>
        <h1 className="land-h1">
          Ask anything.<br />
          <span>Get precise answers.</span>
        </h1>
        <p className="land-sub">
          Upload any PDF and query it with natural language. Semantic search surfaces the exact passages that answer your question — with source citations and page references.
        </p>
        <div className="land-actions">
          <Link to="/register" className="btn-ink">Create a free account</Link>
          <Link to="/login" className="btn-ghost">Sign in →</Link>
        </div>
      </section>

      {/* ── How it works ── */}
      <section className="land-steps-section">
        <div className="land-steps-heading">
          <h2>How it works</h2>
          <p>Three steps from upload to insight</p>
        </div>
        <div className="land-steps">
          {STEPS.map((s) => (
            <div key={s.num} className="land-step">
              <span className="land-step-num">{s.num}</span>
              <h3 className="land-step-title">{s.title}</h3>
              <p className="land-step-desc">{s.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="land-footer">
        <p>© {new Date().getFullYear()} DocQuery · Built for document intelligence</p>
      </footer>
    </div>
  );
}

