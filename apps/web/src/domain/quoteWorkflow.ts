export type QuoteWorkflowStatus = "draft" | "pending_review" | "in_review" | "needs_sales_info" | "ready_to_send" | "sent" | "accepted" | "change_requested" | "rejected" | "expired" | "cancelled" | "legacy_unclassified";

export interface QuoteActionDescriptor { key: string; label: string; }
