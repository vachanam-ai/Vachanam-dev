import React from "react";

/**
 * Top-level safety net. A render-time throw anywhere below this boundary would
 * otherwise unmount the whole React tree and leave the user staring at a blank
 * white screen. Instead we catch it, log the detail to the console (and, in
 * production, this is where a Sentry/log beacon would go), and show a calm,
 * on-brand "something went wrong" card with a reload action.
 *
 * This is NOT a substitute for handling expected errors (API failures, form
 * validation) — those are handled per-page with their own UI. This only exists
 * for the unexpected: the bug we didn't predict. The user should never see a
 * stack trace.
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    // Full detail stays in the console for debugging; never rendered to the user.
    console.error("Unhandled UI error:", error, info?.componentStack);
  }

  handleReload = () => {
    this.setState({ hasError: false });
    window.location.reload();
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div
        style={{
          minHeight: "100dvh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "1.5rem",
          fontFamily: "Outfit, sans-serif",
          background: "#F0FAFA",
          color: "#1A2E2E",
        }}
      >
        <div
          style={{
            maxWidth: "26rem",
            width: "100%",
            textAlign: "center",
            background: "#FFFFFF",
            border: "1px solid #D0E4E4",
            borderRadius: "16px",
            padding: "2rem 1.75rem",
            boxShadow: "0 10px 30px rgba(26, 46, 46, 0.06)",
          }}
        >
          <div style={{ fontSize: "2rem", marginBottom: "0.75rem" }}>🩺</div>
          <h1 style={{ fontSize: "1.25rem", margin: "0 0 0.5rem", fontWeight: 600 }}>
            Something went wrong
          </h1>
          <p style={{ fontSize: "0.95rem", lineHeight: 1.5, color: "#4A6060", margin: "0 0 1.5rem" }}>
            We hit an unexpected hiccup. Your data is safe. Please reload — if it
            keeps happening, reach us at hello@vachanam.in.
          </p>
          <button
            onClick={this.handleReload}
            style={{
              fontFamily: "Outfit, sans-serif",
              fontSize: "0.95rem",
              fontWeight: 600,
              color: "#FFFFFF",
              background: "#008F8F",
              border: "none",
              borderRadius: "10px",
              padding: "0.7rem 1.5rem",
              cursor: "pointer",
            }}
          >
            Reload
          </button>
        </div>
      </div>
    );
  }
}
