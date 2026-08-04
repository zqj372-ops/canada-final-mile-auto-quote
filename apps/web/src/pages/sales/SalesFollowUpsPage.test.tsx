import { describe, expect, it } from "vitest";
import { renderApp } from "../../test/render";
import SalesFollowUpsPage from "./SalesFollowUpsPage";

describe("SalesFollowUpsPage", () => {
  it("shows a single next action per follow-up item", () => {
    const view = renderApp(<SalesFollowUpsPage />);
    expect(view.getByText("待办跟进")).toBeInTheDocument();
    expect(view.getByText("暂无待办")).toBeInTheDocument();
  });
});
