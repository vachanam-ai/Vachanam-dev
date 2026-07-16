import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Regression for FIXLOG #380: the "Add team member" form referenced
// `unlinkedDoctors` (and `allDoctors`) that were never defined, so selecting
// Role = Doctor threw a ReferenceError and white-screened the whole Settings
// page. This test picks Doctor and asserts the doctor dropdown renders — it
// would throw if either variable were undefined again.

const doctor = { id: "d1", name: "Dr Meera", user_id: null };

vi.mock("../api/client.js", () => ({
  fetchBranchSettings: vi.fn(() =>
    Promise.resolve({ name: "Test Clinic", allowed_languages: [], doctors_count: 1, staff_count: 1 })
  ),
  fetchStaff: vi.fn(() => Promise.resolve([])),
  fetchDoctors: vi.fn(() => Promise.resolve([doctor])),
  fetchPlan: vi.fn(() => Promise.resolve({ plan: "clinic", status: "active" })),
  getBranchFaq: vi.fn(() => Promise.resolve([])),
  getBranchVoices: vi.fn(() => Promise.resolve([])),
  addStaff: vi.fn(),
  changePlan: vi.fn(),
  cloneBranchVoice: vi.fn(),
  createPaymentOrder: vi.fn(),
  registerClonedVoice: vi.fn(),
  removeClonedVoice: vi.fn(),
  saveBranchFaq: vi.fn(),
  setBranchVoice: vi.fn(),
  testCalendar: vi.fn(),
  updateBranchSettings: vi.fn(),
  verifyPayment: vi.fn(),
}));
vi.mock("../hooks/useAuth.jsx", () => ({
  useAuth: () => ({ branchId: "b1", user: { role: "owner" } }),
}));
vi.mock("../lib/recorder.js", () => ({ startRecording: vi.fn() }));

import Settings from "./Settings.jsx";

afterEach(cleanup);

function renderSettings() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Settings />
    </QueryClientProvider>
  );
}

describe("Settings — doctor account creation", () => {
  it("selecting Role = Doctor renders the doctor dropdown without crashing", async () => {
    renderSettings();

    // Once data loads, the add-team form's Role select carries a "Doctor"
    // option. Find it, switch the select to "doctor".
    const doctorOption = await screen.findByRole("option", { name: "Doctor" });
    const roleSelect = doctorOption.closest("select");
    fireEvent.change(roleSelect, { target: { value: "doctor" } });

    // The doctor dropdown (unlinkedDoctors) must render our unlinked doctor —
    // this throws if unlinkedDoctors/allDoctors are undefined again.
    await waitFor(() => expect(screen.getByText("Dr Meera")).toBeInTheDocument());
  });
});
