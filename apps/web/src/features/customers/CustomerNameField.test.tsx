import { describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test/render";
import CustomerNameField from "./CustomerNameField";

describe("CustomerNameField", () => {
  it("renders only a labeled customer name field", () => {
    const view = renderApp(<CustomerNameField value="" onChange={vi.fn()} onCreate={vi.fn()} />);
    expect(view.getByLabelText("客户名称")).toBeInTheDocument();
    expect(view.queryByText(/邮箱|电话|联系人|地址|备注/)).not.toBeInTheDocument();
  });
});
