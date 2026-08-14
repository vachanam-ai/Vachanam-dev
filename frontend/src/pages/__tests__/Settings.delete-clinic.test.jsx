import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

// Vinay 2026-08-14: "DELETE not working."
//
// The Jul-25 security review made /auth/delete-account require a FRESH Google
// ID token for password-less accounts — the typed "DELETE" is a UI guard, not
// authentication. The frontend kept posting {confirm:"DELETE"} with no token,
// so the API answered 401 "Google re-verification required to delete" every
// time and the button silently did nothing. Broken for three weeks.
//
// These tests pin BOTH paths, because the failure was an asymmetry between
// what the UI sent and what the API demanded.

const deleteAccount = vi.fn(() => Promise.resolve({ deleted: true }));
const logout = vi.fn();
let googleToken = "fresh-google-id-token";

vi.mock("../../api/client.js", () => ({
  fetchBranchSettings: () => Promise.resolve(settingsPayload),
  updateBranchSettings: vi.fn(() => Promise.resolve(settingsPayload)),
  fetchDoctors: () => Promise.resolve([]),
  fetchStaff: () => Promise.resolve([]),
  fetchPlan: () => Promise.resolve({ plan: "clinic", status: "active" }),
  addStaff: vi.fn(),
  removeStaff: vi.fn(),
  deleteAccount: (...a) => deleteAccount(...a),
  getBranchFaq: () => Promise.resolve([]),
  saveBranchFaq: vi.fn(),
  testCalendar: vi.fn(),
}));

vi.mock("../../hooks/useAuth.jsx", () => ({
  useAuth: () => ({
    user: { role: "org_admin", user_id: "u1" },
    branchId: "b1",
    branches: [{ branch_id: "b1", name: "Main" }],
    logout,
  }),
  roleHome: () => "/queue",
}));

// Stand in for Google Identity Services: renders a button that hands back a
// credential, which is exactly the contract GoogleReauth relies on.
vi.mock("../../components/GoogleReauth.jsx", () => ({
  default: ({ onToken, disabled }) => (
    <button type="button" disabled={disabled} onClick={() => onToken(googleToken)}>
      Confirm with Google
    </button>
  ),
}));

let settingsPayload;

beforeEach(() => {
  settingsPayload = {
    branch_id: "b1", name: "Clinic", allowed_languages: [],
    doctors_count: 1, staff_count: 1, whatsapp_status: "none",
  };
  deleteAccount.mockClear();
  logout.mockClear();
  vi.stubGlobal("confirm", vi.fn(() => true));
});

afterEach(cleanup);

function renderSettings() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return import("../Settings.jsx").then(({ default: Settings }) =>
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Settings />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
}

async function typeConfirm(value) {
  const input = await screen.findByPlaceholderText("Password or DELETE");
  fireEvent.change(input, { target: { value } });
  return input;
}

describe("delete clinic — Google account", () => {
  it("sends a fresh Google id_token, not just the typed word", async () => {
    await renderSettings();
    await typeConfirm("DELETE");

    fireEvent.click(screen.getByRole("button", { name: /Confirm with Google/i }));

    await waitFor(() => expect(deleteAccount).toHaveBeenCalled());
    expect(deleteAccount).toHaveBeenCalledWith({
      confirm: "DELETE",
      id_token: "fresh-google-id-token",
    });
  });

  it("never posts confirm without a token — the exact 401 that broke it", async () => {
    await renderSettings();
    await typeConfirm("DELETE");
    fireEvent.click(screen.getByRole("button", { name: /Confirm with Google/i }));

    await waitFor(() => expect(deleteAccount).toHaveBeenCalled());
    const payload = deleteAccount.mock.calls[0][0];
    expect(payload.id_token).toBeTruthy();
  });

  it("swaps the red button for the Google step-up once DELETE is typed", async () => {
    await renderSettings();
    // Before: the plain destructive button (findBy — the page loads async).
    expect(
      await screen.findByRole("button", { name: /Delete clinic permanently/i }),
    ).toBeTruthy();

    await typeConfirm("DELETE");

    expect(screen.getByRole("button", { name: /Confirm with Google/i })).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: /Delete clinic permanently/i }),
    ).toBeNull();
  });

  it("explains why a second sign-in is needed", async () => {
    await renderSettings();
    await typeConfirm("DELETE");
    expect(screen.getByText(/fresh\s+sign-in/i)).toBeTruthy();
  });

  it("still asks for confirmation before erasing", async () => {
    globalThis.confirm.mockReturnValueOnce(false);
    await renderSettings();
    await typeConfirm("DELETE");
    fireEvent.click(screen.getByRole("button", { name: /Confirm with Google/i }));
    expect(deleteAccount).not.toHaveBeenCalled();
  });

  it("signs the owner out after a successful delete", async () => {
    await renderSettings();
    await typeConfirm("DELETE");
    fireEvent.click(screen.getByRole("button", { name: /Confirm with Google/i }));
    await waitFor(() => expect(logout).toHaveBeenCalled());
  });
});

describe("delete clinic — password account", () => {
  it("still sends the password and no token", async () => {
    await renderSettings();
    await typeConfirm("hunter2hunter2");

    fireEvent.click(
      screen.getByRole("button", { name: /Delete clinic permanently/i }),
    );

    await waitFor(() => expect(deleteAccount).toHaveBeenCalled());
    expect(deleteAccount).toHaveBeenCalledWith({ password: "hunter2hunter2" });
  });

  it("keeps the destructive button disabled while the field is empty", async () => {
    await renderSettings();
    const button = await screen.findByRole("button", {
      name: /Delete clinic permanently/i,
    });
    expect(button.disabled).toBe(true);
  });
});
