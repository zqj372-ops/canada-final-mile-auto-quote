import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import AdminApp from "./AdminApp";

describe("AdminApp", () => {
  it("shows only admin navigation", () => {
    const { getByText, queryByText } = renderApp(
      <MemoryRouter initialEntries={["/admin"]}>
        <AdminApp />
      </MemoryRouter>,
    );

    expect(getByText("运营工作台")).toBeInTheDocument();
    expect(getByText("报价复核")).toBeInTheDocument();
    expect(getByText("报价记录")).toBeInTheDocument();
    expect(getByText("规则与价格")).toBeInTheDocument();
    expect(getByText("管理数据")).toBeInTheDocument();
    expect(getByText("用户与权限")).toBeInTheDocument();
    expect(queryByText("新建报价")).not.toBeInTheDocument();
    expect(queryByText("待办跟进")).not.toBeInTheDocument();
  });
});
