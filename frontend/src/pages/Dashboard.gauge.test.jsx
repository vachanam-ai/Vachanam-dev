import { describe, expect, it } from "vitest";

import { voiceMinutesGaugeFraction } from "./Dashboard.jsx";

describe("billable voice minutes gauge", () => {
  it.each([
    [0, 0],
    [1000, 0.3],
    [3000, 0.5],
    [7000, 0.8],
    [16000, 0.895],
    [25000, 0.99],
    [100000, 0.99],
    [-10, 0],
  ])("maps %s minutes to %s of the gauge", (minutes, expected) => {
    expect(voiceMinutesGaugeFraction(minutes)).toBeCloseTo(expected);
  });

  it("never reaches 100%", () => {
    expect(voiceMinutesGaugeFraction(Number.MAX_SAFE_INTEGER)).toBeLessThan(1);
  });
});
