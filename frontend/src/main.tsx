import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Provider } from "react-redux";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { store } from "@/app/store";
import { RequireAuth } from "@/features/auth/ui/RequireAuth";
import { HomePage } from "@/pages/home/ui/HomePage";
import { RecorderPage } from "@/pages/recorder/ui/RecorderPage";
import { AdminPage } from "@/pages/admin/ui/AdminPage";
import { TranslatePage } from "@/pages/translate/ui/TranslatePage";
import { MyRecordingsPage } from "@/pages/recordings/ui/MyRecordingsPage";
import { UploadPage } from "@/pages/upload/ui/UploadPage";
import "./index.css";

// All six post-login pages are client-side routes of this one SPA.
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
          <Route
            path="/recordings"
            element={
              <RequireAuth>
                <MyRecordingsPage />
              </RequireAuth>
            }
          />
          <Route
            path="/upload"
            element={
              <RequireAuth>
                <UploadPage />
              </RequireAuth>
            }
          />
          <Route path="*" element={<Navigate to="/home" replace />} />
        </Routes>
      </BrowserRouter>
    </Provider>
  </StrictMode>,
);
