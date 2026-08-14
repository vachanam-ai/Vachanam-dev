import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

/**
 * In-app confirmation, replacing window.confirm().
 *
 * Vinay 2026-08-14: "POP is so ugly. make it professional." The native dialog
 * is an OS chrome slab — wrong typeface, wrong colours, no theme, and it says
 * "localhost:5173 says" above a message about erasing a clinic. It also
 * can't distinguish "remove one login" from "erase every patient record",
 * which is exactly the distinction that should be loudest.
 *
 * API mirrors window.confirm so call sites stay one line:
 *
 *     const confirm = useConfirm();
 *     if (await confirm({ title, body, confirmLabel, destructive: true })) ...
 *
 * Behaviour that the native dialog gets right and a hand-rolled one usually
 * doesn't, so it is all here: Escape cancels, the backdrop cancels, focus moves
 * into the dialog and returns to the trigger afterwards, background scroll is
 * locked, and CANCEL is focused first — on a destructive prompt the safe
 * option should be the one a stray Enter hits.
 */
const ConfirmContext = createContext(null);

export function useConfirm() {
  const ctx = useContext(ConfirmContext);
  if (!ctx) {
    // A missing provider must not silently fall back to window.confirm — that
    // would reintroduce the thing this replaces, invisibly.
    throw new Error("useConfirm() requires <ConfirmProvider> above it");
  }
  return ctx;
}

export function ConfirmProvider({ children }) {
  const [request, setRequest] = useState(null);
  const resolver = useRef(null);

  const confirm = useCallback((options) => {
    return new Promise((resolve) => {
      resolver.current = resolve;
      setRequest(typeof options === "string" ? { body: options } : options || {});
    });
  }, []);

  const settle = useCallback((answer) => {
    setRequest(null);
    const resolve = resolver.current;
    resolver.current = null;
    resolve?.(answer);
  }, []);

  const value = useMemo(() => confirm, [confirm]);

  return (
    <ConfirmContext.Provider value={value}>
      {children}
      {request && <ConfirmSurface request={request} onSettle={settle} />}
    </ConfirmContext.Provider>
  );
}

function ConfirmSurface({ request, onSettle }) {
  const {
    title = "Are you sure?",
    body,
    confirmLabel = "Confirm",
    cancelLabel = "Cancel",
    destructive = false,
  } = request;

  const cancelRef = useRef(null);
  const panelRef = useRef(null);
  const returnFocusTo = useRef(null);

  useEffect(() => {
    returnFocusTo.current = document.activeElement;
    // Cancel takes focus: on a destructive prompt, a stray Enter must not
    // confirm. Native confirm() does the same.
    cancelRef.current?.focus();

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onSettle(false);
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;
      // Keep Tab inside the dialog — otherwise focus wanders to the page
      // behind and the user can operate what they were asked about.
      const focusable = panelRef.current.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      const back = returnFocusTo.current;
      if (back && typeof back.focus === "function") back.focus();
    };
  }, [onSettle]);

  return createPortal(
    <div className="confirm-scrim" onMouseDown={(e) => {
      if (e.target === e.currentTarget) onSettle(false);
    }}>
      <div
        ref={panelRef}
        className="confirm-panel"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby={body ? "confirm-body" : undefined}
      >
        <h2 id="confirm-title" className="confirm-title">{title}</h2>
        {body && <p id="confirm-body" className="confirm-body">{body}</p>}
        <div className="confirm-actions">
          <button
            type="button"
            ref={cancelRef}
            className="btn-ghost"
            onClick={() => onSettle(false)}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            className={destructive ? "btn-danger-solid" : "btn-primary"}
            onClick={() => onSettle(true)}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
