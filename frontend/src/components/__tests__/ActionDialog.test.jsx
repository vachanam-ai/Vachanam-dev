import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ActionDialogProvider, useActionDialog } from "../ActionDialog.jsx";

function Harness({ onResult, input = false }) {
  const ask = useActionDialog();
  return (
    <button type="button" onClick={async () => onResult(await ask({
      title: "Delete clinic?",
      description: "Every tenant record will be removed.",
      confirmLabel: "Delete everything",
      tone: "danger",
      input: input ? { label: "Minute adjustment", defaultValue: "0" } : undefined,
    }))}>Open</button>
  );
}

describe("ActionDialog", () => {
  it("uses an accessible branded confirmation instead of a browser popup", async () => {
    let result;
    render(<ActionDialogProvider><Harness onResult={(value) => { result = value; }} /></ActionDialogProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(screen.getByRole("alertdialog")).toHaveAccessibleName("Delete clinic?");
    fireEvent.click(screen.getByRole("button", { name: "Delete everything" }));
    await waitFor(() => expect(result).toBe(true));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("returns typed input and Escape cancels", async () => {
    const results = [];
    const { rerender } = render(<ActionDialogProvider><Harness input onResult={(value) => results.push(value)} /></ActionDialogProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    fireEvent.change(screen.getByLabelText("Minute adjustment"), { target: { value: "500" } });
    fireEvent.click(screen.getByRole("button", { name: "Delete everything" }));
    await waitFor(() => expect(results).toEqual(["500"]));

    rerender(<ActionDialogProvider><Harness onResult={(value) => results.push(value)} /></ActionDialogProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(results).toEqual(["500", false]));
  });
});
