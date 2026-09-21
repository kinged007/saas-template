import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

/** Catches render/effect crashes and shows a readable message instead of a blank page. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Full component stack — the message alone (e.g. removeChild) never
    // identifies the crashing component; the stack does.
    console.error("[error-boundary]", error, info.componentStack);
    (window as unknown as { __lastErrorStack?: string }).__lastErrorStack =
      info.componentStack ?? undefined;
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div
          style={{
            minHeight: "100vh",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "#fff1f0",
            padding: 24,
            fontFamily: "system-ui, sans-serif",
          }}
        >
          <div style={{ maxWidth: 640 }}>
            <h1 style={{ color: "#cf1322" }}>Something went wrong</h1>
            <pre
              style={{
                background: "#fff",
                border: "1px solid #ffccc7",
                borderRadius: 6,
                padding: 16,
                overflow: "auto",
                whiteSpace: "pre-wrap",
              }}
            >
              {this.state.error.message}
            </pre>
            <button
              onClick={() => {
                this.setState({ error: null });
              }}
              style={{ marginTop: 12, padding: "6px 16px", cursor: "pointer" }}
            >
              Try again
            </button>
            {/* plain anchor: the boundary renders outside the router */}
            <a href="/" style={{ marginLeft: 8, padding: "6px 16px" }}>
              Go to dashboard
            </a>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
