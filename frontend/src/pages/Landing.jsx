import { Link } from "react-router-dom";

export default function Landing() {
  return (
    <div className="landing-root">
      {/* ── Hero ── */}
      <div className="landing-hero">
        <div className="landing-hero-inner">
          
          <h1 className="landing-title">
            Semantic<br />
            <span className="landing-title-accent">DocQuery</span>
          </h1>

          <p className="landing-sub">
            Upload any PDF , Ask queries, and get precise, source-cited answers powered by semantic vector
        </p>

          <div className="landing-actions">
            <Link to="/register" className="landing-btn landing-btn-primary">
              Get Started — Register
            </Link>
            <Link to="/login" className="landing-btn landing-btn-secondary">
              Sign In
            </Link>
          </div>
        </div>

       
      </div>
    </div>
  );
}

