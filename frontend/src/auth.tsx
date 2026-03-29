import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { saveStoredToken, readStoredToken } from "./token-storage";

type AuthContextValue = {
  token: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => readStoredToken());

  const setToken = useCallback((value: string | null) => {
    setTokenState(value);
    saveStoredToken(value);
  }, []);

  const login = useCallback(
    async (username: string, password: string) => {
      const response = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
        body: new URLSearchParams({ username, password }),
      });
      const responseText = await response.text();
      if (!response.ok) {
        let message = responseText || "Authentication failed";
        try {
          const parsed = JSON.parse(responseText);
          if (parsed && typeof parsed.detail === "string") {
            message = parsed.detail;
          }
        } catch {
          // ignore parsing errors
        }
        throw new Error(message);
      }
      let payload: { token?: string } = {};
      try {
        payload = responseText ? JSON.parse(responseText) : {};
      } catch {
        // ignore
      }
      if (!payload.token) {
        throw new Error("Authentication token missing");
      }
      setToken(payload.token);
    },
    [setToken],
  );

  const logout = useCallback(() => {
    setToken(null);
  }, [setToken]);

  const value = useMemo(() => ({ token, login, logout }), [token, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

export function RequireAuth({ children }: { children: JSX.Element }) {
  const { token } = useAuth();
  const location = useLocation();
  if (!token) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return children;
}
