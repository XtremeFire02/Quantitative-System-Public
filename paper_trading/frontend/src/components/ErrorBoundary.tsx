import React from "react";

interface Props { children: React.ReactNode }
interface State { error: Error | null }

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  reset = () => this.setState({ error: null });

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div style={{
        margin: "40px auto", maxWidth: 600, padding: "28px 32px",
        background: "#0d0000", border: "1px solid #440000",
        borderTop: "3px solid #ff3333", fontFamily: "Courier New",
      }}>
        <div style={{ color: "#ff3333", fontWeight: 700, fontSize: 11, letterSpacing: 1, marginBottom: 12 }}>
          RENDER ERROR
        </div>
        <div style={{ color: "#cccccc", fontSize: 13, marginBottom: 8 }}>
          {error.message}
        </div>
        <pre style={{
          fontSize: 10, color: "#555555", overflowX: "auto",
          background: "#050000", padding: "10px 12px", marginBottom: 16,
          border: "1px solid #2a0000", whiteSpace: "pre-wrap", wordBreak: "break-word",
        }}>
          {error.stack?.slice(0, 600)}
        </pre>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn-primary" onClick={this.reset}>
            ↺ Retry
          </button>
          <button className="btn btn-ghost" onClick={() => window.location.reload()}>
            Reload page
          </button>
        </div>
      </div>
    );
  }
}
