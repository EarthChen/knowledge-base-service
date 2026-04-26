import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode; fallbackLabel?: string };
type State = { error: Error | null };

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-red-200 bg-red-50 p-8 text-center dark:border-red-900 dark:bg-red-950/40">
          <p className="text-sm font-medium text-red-800 dark:text-red-200">
            {this.props.fallbackLabel ?? "Something went wrong"}
          </p>
          <p className="max-w-md truncate font-mono text-xs text-red-600 dark:text-red-400">
            {this.state.error.message}
          </p>
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            className="rounded-lg border border-red-200 bg-white px-4 py-2 text-xs font-medium text-red-800 hover:bg-red-50 dark:border-red-800 dark:bg-red-950 dark:text-red-200 dark:hover:bg-red-900"
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
