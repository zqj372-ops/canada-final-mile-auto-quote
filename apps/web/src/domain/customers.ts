export interface CustomerSummary { id: number; name: string; possible_duplicate: boolean; created_at: string | null; updated_at: string | null; }
export interface CustomerListResponse { records: CustomerSummary[]; total: number; limit: number; offset: number; }
