import { useState, useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import Navbar from "./components/Navbar";
import ProtectedRoute from "./components/ProtectedRoute";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import SessionChat from "./pages/SessionChat";
import { checkHealth } from "./api/client";

function Layout() {
  const location = useLocation();
  const isLanding = location.pathname === "/";
  const isAuth = ["/login", "/register"].includes(location.pathname);

  return (
    <>
      {!isLanding && <Navbar />}
      <main className={isLanding ? "" : isAuth ? "auth-page" : "main-content"}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/session/:sessionId"
            element={
              <ProtectedRoute>
                <SessionChat />
              </ProtectedRoute>
            }
          />
        </Routes>
      </main>
    </>
  );
}

export default function App() {
  const [backendReady, setBackendReady] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      while (!cancelled) {
        try {
          await checkHealth();
          if (!cancelled) setBackendReady(true);
          return;
        } catch {
          if (!cancelled) setAttempt((n) => n + 1);
          await new Promise((r) => setTimeout(r, 2000));
        }
      }
    };

    poll();
    return () => { cancelled = true; };
  }, []);

  if (!backendReady) {
    return (
      <div className="backend-connecting">
        <div className="backend-connecting-card">
          <span className="backend-spinner" />
          <p className="backend-connecting-title">Please wait while backend is loading…</p>
          <p className="backend-connecting-sub">
            Connecting to server, this may take a moment.
          </p>
          {attempt > 3 && (
            <p className="backend-connecting-hint">
              Still trying… ({attempt} attempts)
            </p>
          )}
        </div>
      </div>
    );
  }

  return (
    <BrowserRouter>
      <Layout />
    </BrowserRouter>
  );
}

