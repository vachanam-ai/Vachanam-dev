import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ConfirmProvider, useConfirm } from "../ConfirmDialog.jsx";

// Vinay 2026-08-14: "POP is so ugly. make it professional."
//
// window.confirm is OS chrome — wrong typeface, no theme, and it prefixes
// "localhost says" above a message about erasing a clinic. It also cannot
// distinguish "remove one login" from "erase every patient record", which is
// exactly the distinction that should be loudest.
//
// Replacing it means re-earning the things the native dialog got for free:
// Escape cancels, focus is trapped and restored, background scroll is locked,
// and CANCEL holds focus so a stray Enter never confirms a destructive action.

afterEach(cleanup);

function Harness({ options, onResult }) {
  const confirm = useConfirm();
  return (
    <button type="button" onClick={async () => onResult(await confirm(options))}>
      trigger
    </button>
  );
}

function renderConfirm(options = { title: "Delete it?", body: "Gone for good." }) {
  const onResult = vi.fn();
  render(
    <ConfirmProvider>
      <Harness options={options} onResult={onResult} />
    </ConfirmProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "trigger" }));
  return onResult;
}

describe("ConfirmDialog", () => {
  it("resolves true when confirmed", async () => {
    const onResult = renderConfirm();
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(onResult).toHaveBeenCalledWith(true));
  });

  it("resolves false when cancelled", async () => {
    const onResult = renderConfirm();
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(onResult).toHaveBeenCalledWith(false));
  });

  it("resolves false on Escape", async () => {
    const onResult = renderConfirm();
    await screen.findByRole("alertdialog");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(onResult).toHaveBeenCalledWith(false));
  });

  it("resolves false when the backdrop is clicked", async () => {
    const onResult = renderConfirm();
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.mouseDown(dialog.parentElement);
    await waitFor(() => expect(onResult).toHaveBeenCalledWith(false));
  });

  it("does NOT cancel when the panel itself is clicked", async () => {
    const onResult = renderConfirm();
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.mouseDown(dialog);
    expect(onResult).not.toHaveBeenCalled();
  });

  it("focuses Cancel, so a stray Enter never confirms", async () => {
    renderConfirm({ title: "Erase everything?", destructive: true });
    const cancel = await screen.findByRole("button", { name: "Cancel" });
    await waitFor(() => expect(document.activeElement).toBe(cancel));
  });

  it("marks the destructive action visually distinct", async () => {
    renderConfirm({ title: "Erase?", destructive: true, confirmLabel: "Erase" });
    const button = await screen.findByRole("button", { name: "Erase" });
    expect(button.className).toContain("btn-danger-solid");
  });

  it("uses the normal primary style when not destructive", async () => {
    renderConfirm({ title: "Start pilot?", confirmLabel: "Start" });
    const button = await screen.findByRole("button", { name: "Start" });
    expect(button.className).toContain("btn-primary");
    expect(button.className).not.toContain("danger");
  });

  it("locks background scroll while open and restores it after", async () => {
    renderConfirm();
    await screen.findByRole("alertdialog");
    expect(document.body.style.overflow).toBe("hidden");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(document.body.style.overflow).not.toBe("hidden"));
  });

  it("returns focus to the trigger when it closes", async () => {
    // A real click focuses the button; jsdom's fireEvent.click does not, so
    // focus it explicitly — otherwise there is nothing to restore TO and the
    // test would pass vacuously against a component that restores nothing.
    const onResult = vi.fn();
    render(
      <ConfirmProvider>
        <Harness options={{ title: "Delete it?" }} onResult={onResult} />
      </ConfirmProvider>,
    );
    const trigger = screen.getByRole("button", { name: "trigger" });
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    fireEvent.click(trigger);
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("is announced as an alertdialog with its title and body", async () => {
    renderConfirm({ title: "Remove Dr Srinivas?", body: "Past bookings stay." });
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(screen.getByText("Remove Dr Srinivas?")).toBeTruthy();
    expect(screen.getByText("Past bookings stay.")).toBeTruthy();
  });

  it("accepts a bare string, matching window.confirm's shape", async () => {
    const onResult = renderConfirm("Just checking?");
    expect(await screen.findByText("Just checking?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(onResult).toHaveBeenCalledWith(true));
  });

  it("throws without a provider rather than silently falling back", () => {
    const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() =>
      render(<Harness options={{}} onResult={() => {}} />),
    ).toThrow(/ConfirmProvider/);
    quiet.mockRestore();
  });
});

describe("no native confirms remain", () => {
  // The point of the change: not one survivor, and no new one creeps back.
  const FILES = [
    "src/pages/Settings.jsx",
    "src/pages/Admin.jsx",
    "src/pages/Voices.jsx",
    "src/pages/WhatsApp.jsx",
    "src/pages/DoctorSchedule.jsx",
    "src/components/WaConnectCard.jsx",
  ];

  it.each(FILES)("%s uses the in-app dialog", (file) => {
    const src = readFileSync(resolve(process.cwd(), file), "utf-8");
    expect(src).not.toMatch(/window\.confirm\(/);
    expect(src).toContain("useConfirm");
  });

  it("the provider is mounted above the app", () => {
    const main = readFileSync(resolve(process.cwd(), "src/main.jsx"), "utf-8");
    expect(main).toContain("<ConfirmProvider>");
  });
});
