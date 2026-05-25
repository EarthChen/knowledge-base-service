import { useEffect, useState, useCallback, createContext, useContext } from "react";
import { X, CheckCircle2, AlertCircle, Info } from "lucide-react";

type ToastType = "success" | "error" | "info";

interface Toast {
  id: number;
  type: ToastType;
  message: string;
}

interface ToastContextType {
  toast: (type: ToastType, message: string) => void;
}

const ToastContext = createContext<ToastContextType>({ toast: () => {} });

let globalToastHandler: ToastContextType["toast"] | null = null;

/** Register toast handler for non-React contexts (e.g. QueryClient mutation onError). */
export function registerGlobalToast(handler: ToastContextType["toast"] | null) {
  globalToastHandler = handler;
}

export function showGlobalToast(type: ToastType, message: string) {
  if (globalToastHandler) {
    globalToastHandler(type, message);
  }
}

let nextId = 0;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((type: ToastType, message: string) => {
    const id = nextId++;
    setToasts((prev) => [...prev, { id, type, message }]);
  }, []);

  const remove = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  useEffect(() => {
    registerGlobalToast(addToast);
    return () => registerGlobalToast(null);
  }, [addToast]);

  return (
    <ToastContext.Provider value={{ toast: addToast }}>
      {children}
      <div
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="pointer-events-none fixed right-4 top-4 z-50 flex flex-col gap-2"
      >
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onDismiss={() => remove(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}

const ICON_MAP = {
  success: CheckCircle2,
  error: AlertCircle,
  info: Info,
};

const STYLE_MAP = {
  success:
    "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300",
  error:
    "border-red-200 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950/80 dark:text-red-300",
  info: "border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-800 dark:bg-sky-950/80 dark:text-sky-300",
};

const ARIA_MAP = {
  error: { role: "alert", "aria-live": "assertive" },
  success: { role: "status", "aria-live": "polite" },
  info: { role: "status", "aria-live": "polite" },
} as const;

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const Icon = ICON_MAP[toast.type];
  const aria = ARIA_MAP[toast.type];

  useEffect(() => {
    const timer = setTimeout(onDismiss, 4000);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  return (
    <div
      role={aria.role}
      aria-live={aria["aria-live"]}
      className={`pointer-events-auto flex items-center gap-2.5 rounded-lg border px-4 py-3 text-sm shadow-lg backdrop-blur-sm ${STYLE_MAP[toast.type]}`}
    >
      <Icon size={16} aria-hidden={true} />
      <span className="max-w-xs">{toast.message}</span>
      <button
        type="button"
        aria-label="Dismiss notification"
        onClick={onDismiss}
        className="ml-2 rounded p-0.5 opacity-60 hover:opacity-100 dark:text-gray-200"
      >
        <X size={14} aria-hidden={true} />
      </button>
    </div>
  );
}
