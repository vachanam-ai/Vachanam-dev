import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.fn();
const fetchDoctors = vi.fn();
const listTreatmentPatients = vi.fn();

vi.mock("../../hooks/useAuth.jsx", () => ({ useAuth: () => auth() }));
vi.mock("../../api/client.js", () => ({ fetchDoctors: (...args) => fetchDoctors(...args) }));
vi.mock("../../api/treatment.js", () => ({
  listTreatmentPatients: (...args) => listTreatmentPatients(...args),
  listNotes: vi.fn(),
  createNote: vi.fn(),
  editNote: vi.fn(),
  listFollowups: vi.fn(),
  replyToPatient: vi.fn(),
  endTreatment: vi.fn(),
  markMessagesRead: vi.fn(),
}));
vi.mock("../../lib/motion.js", () => ({ revealStagger: vi.fn() }));

import Treatments from "../Treatments.jsx";

function renderTreatments() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Treatments />
    </QueryClientProvider>,
  );
}

describe("doctor treatment isolation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchDoctors.mockResolvedValue([
      { id: "doctor-own", name: "Dr Own" },
      { id: "doctor-other", name: "Dr Other" },
    ]);
    listTreatmentPatients.mockResolvedValue([]);
  });

  it("does not expose the cross-doctor filter to a doctor", async () => {
    auth.mockReturnValue({ branchId: "branch-1", role: "doctor" });
    renderTreatments();

    expect(await screen.findByText("No patients under treatment yet.")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Filter by doctor" })).not.toBeInTheDocument();
    expect(screen.queryByText("All doctors")).not.toBeInTheDocument();
    expect(screen.queryByText("Dr Other")).not.toBeInTheDocument();
  });

  it("keeps the clinic-wide filter for an owner", async () => {
    auth.mockReturnValue({ branchId: "branch-1", role: "org_admin" });
    renderTreatments();

    expect(await screen.findByRole("combobox", { name: "Filter by doctor" })).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Dr Other" })).toBeInTheDocument();
  });
});
