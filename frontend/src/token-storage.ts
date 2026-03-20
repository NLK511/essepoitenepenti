const STORAGE_KEY = "trade-proposer-auth-token";

export function readStoredToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  const value = window.localStorage.getItem(STORAGE_KEY);
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

export function saveStoredToken(token: string | null): void {
  if (typeof window === "undefined") {
    return;
  }
  if (token && token.trim()) {
    window.localStorage.setItem(STORAGE_KEY, token.trim());
  } else {
    window.localStorage.removeItem(STORAGE_KEY);
  }
}
