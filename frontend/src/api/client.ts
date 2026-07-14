export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

function errorDetail(body: unknown, fallback: string): string {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
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
  const response = await fetch(`/api${normalizedPath}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init.headers },
  });

  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.includes("json")) {
      const body = await response.json().catch(() => null);
      throw new ApiError(response.status, errorDetail(body, response.statusText));
    }
    const text = await response.text().catch(() => "");
    throw new ApiError(response.status, text || response.statusText || "Request failed");
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
