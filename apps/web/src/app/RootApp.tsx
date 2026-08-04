import { Route, Routes } from "react-router-dom";
import AdminApp from "../apps/AdminApp";
import SalesApp from "../apps/SalesApp";
import NotFoundPage from "./NotFoundPage";

export default function RootApp() {
  return <Routes>
    <Route path="/quote/*" element={<SalesApp />} />
    <Route path="/admin/*" element={<AdminApp />} />
    <Route path="*" element={<NotFoundPage />} />
  </Routes>;
}
