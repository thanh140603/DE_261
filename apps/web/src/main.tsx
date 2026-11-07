import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./components/AnalyticsAccess";
import { ToastProvider } from "./components/ui";
import { StoreProvider } from "./store";
import "./styles/global.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <StoreProvider>
        <AuthProvider>
          <ToastProvider>
            <App />
          </ToastProvider>
        </AuthProvider>
      </StoreProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
