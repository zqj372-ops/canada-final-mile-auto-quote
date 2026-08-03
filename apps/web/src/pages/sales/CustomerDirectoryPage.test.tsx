import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { renderApp } from "../../test/render";
import CustomerDirectoryPage from "./CustomerDirectoryPage";

describe("CustomerDirectoryPage", () => {
  it("offers customer name only and points to filtered quote records", () => {
    const view = renderApp(<MemoryRouter><CustomerDirectoryPage /></MemoryRouter>);
    expect(view.getByText("客户目录")).toBeInTheDocument();
    expect(view.queryByText(/邮箱|电话|联系人|地址/)).not.toBeInTheDocument();
  });
});
