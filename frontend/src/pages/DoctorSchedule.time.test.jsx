import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  createDoctor: vi.fn(),
  deleteDoctor: vi.fn(),
  fetchDoctorSchedules: vi.fn(),
  fetchDoctors: vi.fn(),
  fetchTodayQueue: vi.fn(),
  publishDoctorScheduleRange: vi.fn(),
  stopWalkinsToday: vi.fn(),
  updateDoctor: vi.fn(),
}));

const toast = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
}));

vi.mock("../api/client.js", () => api);
vi.mock("sonner", () => ({ toast }));
vi.mock("../components/QuestionsCard.jsx", () => ({ default: () => null }));
vi.mock("../components/ActionDialog.jsx", () => ({
  useActionDialog: () => vi.fn(async () => true),
}));
vi.mock("../hooks/useAuth.jsx", () => ({
  useAuth: () => ({
    branchId: "branch-1",
    role: "doctor",
    user: { user_id: "user-1", email: "doctor@example.com" },
  }),
}));
vi.mock("../lib/motion.js", () => ({ revealStagger: vi.fn() }));

import DoctorSchedule, { datesInRange, formatTimeLabel } from "./DoctorSchedule.jsx";

const doctor = {
  id: "doctor-1",
  user_id: "user-1",
  name: "Dr Asha",
  booking_type: "appointment",
  schedule_mode: "date_specific",
  recurring_schedule: {},
  available_weekdays: [],
  slot_duration_minutes: 15,
};

const isoOffset = (days) => {
  const value = new Date();
  value.setUTCHours(12, 0, 0, 0);
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
};

const scheduleEntry = (date) => ({
  date,
  is_published: false,
  status: "unpublished",
  source: "unpublished",
  sessions: [],
  token_limit: null,
  notes: null,
});

const renderSchedule = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const view = render(
    <QueryClientProvider client={queryClient}>
      <DoctorSchedule />
    </QueryClientProvider>,
  );
  return { ...view, invalidate, queryClient };
};

const openPublisher = async () => {
  fireEvent.click(await screen.findByRole("button", { name: "Manage dates" }));
  await waitFor(() => expect(api.fetchDoctorSchedules).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "+ Publish dates" }));
  return {
    from: screen.getByLabelText("From date"),
    to: screen.getByLabelText("To date"),
  };
};

beforeEach(() => {
  vi.clearAllMocks();
  api.fetchDoctors.mockResolvedValue([doctor]);
  api.fetchTodayQueue.mockResolvedValue({ doctors: [] });
  api.fetchDoctorSchedules.mockResolvedValue([]);
  api.publishDoctorScheduleRange.mockImplementation((_branchId, _doctorId, payload) =>
    Promise.resolve({
      schedules: datesInRange(payload.date_from, payload.date_to).map(scheduleEntry),
    }),
  );
});

afterEach(cleanup);

describe("doctor schedule time labels", () => {
  it.each([
    ["00:00", "12:00 AM"],
    ["09:00", "9:00 AM"],
    ["12:00", "12:00 PM"],
    ["17:15", "5:15 PM"],
    ["21:00", "9:00 PM"],
  ])("formats %s as %s", (value, label) => {
    expect(formatTimeLabel(value)).toBe(label);
  });
});

describe("doctor schedule date ranges", () => {
  it("returns every selected date inclusively", () => {
    expect(datesInRange("2026-08-21", "2026-08-24")).toEqual([
      "2026-08-21",
      "2026-08-22",
      "2026-08-23",
      "2026-08-24",
    ]);
  });

  it("handles blank, same-day, and inverted ranges", () => {
    expect(datesInRange("", "2026-08-24")).toEqual([]);
    expect(datesInRange("2026-08-24", "")).toEqual([]);
    expect(datesInRange("2026-08-24", "2026-08-24")).toEqual(["2026-08-24"]);
    expect(datesInRange("2026-08-24", "2026-08-21")).toEqual([]);
  });

  it("enumerates the accepted 31-day boundary and the rejected 32-day boundary", () => {
    expect(datesInRange("2026-08-01", "2026-08-31")).toHaveLength(31);
    expect(datesInRange("2026-08-01", "2026-09-01")).toHaveLength(32);
  });
});

