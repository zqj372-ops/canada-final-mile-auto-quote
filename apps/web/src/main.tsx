import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import RootApp from "./app/RootApp";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <BrowserRouter basename={import.meta.env.VITE_APP_BASE_PATH || "/"}>
      <RootApp />
    </BrowserRouter>
  </React.StrictMode>,
);
