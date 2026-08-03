import { render } from "@testing-library/react";
import type { ReactElement } from "react";

export function renderApp(ui: ReactElement) {
  return render(ui);
}

export * from "@testing-library/react";
