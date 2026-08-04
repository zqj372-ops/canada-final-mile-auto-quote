import { request } from "./http";
import type { CustomerListResponse, CustomerSummary } from "../domain/customers";

export function listCustomers(params: { query?: string; limit?: number; offset?: number } = {}): Promise<CustomerListResponse> {
  const query = new URLSearchParams();
  if (params.query) query.set("query", params.query);
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  return request<CustomerListResponse>(`/customers${query.toString() ? `?${query}` : ""}`, {}, "quote");
}

export function createCustomer(payload: { name: string }): Promise<CustomerSummary> {
  return request<CustomerSummary>("/customers", { method: "POST", body: JSON.stringify(payload) }, "quote");
}

export function updateCustomer(id: number, payload: { name: string }): Promise<CustomerSummary> {
  return request<CustomerSummary>(`/customers/${id}`, { method: "PATCH", body: JSON.stringify(payload) }, "quote");
}
