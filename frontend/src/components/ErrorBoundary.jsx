import React from "react";

export default class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { hasError: false }; }
  static getDerivedStateFromError() { return { hasError: true }; }
  componentDidMount() {
    // A successful boot clears the one-shot stale-bundle recovery marker.
    this.clearRecovery = window.setTimeout(
      () => window.sessionStorage.removeItem("vachanam_chunk_reload"),
      10_000,
    );
  }
  componentWillUnmount() { window.clearTimeout(this.clearRecovery); }
  componentDidCatch(error, info) {
    console.error("Unhandled UI error:", error, info?.componentStack);
    const message = String(error?.message || error || "");
    const staleBundle = /dynamically imported module|loading chunk|failed to fetch/i.test(message);
    if (staleBundle && !window.sessionStorage.getItem("vachanam_chunk_reload")) {
      // Cloudflare deploys replace hashed lazy-route files. An already-open
      // tab can request the previous hash and crash even though the app and
      // API are healthy. One reload fetches the new HTML + asset manifest.
      window.sessionStorage.setItem("vachanam_chunk_reload", "1");
      window.location.reload();
    }
  }
  handleReload = () => { this.setState({ hasError: false }); window.location.reload(); };
  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <main className="error-boundary">
        <section>
          <span><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden><circle cx="12" cy="12" r="9" /><path d="M12 7v6M12 17h.01" strokeLinecap="round" /></svg></span>
          <p>Workspace interrupted</p>
          <h1>Something went wrong</h1>
          <p>Your clinic data is safe. Reload this workspace. If it happens again, contact hello@vachanam.in.</p>
          <button type="button" onClick={this.handleReload} className="btn-primary"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M20 6v5h-5M19 11a7.5 7.5 0 1 0 .3 3" strokeLinecap="round" strokeLinejoin="round" /></svg>Reload workspace</button>
        </section>
      </main>
    );
  }
}
