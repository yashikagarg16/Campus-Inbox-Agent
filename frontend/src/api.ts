// Typed client for the FastAPI backend. Shapes mirror backend/app/main.py.

export type Verdict = "eligible" | "not_eligible" | "needs_review";
export type RuleStatus = "pass" | "fail" | "unknown";

export interface RuleResult {
  rule: string;
  status: RuleStatus;
  required: unknown;
  actual: unknown;
  evidence: string | null;
  span: [number, number] | null;
  reason: string;
}

export interface Decision {
  verdict: Verdict;
  rules: RuleResult[];
  reasons: string[];
  notes: string[];
  deadline: string | null;
  deadline_passed: boolean | null;
}

export interface FieldIssue {
  field: string;
  reason: string;
  value: unknown;
  evidence: string | null;
}

export interface Draft {
  id: number;
  opportunity_id: number;
  question: string;
  answer: string;
  status: "draft" | "approved";
  warnings: string[];
  updated_at: string;
}

export interface OpportunitySummary {
  id: number;
  email_id: number;
  subject: string | null;
  company: string | null;
  role: string | null;
  deadline: string | null;
  deadline_passed: boolean | null;
  form_link: string | null;
  verdict: Verdict | null;
  is_opportunity: boolean;
  created_at: string;
}

export interface OpportunityDetail extends OpportunitySummary {
  email_text: string;
  received_at: string | null;
  sender: string | null;
  siblings: number[];
  extraction: Record<string, unknown>;
  issues: FieldIssue[];
  decision: Decision | null;
  drafts: Draft[];
}

export interface IngestResult {
  email_id: number;
  duplicate: boolean;
  opportunities: OpportunityDetail[];
}

export interface Profile {
  name: string | null;
  batch: number | null;
  cgpa: number | null;
  cgpa_scale: number;
  branch: string | null;
  tenth_percent: number | null;
  twelfth_percent: number | null;
  active_backlogs: number | null;
  skills: string[];
  branch_aliases: string[];
  resume_summary: string | null;
}

export interface AuditEvent {
  id: number;
  event: string;
  email_id: number | null;
  opportunity_id: number | null;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface ServerConfig {
  demo_mode?: boolean;
  llm_configured: boolean;
  imap_configured: boolean; // any inbox sync is set up
  mail_source?: "graph" | "imap" | null;
  auth_required: boolean;
}

export interface SyncResult {
  fetched: number;
  new: number;
  duplicates: number;
  failed: number;
  email_ids: number[];
}

const API_URL_KEY = "cia.apiUrl";
const TOKEN_KEY = "cia.token";

function readStorage(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string): void {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    // Storage blocked (private mode); settings then last only for this page load.
  }
}

export function getApiUrl(): string {
  const url = readStorage(API_URL_KEY) || import.meta.env.VITE_API_URL || "http://localhost:8000";
  return url.replace(/\/+$/, "");
}

export function getToken(): string {
  return readStorage(TOKEN_KEY) ?? "";
}

export function saveConnection(apiUrl: string, token: string): void {
  writeStorage(API_URL_KEY, apiUrl.trim());
  writeStorage(TOKEN_KEY, token.trim());
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");

  let res: Response;
  try {
    res = await fetch(getApiUrl() + path, { ...init, headers });
  } catch {
    throw new ApiError(0, `Can't reach the server at ${getApiUrl()}. Is the backend running?`);
  }
  if (!res.ok) {
    let message = res.statusText || `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail))
        message = body.detail.map((d: { msg?: string }) => d.msg ?? JSON.stringify(d)).join("; ");
    } catch {
      // keep the status text
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  config: () => request<ServerConfig>("/config"),
  getProfile: () => request<Profile>("/profile"),
  saveProfile: (p: Profile) =>
    request<{ profile: Profile; reevaluated: number }>("/profile", { method: "PUT", body: json(p) }),
  submitEmail: (body: { text: string; subject?: string; received_at?: string }) =>
    request<IngestResult>("/emails", { method: "POST", body: json(body) }),
  uploadEml: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<IngestResult>("/emails/eml", { method: "POST", body: form });
  },
  deleteEmail: (id: number) => request<void>(`/emails/${id}`, { method: "DELETE" }),
  syncImap: (sinceDays: number) =>
    request<SyncResult>("/sync/inbox", { method: "POST", body: json({ since_days: sinceDays }) }),
  listOpportunities: () => request<OpportunitySummary[]>("/opportunities"),
  getOpportunity: (id: number) => request<OpportunityDetail>(`/opportunities/${id}`),
  getAudit: (id: number) => request<AuditEvent[]>(`/opportunities/${id}/audit`),
  createDrafts: (id: number, questions: string[]) =>
    request<Draft[]>(`/opportunities/${id}/drafts`, { method: "POST", body: json({ questions }) }),
  updateDraft: (id: number, body: { answer?: string; status?: "draft" | "approved" }) =>
    request<Draft>(`/drafts/${id}`, { method: "PUT", body: json(body) }),
  deleteDraft: (id: number) => request<void>(`/drafts/${id}`, { method: "DELETE" }),
};
