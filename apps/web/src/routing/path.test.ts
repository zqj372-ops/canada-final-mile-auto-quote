import { describe, expect, it } from "vitest";
import { classifyAppSurface, navigateTo, normalizeBasePath, stripBasePath } from "./path";

describe("application surface routing", () => {
  it.each([
    ["/quote", "sales"],
    ["/quote/customers", "sales"],
    ["/admin", "admin"],
    ["/admin/reviews", "admin"],
  ])("classifies %s as %s", (pathname, expected) => {
    expect(classifyAppSurface(pathname, "")).toBe(expected);
  });

  it("rejects unknown paths instead of crossing application shells", () => {
    expect(classifyAppSurface("/other", "")).toBe("not-found");
    expect(classifyAppSurface("/administer", "")).toBe("not-found");
  });

  it("normalizes and strips the configured base path", () => {
    expect(normalizeBasePath("/quote-app/")).toBe("/quote-app");
    expect(stripBasePath("/quote-app/quote/customers", "/quote-app")).toBe("/quote/customers");
    expect(stripBasePath("/quote/customers", "/quote-app")).toBe("/quote/customers");
  });

  it("builds navigation paths under the configured base path", () => {
    expect(navigateTo("/admin/reviews/12", "/quote-app")).toBe("/quote-app/admin/reviews/12");
  });
});