describe("exact-date range publisher", () => {
  it("keeps From/To ordered and marks every chip inside the selected range", async () => {
    const dates = Array.from({ length: 5 }, (_, index) => isoOffset(index + 1));
    api.fetchDoctorSchedules.mockResolvedValue(dates.map(scheduleEntry));
    const { container } = renderSchedule();
    const { from, to } = await openPublisher();

    fireEvent.change(from, { target: { value: dates[1] } });
    expect(to).toHaveValue(dates[1]);
    fireEvent.change(to, { target: { value: dates[3] } });

    expect(from).toHaveValue(dates[1]);
    expect(to).toHaveValue(dates[3]);
    expect(
      [...container.querySelectorAll('button[aria-label*="Open this date"]')].map((button) =>
        button.getAttribute("aria-label").includes("in selected range"),
      ),
    ).toEqual([false, true, true, true, false]);
    expect(
      container.querySelector('button[aria-label*="Open this date"] [aria-hidden="true"]')
        .getAttribute("style"),
    ).toContain("--slate-light");
    expect(container.querySelector("button[aria-pressed]")).not.toBeInTheDocument();

    fireEvent.change(from, { target: { value: dates[4] } });
    expect(from).toHaveValue(dates[4]);
    expect(to).toHaveValue(dates[4]);
  });

  it("uses labelled 44px controls and exposes validation help to both dates", async () => {
    renderSchedule();
    const { from, to } = await openPublisher();
    const toggle = screen.getByRole("button", { name: "Hide" });
    expect(toggle).toHaveClass("min-h-11");

    expect(from).toHaveAttribute("aria-describedby", expect.stringContaining("range-help"));
    expect(to).toHaveAttribute("aria-describedby", expect.stringContaining("range-help"));
    expect(from).toHaveAttribute("aria-invalid", "false");
    expect(to).toHaveAttribute("aria-invalid", "false");
  });

  it("loads and exposes every selected date even beyond the 15-day strip", async () => {
    api.fetchDoctorSchedules.mockImplementation((_branchId, _doctorId, from, to) =>
      Promise.resolve(datesInRange(from, to).map(scheduleEntry)),
    );
    const { container } = renderSchedule();
    const { from, to } = await openPublisher();
    const selected = [isoOffset(20), isoOffset(21), isoOffset(22)];

    fireEvent.change(from, { target: { value: selected[0] } });
    fireEvent.change(to, { target: { value: selected[2] } });

    await waitFor(() => {
      expect(
        [...container.querySelectorAll("section[aria-labelledby] time")].map((node) =>
          node.getAttribute("datetime"),
        ),
      ).toEqual(selected);
    });
    expect(api.fetchDoctorSchedules).toHaveBeenCalledWith(
      "branch-1", "doctor-1", selected[0], selected[2],
    );
  });

  it("does not carry sessions or notes from another date into unpublished, recurring, or leave entries", async () => {
    const dates = [isoOffset(1), isoOffset(2), isoOffset(3), isoOffset(4)];
    api.fetchDoctorSchedules.mockResolvedValue([
      {
        ...scheduleEntry(dates[0]),
        is_published: true,
        status: "available",
        source: "date_override",
        sessions: [{ start: "10:00", end: "12:00" }],
        notes: "Only for the first date",
      },
      scheduleEntry(dates[1]),
      {
        ...scheduleEntry(dates[2]),
        status: "available",
        source: "recurring",
        sessions: [{ start: "11:00", end: "13:00" }],
      },
      {
        ...scheduleEntry(dates[3]),
        is_published: true,
        status: "unavailable",
        source: "leave",
        notes: "Conference leave",
      },
    ]);
    const { container } = renderSchedule();
    fireEvent.click(await screen.findByRole("button", { name: "Manage dates" }));
    await waitFor(() => {
      expect(container.querySelectorAll('button[aria-label*="Open this date"]')).toHaveLength(4);
    });
    const chips = [...container.querySelectorAll('button[aria-label*="Open this date"]')];

    fireEvent.click(chips[0]);
    expect(screen.getByLabelText("Session 1 start time")).toHaveValue("10:00");
    expect(screen.getByLabelText("Internal note (optional)")).toHaveValue("Only for the first date");

    fireEvent.click(chips[1]);
    expect(screen.queryByLabelText("Session 1 start time")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Internal note (optional)")).toHaveValue("");

    fireEvent.click(chips[2]);
    expect(screen.getByLabelText("Session 1 start time")).toHaveValue("11:00");
    expect(screen.getByLabelText("Internal note (optional)")).toHaveValue("");

    fireEvent.click(chips[3]);
    expect(screen.queryByLabelText("Session 1 start time")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Internal note (optional)")).toHaveValue("");
  });

  it("accepts 31 dates and blocks 32 dates before any API write", async () => {
    renderSchedule();
    const { from, to } = await openPublisher();
    const start = isoOffset(1);
    const day31 = isoOffset(31);
    const day32 = isoOffset(32);

    fireEvent.change(from, { target: { value: start } });
    fireEvent.change(to, { target: { value: day31 } });
    expect(screen.getByRole("button", { name: "Publish 31 dates" })).toBeEnabled();
    expect(screen.queryByText("Choose a range of 31 days or fewer.")).not.toBeInTheDocument();

    fireEvent.change(to, { target: { value: day32 } });
    expect(screen.getByRole("button", { name: "Publish 32 dates" })).toBeDisabled();
    const error = screen.getByRole("alert", { name: "" });
    expect(error).toHaveTextContent("Choose a range of 31 days or fewer.");
    expect(to).toHaveAttribute("aria-invalid", "true");
    expect(to.getAttribute("aria-describedby")).toContain(error.id);
    expect(api.publishDoctorScheduleRange).not.toHaveBeenCalled();
  });

  it("publishes the whole range through one atomic API call and refreshes it", async () => {
    const { invalidate } = renderSchedule();
    const { from, to } = await openPublisher();
    const dates = [isoOffset(1), isoOffset(2), isoOffset(3)];

    fireEvent.change(from, { target: { value: dates[0] } });
    fireEvent.change(to, { target: { value: dates[2] } });
    fireEvent.change(screen.getByLabelText("Internal note (optional)"), {
      target: { value: "Doctor confirmed this range" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Publish 3 dates" }));

    await waitFor(() => expect(api.publishDoctorScheduleRange).toHaveBeenCalledTimes(1));
    expect(api.publishDoctorScheduleRange).toHaveBeenCalledWith("branch-1", "doctor-1", {
      date_from: dates[0],
      date_to: dates[2],
      sessions: [
        { start: "09:00", end: "12:00" },
        { start: "17:00", end: "21:00" },
      ],
      token_limit: null,
      notes: "Doctor confirmed this range",
    });
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Dr Asha's schedule published for 3 dates");
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: ["doctor-schedules", "branch-1", "doctor-1"],
      });
    });
  });

  it("shows exact conflicting dates and never claims an atomic rejection succeeded", async () => {
    const dates = [isoOffset(1), isoOffset(2), isoOffset(3)];
    api.publishDoctorScheduleRange.mockRejectedValue({
      response: {
        data: {
          detail: {
            message: "Schedule range has conflicts. No dates were changed.",
            conflicts: [{
              date: dates[1],
              reasons: ["Schedule would invalidate 1 confirmed appointment(s)."],
            }],
          },
        },
      },
    });
    const { invalidate } = renderSchedule();
    const { from, to } = await openPublisher();

    fireEvent.change(from, { target: { value: dates[0] } });
    fireEvent.change(to, { target: { value: dates[2] } });
    fireEvent.click(screen.getByRole("button", { name: "Publish 3 dates" }));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining(
        "Schedule range has conflicts. No dates were changed.",
      ));
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining(dates[1].slice(0, 4)));
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: ["doctor-schedules", "branch-1", "doctor-1"],
      });
    });
    expect(screen.getByRole("alert")).toHaveTextContent("No dates were changed");
    expect(toast.success).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Publish 3 dates" })).toBeEnabled();
  });
});
