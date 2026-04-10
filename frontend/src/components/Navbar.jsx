import { Link, useNavigate } from "react-router-dom";

export default function Navbar() {
  const navigate = useNavigate();
  const token = localStorage.getItem("token");

  const handleLogout = () => {
    localStorage.removeItem("token");
    navigate("/");
  };

  return (
    <nav className="navbar">
      <Link to="/" className="navbar-brand">
        Semantic DocQuery
      </Link>
      {token && (
        <div className="navbar-actions">
          <button onClick={handleLogout} className="logout-btn">
            Logout
          </button>
        </div>
      )}
    </nav>
  );
}
