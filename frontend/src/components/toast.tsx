import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

export type ToastTone = "info" | "success" | "warning" | "danger";

interface ToastOptions {
  message: string;
  tone?: ToastTone;
  duration?: number;
  actionLabel?: string;
  action?: () => void;
}

interface ToastState extends ToastOptions {
  visible: boolean;
}

interface ToastContextValue {
  showToast: (options: ToastOptions) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider(props: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastState | null>(null);

  const showToast = useCallback((options: ToastOptions) => {
    setToast({ ...options, visible: true });
  }, []);

  const hideToast = useCallback(() => {
    setToast((current) => (current ? { ...current, visible: false } : current));
  }, []);

  useEffect(() => {
    if (!toast) {
      return;
    }
    const duration = toast.duration ?? 6000;
    const timer = window.setTimeout(() => setToast(null), duration);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const renderedToast = useMemo(() => {
    if (!toast) {
      return null;
    }
    return (
      <div className={`toast-card toast-tone-${toast.tone ?? "info"}${toast.visible ? " is-visible" : ""}`}>
        <div className="toast-message">{toast.message}</div>
        <div className="toast-actions">
          {toast.actionLabel && toast.action ? (
            <button type="button" className="toast-button" onClick={() => {
              toast.action?.();
              hideToast();
            }}>
              {toast.actionLabel}
            </button>
          ) : null}
          <button type="button" className="toast-close" onClick={hideToast} aria-label="Dismiss notification">
            ×
          </button>
        </div>
      </div>
    );
  }, [hideToast, toast]);

  return (
    <ToastContext.Provider value={{ showToast }}>
      {props.children}
      <div className="toast-portal">{renderedToast}</div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return context;
}
