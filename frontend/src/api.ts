type JsonObject = Record<string, unknown>;
type FormValue = string | number | boolean | null | undefined;

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null;
}

function extractErrorMessage(value: unknown): string | null {
  if (typeof value === "string") {
    return value;
  }
  if (isJsonObject(value)) {
    const detail = value.detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail)) {
      return detail.map((d) => (isJsonObject(d) && typeof d.msg === "string" ? d.msg : JSON.stringify(d))).join(", ");
    }
  }
  return null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: {
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    const text = await response.text();
    let message = text || `Request failed with status ${response.status}`;
    try {
      const parsed = JSON.parse(text) as unknown;
      message = extractErrorMessage(parsed) ?? message;
    } catch (_error) {
      // keep raw text
    }
    throw new ApiError(message, response.status);
  }

  return (await response.json()) as T;
}

export async function getJson<T>(path: string): Promise<T> {
  return request<T>(path, { method: "GET" });
}

export async function deleteJson<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" });
}

export async function postForm<T>(path: string, values: Record<string, FormValue>): Promise<T> {
  const formData = new FormData();
  for (const [key, value] of Object.entries(values)) {
    if (value === null || value === undefined) {
      continue;
    }
    formData.append(key, String(value));
  }
  return request<T>(path, { method: "POST", body: formData });
}
