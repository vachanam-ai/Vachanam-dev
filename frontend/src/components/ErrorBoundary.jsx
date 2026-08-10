import React from "react";
import { ArrowClockwise, WarningCircle } from "@phosphor-icons/react";

export default class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { hasError: false }; }
  static getDerivedStateFromError() { return { hasError: true }; }
  componentDidCatch(error, info) { console.error("Unhandled UI error:", error, info?.componentStack); }
  handleReload = () => { this.setState({ hasError: false }); window.location.reload(); };
  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <main className="error-boundary">
        <section>
          <span><WarningCircle size={32} weight="duotone" /></span>
          <p>Workspace interrupted</p>
          <h1>Something went wrong</h1>
          <p>Your clinic data is safe. Reload this workspace. If it happens again, contact hello@vachanam.in.</p>
          <button type="button" onClick={this.handleReload} className="btn-primary"><ArrowClockwise size={18} weight="bold" />Reload workspace</button>
        </section>
      </main>
    );
  }
}
