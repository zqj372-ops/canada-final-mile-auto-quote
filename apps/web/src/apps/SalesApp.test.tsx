import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import SalesApp from "./SalesApp";

describe("SalesApp", () => {
  it("shows only sales navigation", () => {
    const { getByText, queryByText } = renderApp(
      <MemoryRouter initialEntries={["/quote"]}>
        <SalesApp />
      </MemoryRouter>,
    );

    expect(getByText("工作台")).toBeInTheDocument();
    expect(getByText("客户与报价")).toBeInTheDocument();
    expect(getByText("待办跟进")).toBeInTheDocument();
    expect(queryByText("规则与价格")).not.toBeInTheDocument();
    expect(queryByText("运营工作台")).not.toBeInTheDocument();
  });
});
