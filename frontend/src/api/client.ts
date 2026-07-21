export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    public readonly responseBody?: unknown,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

const friendlyMessages: Record<string, string> = {
  "Invalid credentials": "用户名或密码错误，请重新输入",
  "Inactive user": "这个账号已停用，请联系管理员",
  "Income configuration version does not match": "收入项目刚刚发生变化，页面已为你重新加载，请确认金额后再次保存",
};

export function friendlyApiError(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError)) return fallback;
  const mapped = friendlyMessages[error.detail];
  if (mapped) return mapped;
  if (/^[\x00-\x7f\s]+$/.test(error.detail)) {
    if (error.status === 401) return "登录状态已失效，请重新登录";
    if (error.status === 403) return "你没有权限执行这个操作";
    if (error.status === 409) return "数据已经发生变化，请刷新后重试";
    if (error.status >= 500) return "服务器暂时不可用，请稍后重试";
    return fallback;
  }
  return error.detail || fallback;
}

function errorDetail(body: unknown, fallback: string): string {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (typeof detail === "object" && detail !== null && "message" in detail && typeof detail.message === "string") {
      return detail.message;
    }
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => (typeof item === "object" && item !== null && "msg" in item ? String(item.msg) : ""))
        .filter(Boolean);
      if (messages.length) return messages.join("; ");
    }
  }
  return fallback || "Request failed";
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const headers = new Headers(init.headers);
  if (init.body != null && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(`/api${normalizedPath}`, {
    ...init,
    credentials: "include",
    headers,
  });

  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.includes("json")) {
      const body = await response.json().catch(() => null);
      throw new ApiError(response.status, errorDetail(body, response.statusText), body);
    }
    const text = await response.text().catch(() => "");
    throw new ApiError(response.status, text || response.statusText || "Request failed");
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
