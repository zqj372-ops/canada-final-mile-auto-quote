import { useState } from "react";

export default function QuoteCopyButton({
  text,
  disabled,
}: {
  text: string;
  disabled: boolean;
}) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
      window.setTimeout(() => setState("idle"), 2200);
    } catch {
      setState("failed");
      window.setTimeout(() => setState("idle"), 2200);
    }
  }

  return (
    <button className="btn-primary" type="button" onClick={handleCopy} disabled={disabled}>
      {state === "copied" ? "已复制" : state === "failed" ? "复制失败" : "复制客户回复"}
    </button>
  );
}
