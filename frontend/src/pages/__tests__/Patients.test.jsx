import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const listPatients = vi.fn();
const deletePatient = vi.fn();

vi.mock("../../api/patients.js", () => ({
  listPatients: (...args) => listPatients(...args),
  deletePatient: (...args) => deletePatient(...args),
  editPatient: vi.fn(),
  fetchUpcoming: vi.fn(() => Promise.resolve({ appointments: [] })),
  importPatients: vi.fn(),
}));
vi.mock("../../api/client.js", () => ({ fetchDoctors: vi.fn(() => Promise.resolve([])) }));
vi.mock("../../hooks/useAuth.jsx", () => ({ useAuth: () => ({ branchId: "branch-1" }) }));

import Patients from "../Patients.jsx";

function renderPatients() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <Patients />
    </QueryClientProvider>,
  );
}

describe("patient erasure", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listPatients.mockResolvedValue([
      { id: "p1", name: "Vinay", age: 24, phone: "+918096007554", last_doctor: "Srinivas" },
      { id: "p2", name: "Lakshmi", age: 45, phone: "+916303620981", last_doctor: "Lakshmi" },
    ]);
    deletePatient.mockResolvedValue({ erased: true });
  });

  it("keeps both confirmation actions on the selected patient row", async () => {
    renderPatients();
    const deleteButton = await screen.findByRole(
      "button", { name: "Delete Vinay" }, { timeout: 5000 },
    );
    const patientRow = deleteButton.closest("tr");

    fireEvent.click(deleteButton);

    expect(within(patientRow).getByText("Erase Vinay permanently?")).toBeInTheDocument();
    expect(within(patientRow).getByRole("button", { name: "Confirm erasure" })).toBeInTheDocument();
    expect(within(patientRow).getByRole("button", { name: "Keep patient" })).toBeInTheDocument();
    expect(screen.queryByText("Erase Lakshmi permanently?")).not.toBeInTheDocument();
  });

  it("erases only after the second inline confirmation", async () => {
    renderPatients();
    fireEvent.click(await screen.findByRole(
      "button", { name: "Delete Vinay" }, { timeout: 5000 },
    ));
    expect(deletePatient).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Confirm erasure" }));

    await waitFor(() => expect(deletePatient).toHaveBeenCalledWith("p1", "branch-1"));
  });
});
