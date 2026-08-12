import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Provider } from "react-redux";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { store } from "./app/store";
import { RequireAuth } from "./features/auth/RequireAuth";
import { HomePage } from "./pages/home/HomePage";
import { RecorderPage } from "./pages/recorder/RecorderPage";
import { AdminPage } from "./pages/admin/AdminPage";
import { TranslatePage } from "./pages/translate/TranslatePage";
import "./index.css";

// This is the last page in the staged migration - all four post-login
// pages are now client-side routes of this one SPA.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Provider store={store}>
      <BrowserRouter>
        <Routes>
          <Route
            path="/home"
            element={
              <RequireAuth>
                <HomePage />
              </RequireAuth>
            }
          />
          <Route
            path="/app"
            element={
              <RequireAuth>
                <RecorderPage />
              </RequireAuth>
            }
          />
          <Route
            path="/admin"
            element={
              <RequireAuth adminOnly>
                <AdminPage />
              </RequireAuth>
            }
          />
          <Route
            path="/translate"
            element={
              <RequireAuth>
                <TranslatePage />
              </RequireAuth>
            }
          />
          <Route path="*" element={<Navigate to="/home" replace />} />
        </Routes>
      </BrowserRouter>
    </Provider>
  </StrictMode>,
);
