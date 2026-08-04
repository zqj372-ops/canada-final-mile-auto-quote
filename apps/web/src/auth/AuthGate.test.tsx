import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import AuthGate from "./AuthGate";

describe("AuthGate", () => {
  it("shows a forbidden state when the actor role is not allowed", () => {
    const { getByRole } = renderApp(
      <AuthGate actor={{ user_id: 1, api_key_id: null, name: "Sales", role: "sales" }} allowedRoles={["admin"]}>
        <span>后台内容</span>
      </AuthGate>,
    );
    expect(getByRole("alert")).toHaveTextContent("403");
  });
});
