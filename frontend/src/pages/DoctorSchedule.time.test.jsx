import { describe, expect, it } from "vitest";

import { formatTimeLabel } from "./DoctorSchedule.jsx";

describe("doctor schedule time labels", () => {
  it.each([
    ["00:00", "12:00 AM"],
    ["09:00", "9:00 AM"],
    ["12:00", "12:00 PM"],
    ["17:15", "5:15 PM"],
    ["21:00", "9:00 PM"]
  ])("formats %s as %s", (value, label) => {
    expect(formatTimeLabel(value)).toBe(label);
  });
});
