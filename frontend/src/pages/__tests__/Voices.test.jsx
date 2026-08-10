import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Voices from "../Voices.jsx";
import {
  activateVoiceClone, fetchBranchSettings, fetchVoiceClones, getBranchVoices,
} from "../../api/client.js";

vi.mock("../../hooks/useAuth.jsx", () => ({ useAuth: () => ({ branchId: "branch-a" }) }));
vi.mock("../../api/client.js", () => ({
  activateVoiceClone: vi.fn(), createVoiceClone: vi.fn(), deleteVoiceClone: vi.fn(),
  fetchBranchSettings: vi.fn(), fetchVoiceClones: vi.fn(), getBranchVoices: vi.fn(),
  previewVoiceClone: vi.fn(), setBranchVoice: vi.fn(),
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><Voices /></QueryClientProvider>);
}

describe("Voices", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchBranchSettings.mockResolvedValue({ language: "te", tts_voice: "Priya" });
    getBranchVoices.mockResolvedValue({ current: "Priya", voices: [{ voice_id: "Priya", display_name: "Priya", gender: "female", kind: "catalog" }] });
    fetchVoiceClones.mockResolvedValue({ clinic_count: 0, voices: [], sync_warning: null });
  });

  it("starts consent-gated and shows the composed empty state", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "A voice patients remember" })).toBeInTheDocument();
    expect(await screen.findByText("No custom voices yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Create Soniox voice/i })).toBeDisabled();
    expect(screen.getByText(/explicit permission/i)).toBeInTheDocument();
  });

  it("activates only a ready branch-owned clone", async () => {
    fetchVoiceClones.mockResolvedValue({
      clinic_count: 1, sync_warning: null,
      voices: [{ id: "local-1", voice_id: "provider-1", name: "Clinic voice", filename: "sample.webm", status: "ready", active: false }],
    });
    activateVoiceClone.mockResolvedValue({ active: true, tts_voice: "provider-1" });
    renderPage();
    const useButton = await screen.findByRole("button", { name: "Use this voice" });
    fireEvent.click(useButton);
    await waitFor(() => expect(activateVoiceClone).toHaveBeenCalledWith("branch-a", "local-1"));
  });
});
