import { describe, expect, it } from "vitest";

import { voiceMinutesGaugeFraction } from "./Dashboard.jsx";

describe("billable voice minutes gauge", () => {
  it.each([
    [0, 0],
    [500, 0.3],
    [1000, 0.5],
    [1500, 0.7],
    [2000, 0.9],
    [2250, 1],
    [5000, 1],
    [-10, 0],
  ])("maps %s minutes to %s of the gauge", (minutes, expected) => {
    expect(voiceMinutesGaugeFraction(minutes)).toBeCloseTo(expected);
  });
});
