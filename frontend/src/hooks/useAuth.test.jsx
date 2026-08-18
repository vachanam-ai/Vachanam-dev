import { describe, expect, it } from "vitest";
import { roleHome, sessionFromToken } from "./useAuth.jsx";

const tokenFor = (claims) => {
  const payload = btoa(JSON.stringify(claims)).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `header.${payload}.signature`;
};

describe("sessionFromToken", () => {
  it("hydrates the signed session without a second login request", () => {
    const session = sessionFromToken(tokenFor({
      sub: "user-1", email: "owner@clinic.in", role: "org_admin",
      org_id: "org-1", branch_ids: ["branch-1"], is_admin: false,
      exp: Math.floor(Date.now() / 1000) + 60
    }));
    expect(session).toEqual({
      user_id: "user-1", email: "owner@clinic.in", role: "org_admin",
      org_id: "org-1", branch_ids: ["branch-1"], is_admin: false
    });
  });

  it("rejects expired or malformed sessions", () => {
    expect(sessionFromToken(tokenFor({ sub: "u", email: "e", role: "doctor", exp: 1 }))).toBeNull();
    expect(sessionFromToken("not-a-jwt")).toBeNull();
  });
});

describe("roleHome", () => {
  it("opens the complete clinic dashboard for receptionists", () => {
    expect(roleHome("receptionist")).toBe("/dashboard");
  });
});
