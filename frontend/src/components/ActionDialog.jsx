import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

const DialogContext = createContext({ ask: async () => false });

export function ActionDialogProvider({ children }) {
  const [dialog, setDialog] = useState(null);
  const [inputValue, setInputValue] = useState("");
  const confirmRef = useRef(null);
  const resolverRef = useRef(null);

  const close = useCallback((value) => {
    resolverRef.current?.(value);
    resolverRef.current = null;
    setDialog(null);
    setInputValue("");
  }, []);

  const ask = useCallback((options) => new Promise((resolve) => {
    // Resolve a superseded dialog safely instead of leaving a caller waiting.
    resolverRef.current?.(false);
    resolverRef.current = resolve;
    setInputValue(options?.input?.defaultValue ?? "");
    setDialog(options);
  }), []);

  useEffect(() => {
    if (!dialog) return undefined;
    const previous = document.activeElement;
    const onKey = (event) => {
      if (event.key === "Escape") close(false);
    };
    document.addEventListener("keydown", onKey);
    document.body.classList.add("has-action-dialog");
    requestAnimationFrame(() => confirmRef.current?.focus());
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.classList.remove("has-action-dialog");
      previous?.focus?.();
    };
  }, [dialog, close]);

  return (
    <DialogContext.Provider value={{ ask }}>
      {children}
      {dialog && (
        <div className="action-dialog-layer" role="presentation">
          <button className="action-dialog-backdrop" type="button" aria-label="Close dialog" onClick={() => close(false)} />
          <section className={`action-dialog is-${dialog.tone ?? "default"}`} role="alertdialog" aria-modal="true" aria-labelledby="action-dialog-title" aria-describedby="action-dialog-description">
            <div className="action-dialog-icon" aria-hidden><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M10.3 4.2 2.6 17.5A2 2 0 0 0 4.3 20h15.4a2 2 0 0 0 1.7-2.5L13.7 4.2a2 2 0 0 0-3.4 0Z" /><path d="M12 9v4M12 17h.01" strokeLinecap="round" /></svg></div>
            <button className="action-dialog-close" type="button" aria-label="Close" onClick={() => close(false)}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="m6 6 12 12M18 6 6 18" strokeLinecap="round" /></svg></button>
            <div className="action-dialog-copy">
              <p className="action-dialog-kicker">{dialog.eyebrow ?? (dialog.tone === "danger" ? "Irreversible action" : "Please confirm")}</p>
              <h2 id="action-dialog-title">{dialog.title}</h2>
              <p id="action-dialog-description">{dialog.description}</p>
            </div>
            {dialog.input && (
              <label className="action-dialog-input">
                <span>{dialog.input.label}</span>
                <input
                  className="field"
                  autoFocus
                  value={inputValue}
                  inputMode={dialog.input.inputMode}
                  placeholder={dialog.input.placeholder}
                  onChange={(event) => setInputValue(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && inputValue.trim()) close(inputValue.trim());
                  }}
                />
              </label>
            )}
            <div className="action-dialog-actions">
              <button type="button" className="btn-ghost" onClick={() => close(false)}>{dialog.cancelLabel ?? "Cancel"}</button>
              <button
                ref={confirmRef}
                type="button"
                className={dialog.tone === "danger" ? "btn-danger" : "btn-primary"}
                disabled={Boolean(dialog.input && !inputValue.trim())}
                onClick={() => close(dialog.input ? inputValue.trim() : true)}
              >
                {dialog.confirmLabel ?? "Confirm"}
              </button>
            </div>
          </section>
        </div>
      )}
    </DialogContext.Provider>
  );
}

export const useActionDialog = () => useContext(DialogContext).ask;
