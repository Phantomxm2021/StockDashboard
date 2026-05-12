export type User = {
  username: string;
  is_root: boolean;
};

export type PoolSummary = {
  key: string;
  title: string;
  count: number;
};

export type ReportDefinition = {
  id: string;
  title: string;
};

export type MarketDefinition = {
  id: string;
  name: string;
  short_name: string;
  default_report_type: string;
  reports: ReportDefinition[];
};

export type Pagination = {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
};

export type ReportPayload = {
  report_type: string;
  active_pool: string;
  pools: PoolSummary[];
  columns: string[];
  rows: Record<string, unknown>[];
  pagination: Pagination;
};

export type StatusPayload = {
  status?: string;
  message?: string;
  [key: string]: unknown;
};

export type JobPayload = {
  job_id: string;
  market: string;
  report_type: string;
  mode: string;
  status: "queued" | "running" | "succeeded" | "failed";
  logs: string;
  returncode: number | null;
  created_at: string;
  updated_at: string;
};

const TOKEN_KEY = "stock_dashboard_token";
const USER_KEY = "stock_dashboard_user";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export function getStoredToken(): string | null {
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): User | null {
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as User;
    if (typeof parsed.username === "string" && typeof parsed.is_root === "boolean") {
      return parsed;
    }
  } catch {
    return null;
  }
  return null;
}

export function storeToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function storeUser(user: User): void {
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

export async function login(username: string, password: string): Promise<{ token: string; user: User }> {
  const response = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password })
  });
  const data = (await readJson(response)) as { access_token: string; user: User };
  return { token: data.access_token, user: data.user };
}

export async function fetchMe(token: string): Promise<User> {
  const response = await authFetch("/api/me", token);
  return (await readJson(response)) as User;
}

export async function fetchMarkets(token: string): Promise<MarketDefinition[]> {
  const response = await authFetch("/api/markets", token);
  return (await readJson(response)) as MarketDefinition[];
}

export async function fetchReport(
  token: string,
  market: string,
  reportType: string,
  pool: string,
  page: number,
  pageSize: number
): Promise<ReportPayload> {
  const params = new URLSearchParams({
    pool,
    page: String(page),
    page_size: String(pageSize)
  });
  const response = await authFetch(`/api/reports/${market}/${reportType}?${params.toString()}`, token);
  return (await readJson(response)) as ReportPayload;
}

export async function fetchStatus(token: string, market: string): Promise<StatusPayload> {
  const response = await authFetch(`/api/status/${market}`, token);
  return (await readJson(response)) as StatusPayload;
}

export async function fetchUsers(token: string): Promise<User[]> {
  const response = await authFetch("/api/users", token);
  return (await readJson(response)) as User[];
}

export async function createUser(token: string, username: string, password: string): Promise<User> {
  const response = await authFetch("/api/users", token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password })
  });
  return (await readJson(response)) as User;
}

export async function runJob(token: string, market: string, reportType: string): Promise<JobPayload> {
  const response = await authFetch("/api/jobs/run", token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ market, report_type: reportType })
  });
  return (await readJson(response)) as JobPayload;
}

export async function fetchJob(token: string, jobId: string): Promise<JobPayload> {
  const response = await authFetch(`/api/jobs/${jobId}`, token);
  return (await readJson(response)) as JobPayload;
}

async function authFetch(url: string, token: string, init: RequestInit = {}): Promise<Response> {
  return fetch(url, {
    ...init,
    headers: {
      ...(init.headers ?? {}),
      Authorization: `Bearer ${token}`
    }
  });
}

async function readJson(response: Response): Promise<Record<string, unknown> | unknown[]> {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data === "object" && data !== null && "detail" in data ? String(data.detail) : "请求失败";
    throw new ApiError(detail, response.status);
  }
  return data as Record<string, unknown> | unknown[];
}
