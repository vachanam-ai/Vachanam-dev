import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import App from "./App.jsx";
import { AuthProvider } from "./hooks/useAuth.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import { ActionDialogProvider } from "./components/ActionDialog.jsx";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: true, staleTime: 15_000 }
  }
});

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthProvider>
            <ActionDialogProvider>
              <App />
              <Toaster
              position="top-center"
              toastOptions={{
                style: {
                  fontFamily: "General Sans, sans-serif",
                  border: "1px solid rgb(var(--line2))",
                  borderRadius: "14px",
                  background: "rgb(var(--surface))",
                  color: "rgb(var(--ink))",
                  boxShadow: "var(--shadow-float)"
                }
              }}
              />
            </ActionDialogProvider>
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>
);
