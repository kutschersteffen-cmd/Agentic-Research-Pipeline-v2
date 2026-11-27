import { Component, type ErrorInfo, type ReactNode } from "react";

interface State { error: Error | null }

interface Props {
  children: ReactNode;
  resetKey?: unknown;
}

/** Catches a crash in one screen, shows what happened with "Try again", and leaves the rest of the app standing.
 * Not keyed by the route, so a screen that is not in error is never remounted; a change of address clears the error. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: unknown): State {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("This screen stopped working", error, info.componentStack);
  }

  componentDidMount() {
    window.addEventListener("hashchange", this.onHash);
  }

  componentDidUpdate(prevProps: Props) {
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  componentWillUnmount() {
    window.removeEventListener("hashchange", this.onHash);
    clearTimeout(this.timer);
  }

  timer: ReturnType<typeof setTimeout> | undefined;

  // After App has taken the new route, so the screen that crashed is not rendered again first.
  onHash = () => {
    clearTimeout(this.timer);
    this.timer = setTimeout(this.reset, 0);
  };

  reset = () => {
    if (this.state.error) this.setState({ error: null });
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="card" role="alert">
        <h2>This screen stopped working</h2>
        <p>Something went wrong while showing it. The rest of the app still works: try again, or open another screen.</p>
        <button type="button" onClick={this.reset}>Try again</button>
        <details>
          <summary>Error details</summary>
          <pre>{error.message}</pre>
        </details>
      </div>
    );
  }
}
