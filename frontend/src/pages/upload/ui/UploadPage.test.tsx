import { configureStore } from "@reduxjs/toolkit";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { baseApi } from "@/shared/api/baseApi";
import authReducer, { setCredentials } from "@/features/auth/model/authSlice";
import type { AuthUser } from "@/features/auth/model/types";
import { UploadPage } from "@/pages/upload/ui/UploadPage";

const user: AuthUser = { id: "u1", username: "ada", full_name: "Ada Lovelace", role: "user" };

function makeStore() {
  const store = configureStore({
    reducer: { auth: authReducer, [baseApi.reducerPath]: baseApi.reducer },
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(baseApi.middleware),
  });
  store.dispatch(setCredentials({ token: "tok", user }));
  return store;
}

function LocationDisplay() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderUploadPage() {
  return render(
    <Provider store={makeStore()}>
      <MemoryRouter initialEntries={["/upload"]}>
        <Routes>
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/home" element={<div>home page</div>} />
        </Routes>
        <LocationDisplay />
      </MemoryRouter>
    </Provider>,
  );
}

describe("UploadPage", () => {
  it("renders the upload form with no recorder/admin content behind it", () => {
    renderUploadPage();
    expect(screen.getByText("Transcribe a file")).toBeInTheDocument();
    expect(screen.queryByText("Press Start and speak.")).not.toBeInTheDocument();
  });

  it("Reset stays on /upload", async () => {
    renderUploadPage();
    await userEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/upload");
  });
});
