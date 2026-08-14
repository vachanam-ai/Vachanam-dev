import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Voices from "../Voices.jsx";
import {
  activateVoiceClone, createVoiceClone, fetchBranchSettings, fetchVoiceClones, getBranchVoices, importVoiceClone, setBranchVoice,
} from "../../api/client.js";
// ConfirmProvider mirrors main.jsx: the app mounts it above every page.
import { ConfirmProvider } from "../../components/ConfirmDialog.jsx";

vi.mock("../../hooks/useAuth.jsx", () => ({ useAuth: () => ({ branchId: "branch-a" }) }));
vi.mock("../../api/client.js", () => ({
  activateVoiceClone: vi.fn(), createVoiceClone: vi.fn(), deleteVoiceClone: vi.fn(),
  fetchBranchSettings: vi.fn(), fetchVoiceClones: vi.fn(), getBranchVoices: vi.fn(),
  importVoiceClone: vi.fn(),
  previewVoiceClone: vi.fn(), setBranchVoice: vi.fn(),
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>
      <ConfirmProvider><Voices /></ConfirmProvider>
      </QueryClientProvider>);
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

  it("shows a real consent checkbox, keeps one custom voice visible, and blocks a second upload", async () => {
    fetchVoiceClones.mockResolvedValue({
      clinic_count: 1, sync_warning: null,
      voices: [{ id: "local-1", voice_id: "provider-1", name: "Clinic voice", filename: "sample.webm", status: "ready", active: true }],
    });
    renderPage();
    expect(await screen.findByRole("checkbox", { name: /explicit permission/i })).toBeInTheDocument();
    expect(await screen.findByText("1/1 custom voice")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete Clinic voice" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Create Soniox voice/i })).toBeDisabled();
  });

  it("moves the call language control into Voice studio", async () => {
    renderPage();
    const language = await screen.findByLabelText("Agent language");
    fireEvent.change(language, { target: { value: "en" } });
    await waitFor(() => expect(setBranchVoice).toHaveBeenCalledWith("branch-a", null, "en"));
  });

  it("verifies and adds an existing Soniox voice ID", async () => {
    importVoiceClone.mockResolvedValue({
      id: "local-import",
      voice_id: "voice_existing_123",
      name: "Existing clinic voice",
      filename: "Existing Soniox voice",
      status: "ready",
      active: false,
    });
    renderPage();
    await screen.findByRole("heading", { name: "A voice patients remember" });

    fireEvent.change(screen.getByPlaceholderText("e.g. Dr Lakshmi's clinic voice"), {
      target: { value: "Existing clinic voice" },
    });
    fireEvent.change(await screen.findByLabelText("Soniox voice ID"), {
      target: { value: "voice_existing_123" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /explicit permission/i }));
    fireEvent.click(screen.getByRole("button", { name: /Add existing voice/i }));

    await waitFor(() => expect(importVoiceClone).toHaveBeenCalledWith("branch-a", {
      name: "Existing clinic voice",
      voice_id: "voice_existing_123",
      consent_confirmed: true,
    }));
    expect(await screen.findByText("Existing clinic voice")).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
  });

  it("keeps a successful upload in the library while Soniox prepares it", async () => {
    vi.stubGlobal("Audio", class {});
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:voice"), revokeObjectURL: vi.fn() });
    createVoiceClone.mockResolvedValue({
      id: "local-upload", voice_id: "provider-upload", name: "Clinic welcome", filename: "sample.webm", status: "processing", active: false,
    });
    renderPage();
    await screen.findByRole("heading", { name: "A voice patients remember" });
    fireEvent.change(document.querySelector('input[type="file"]'), {
      target: { files: [new File(["clean-audio"], "sample.webm", { type: "audio/webm" })] },
    });
    fireEvent.change(screen.getByPlaceholderText("e.g. Dr Lakshmi's clinic voice"), { target: { value: "Clinic welcome" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /explicit permission/i }));
    fireEvent.click(screen.getByRole("button", { name: /Create Soniox voice/i }));
    await waitFor(() => expect(createVoiceClone).toHaveBeenCalledWith("branch-a", expect.any(FormData)));
    expect(await screen.findByText("Clinic welcome")).toBeInTheDocument();
    expect(screen.getByText("Preparing voice")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});
