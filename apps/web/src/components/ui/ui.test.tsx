import { describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test/render";
import StatusBadge from "./StatusBadge";
import MoneyAmount from "./MoneyAmount";
import DataTable from "./DataTable";
import RecordCard from "./RecordCard";
import ResponsiveActionBar from "./ResponsiveActionBar";

describe("shared quote UI", () => {
  it("renders a readable Chinese status", () => {
    expect(renderApp(<StatusBadge status="ready_to_send" label="待销售发送" />).getByText("待销售发送")).toBeInTheDocument();
  });

  it("formats server-provided string money without recalculating it", () => {
    expect(renderApp(<MoneyAmount amount="1300.00" currency="USD" />).getByText("US$1,300.00")).toBeInTheDocument();
  });

  it("renders table headers and the same row fields in a narrow record card", () => {
    const row = { id: "Q-1", status: "待销售发送", amount: "$1,300.00" };
    const table = renderApp(<DataTable columns={[{ key: "id", label: "报价编号" }, { key: "status", label: "状态" }]} rows={[row]} />);
    expect(table.getByRole("columnheader", { name: "报价编号" })).toBeInTheDocument();
    expect(table.getAllByText("Q-1")).toHaveLength(2);
    table.unmount();
    const card = renderApp(<RecordCard fields={[{ label: "报价编号", value: row.id }, { label: "状态", value: row.status }]} />);
    expect(card.getByText("待销售发送")).toBeInTheDocument();
  });

  it("renders only supplied actions", () => {
    const onClick = vi.fn();
    const view = renderApp(<ResponsiveActionBar actions={[{ key: "send", label: "标记已发送", onClick }]} />);
    expect(view.getByRole("button", { name: "标记已发送" })).toBeInTheDocument();
    expect(view.queryByRole("button", { name: "取消" })).not.toBeInTheDocument();
  });
});
