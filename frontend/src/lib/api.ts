/**
 * Typed client for the Turex API.
 *
 * Two things this centralises:
 *
 * 1. **Error shape.** The API always answers failures with `{ error: { code, message } }`.
 *    Everything here throws `ApiError`, so UI code branches on a stable `code` and displays a
 *    `message` that was written for a person.
 * 2. **Silent re-authentication.** Access tokens last minutes. On a 401 the client rotates the
 *    refresh token once and replays the request, so a long reading session is never
 *    interrupted by an expiry the user did not cause.
 */

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export type ApiErrorCode =
  | "validation_failed"
  | "unauthenticated"
  | "invalid_credentials"
  | "forbidden"
  | "not_found"
  | "conflict"
  | "payload_too_large"
  | "unsupported_media_type"
  | "rate_limited"
  | "provider_unavailable"
  | "provider_declined"
  | "not_configured"
  | "processing_failed"
  | "internal_error"
  | "network_error";

export interface FieldError {
  field: string;
  message: string;
}

export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number;
  readonly fields: FieldError[];

  constructor(code: ApiErrorCode, message: string, status: number, fields: FieldError[] = []) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.fields = fields;
  }

  /** Errors the caller can resolve by signing in again. */
  get isAuthError(): boolean {
    return this.code === "unauthenticated" || this.code === "invalid_credentials";
  }

  fieldError(name: string): string | undefined {
    return this.fields.find((entry) => entry.field === name)?.message;
  }
}

const GENERIC_MESSAGE = "Turex couldn't complete that request. Try again.";

interface ErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
    context?: { fields?: FieldError[] };
  };
}

async function toApiError(response: Response): Promise<ApiError> {
  let body: ErrorEnvelope | null = null;
  try {
    body = (await response.json()) as ErrorEnvelope;
  } catch {
    // A non-JSON error body means a proxy or crash, not our API. Fall through to generic.
  }
  return new ApiError(
    (body?.error?.code as ApiErrorCode) ?? "internal_error",
    body?.error?.message ?? GENERIC_MESSAGE,
    response.status,
    body?.error?.context?.fields ?? [],
  );
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Set false on the refresh call itself, so a failed refresh cannot recurse. */
  retryOnUnauthorized?: boolean;
}

let refreshInFlight: Promise<boolean> | null = null;

/** Rotate the session. Concurrent callers share one request rather than racing. */
async function refreshSession(): Promise<boolean> {
  refreshInFlight ??= (async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });
      return response.ok;
    } catch {
      return false;
    } finally {
      // Cleared on the next tick so callers awaiting this promise all see the same result.
      queueMicrotask(() => {
        refreshInFlight = null;
      });
    }
  })();
  return refreshInFlight;
}

/** Shared authentication and error handling for JSON and streaming responses. */
export async function apiResponse(path: string, options: RequestOptions = {}): Promise<Response> {
  const { body, retryOnUnauthorized = true, headers, ...init } = options;

  const isFormData = body instanceof FormData;
  const requestHeaders = new Headers(headers);
  if (!isFormData && body !== undefined && !requestHeaders.has("content-type")) {
    requestHeaders.set("content-type", "application/json");
  }
  const requestInit: RequestInit = {
    ...init,
    credentials: "include",
    headers: requestHeaders,
    body: isFormData ? body : body === undefined ? undefined : JSON.stringify(body),
  };

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, requestInit);
  } catch (caught) {
    if (init.signal?.aborted) throw caught;
    throw new ApiError(
      "network_error",
      "Turex can't reach the server. Check your connection.",
      0,
    );
  }

  if (response.status === 401 && retryOnUnauthorized) {
    if (await refreshSession()) {
      return apiResponse(path, { ...options, retryOnUnauthorized: false });
    }
  }

  if (!response.ok) throw await toApiError(response);
  return response;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await apiResponse(path, options);
  if (response.status === 204) return undefined as T;

  try {
    return (await response.json()) as T;
  } catch (caught) {
    if (options.signal?.aborted) throw caught;
    throw new ApiError("internal_error", GENERIC_MESSAGE, response.status);
  }
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "POST", body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "PATCH", body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "PUT", body }),
  delete: <T>(path: string, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "DELETE" }),
};
