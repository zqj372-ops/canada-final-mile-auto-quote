import RecordCard from "./RecordCard";

type CellValue = string | number | null;
type Column<T extends Record<string, CellValue>> = { key: keyof T; label: string };

export default function DataTable<T extends Record<string, CellValue>>({ columns, rows }: { columns: Array<Column<T>>; rows: T[] }) {
  return <>
    <div className="hidden overflow-x-auto md:block"><table className="w-full border-collapse bg-white"><thead><tr>{columns.map((column) => <th className="border-b border-slate-200 px-4 py-3 text-left text-xs font-semibold text-slate-500" key={String(column.key)} scope="col">{column.label}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map((column) => <td className="border-b border-slate-100 px-4 py-3 text-sm text-slate-800" key={String(column.key)}>{row[column.key] ?? "—"}</td>)}</tr>)}</tbody></table></div>
    <div className="grid gap-3 md:hidden">{rows.map((row, index) => <RecordCard key={index} fields={columns.map((column) => ({ label: column.label, value: row[column.key] }))} />)}</div>
  </>;
}
