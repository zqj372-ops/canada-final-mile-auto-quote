export default function MoneyAmount({ amount, currency }: { amount: string | null; currency: string }) {
  if (amount === null || amount === "") return <span>—</span>;
  const numeric = Number(amount);
  if (!Number.isFinite(numeric)) return <span>{amount} {currency}</span>;
  return <span className="tabular-nums">{new Intl.NumberFormat("en-CA", { style: "currency", currency }).format(numeric)}</span>;
}
