import { FormEvent, useMemo, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth";

type LoginLocationState = {
  from?: {
    pathname: string;
  };
};

export function LoginPage() {
  const { token, login } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const destination = (location.state as LoginLocationState | null)?.from?.pathname ?? "/";

  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submitDisabled = submitting || username.trim() === "" || password === "";

  const helperText = useMemo(
    () => "Use the username and password configured by SINGLE_USER_AUTH_USERNAME/SINGLE_USER_AUTH_PASSWORD.",
    [],
  );

  if (token) {
    return <Navigate to={destination} replace />;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username.trim(), password);
      navigate(destination, { replace: true });
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-page">
      <section className="panel login-panel">
        <div className="page-header">
          <div>
            <div className="kicker">Authentication</div>
            <h1 className="page-title">Sign in</h1>
            <p className="page-subtitle">Enter the credentials for the single-user guard to continue.</p>
          </div>
        </div>
        <p className="helper-text">{helperText}</p>
        {error ? <div className="alert alert-danger">{error}</div> : null}
        <form className="stack-form" onSubmit={handleSubmit}>
          <label className="form-field">
            <span>Username</span>
            <input
              type="text"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label className="form-field">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          <div className="form-actions">
            <button type="submit" className="button" disabled={submitDisabled}>
              {submitting ? "Authenticating…" : "Sign in"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
