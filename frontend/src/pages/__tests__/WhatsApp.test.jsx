import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

// WA MVP1 Task 10 — clinic-authored WhatsApp templates: a list + live phone
// preview (option C). The preview is the whole point: a clinic writing raw
// {{1}} markers gets rejected by Meta and blames us, so the body renders with
// realistic sample data instead of the raw placeholder.

const fetchWaTemplates = vi.fn();
const createWaTemplate = vi.fn();
const deleteWaTemplate = vi.fn();
const fetchBranchSettings = vi.fn(() =>
  Promise.resolve({ name: "Venkateshwara Clinic", whatsapp_status: "connected" })
);

vi.mock("../../api/client.js", () => ({
  fetchWaTemplates: (...args) => fetchWaTemplates(...args),
  createWaTemplate: (...args) => createWaTemplate(...args),
  deleteWaTemplate: (...args) => deleteWaTemplate(...args),
  fetchBranchSettings: (...args) => fetchBranchSettings(...args),
}));
vi.mock("../../hooks/useAuth.jsx", () => ({
  useAuth: () => ({ branchId: "b1", role: "org_admin" }),
}));

import WhatsApp from "../WhatsApp.jsx";
import TemplateEditor from "../../components/TemplateEditor.jsx";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderWithQuery(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // The page reads ?new=1 (the top-bar "New template" action opens the editor
  // through the URL), so it needs a router even though it renders no <Link>.
  return render(
    <MemoryRouter initialEntries={["/whatsapp"]}>
      <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("TemplateEditor — live preview", () => {
  it("previews the message with realistic sample data, not {{1}}", async () => {
    render(<TemplateEditor branch={{ name: "Venkateshwara Clinic" }} />);
    const body = screen.getByLabelText(/message body/i);
    fireEvent.change(body, { target: { value: "Namaste {{1}}, see you {{2}}" } });

    const preview = screen.getByTestId("preview");
    expect(preview).toHaveTextContent("Namaste Ravi, see you tomorrow 10:30 AM");
    expect(preview).not.toHaveTextContent("{{1}}");
    expect(preview).not.toHaveTextContent("{{2}}");
  });

  it("lets the clinic override the sample with its own example value", () => {
    render(<TemplateEditor branch={{ name: "Venkateshwara Clinic" }} />);
    fireEvent.change(screen.getByLabelText(/message body/i), {
      target: { value: "Hi {{1}}!" },
    });
    const exampleInput = screen.getByPlaceholderText("Ravi");
    fireEvent.change(exampleInput, { target: { value: "Priya" } });
    expect(screen.getByTestId("preview")).toHaveTextContent("Hi Priya!");
  });

  it("blocks submit until every placeholder has an example value typed in", () => {
    render(<TemplateEditor />);
    fireEvent.change(screen.getByLabelText(/template name/i), {
      target: { value: "diwali_offer" },
    });
    fireEvent.change(screen.getByLabelText(/message body/i), {
      target: { value: "Hi {{1}}" },
    });
    // No example typed yet — preview shows a friendly sample, but submit stays
    // blocked because Meta needs an actual clinic-supplied example.
    expect(screen.getByRole("button", { name: /submit/i })).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("Ravi"), { target: { value: "Priya" } });
    expect(screen.getByRole("button", { name: /submit/i })).not.toBeDisabled();
  });

  it("blocks submit on a non-lowercase name even with a complete body", () => {
    render(<TemplateEditor />);
    fireEvent.change(screen.getByLabelText(/template name/i), {
      target: { value: "Diwali Offer!" },
    });
    fireEvent.change(screen.getByLabelText(/message body/i), {
      target: { value: "Happy Diwali!" },
    });
    expect(screen.getByRole("button", { name: /submit/i })).toBeDisabled();
  });

  it("calls onSubmit with the typed name, category, body and examples", () => {
    const onSubmit = vi.fn();
    render(<TemplateEditor onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText(/template name/i), {
      target: { value: "diwali_offer" },
    });
    fireEvent.change(screen.getByLabelText(/message body/i), {
      target: { value: "Hi {{1}}!" },
    });
    fireEvent.change(screen.getByPlaceholderText("Ravi"), { target: { value: "Priya" } });
    fireEvent.click(screen.getByRole("button", { name: /submit/i }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "diwali_offer",
        category: "UTILITY",
        body: "Hi {{1}}!",
        examples: ["Priya"],
      })
    );
  });
});

describe("WhatsApp page — template list", () => {
  it("shows Meta's approval state on every template", async () => {
    fetchWaTemplates.mockResolvedValue([
      { name: "booking_confirm", category: "UTILITY", language: "en", status: "APPROVED" },
      { name: "diwali_offer", category: "MARKETING", language: "en", status: "REJECTED" },
    ]);
    renderWithQuery(<WhatsApp />);

    await waitFor(() => expect(screen.getByText("booking_confirm")).toBeInTheDocument());
    expect(screen.getByText(/approved/i)).toBeInTheDocument();
    expect(screen.getByText(/rejected/i)).toBeInTheDocument();
  });

  it("does not offer a delete control for the four system templates", async () => {
    fetchWaTemplates.mockResolvedValue([
      { name: "booking_confirm", category: "UTILITY", language: "en", status: "APPROVED" },
      { name: "diwali_offer", category: "MARKETING", language: "en", status: "PENDING" },
    ]);
    renderWithQuery(<WhatsApp />);

    const bookingRow = await screen.findByTestId("template-row-booking_confirm");
    expect(within(bookingRow).queryByRole("button", { name: /delete/i })).not.toBeInTheDocument();

    const diwaliRow = await screen.findByTestId("template-row-diwali_offer");
    expect(within(diwaliRow).getByRole("button", { name: /delete/i })).toBeInTheDocument();
  });

  it("submits a new template through the editor", async () => {
    fetchWaTemplates.mockResolvedValue([]);
    createWaTemplate.mockResolvedValue({ id: "1", status: "PENDING" });
    renderWithQuery(<WhatsApp />);

    fireEvent.click(await screen.findByRole("button", { name: /new template/i }));
    fireEvent.change(screen.getByLabelText(/template name/i), {
      target: { value: "diwali_offer" },
    });
    fireEvent.change(screen.getByLabelText(/message body/i), {
      target: { value: "Happy Diwali!" },
    });
    fireEvent.click(screen.getByRole("button", { name: /submit/i }));

    await waitFor(() =>
      expect(createWaTemplate).toHaveBeenCalledWith(
        "b1",
        expect.objectContaining({ name: "diwali_offer", body: "Happy Diwali!" })
      )
    );
  });
});
