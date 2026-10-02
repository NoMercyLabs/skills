const TOKEN_KEY = "taskboard.token";

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export function getToken() {
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  if (token) {
    window.localStorage.setItem(TOKEN_KEY, token);
  } else {
    window.localStorage.removeItem(TOKEN_KEY);
  }
}

function buildQuery(params) {
  const query = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  });
  const text = query.toString();
  return text ? `?${text}` : "";
}

export async function request(method, path, { params, body } = {}) {
  const headers = { Accept: "application/json" };
  const token = getToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(`/api${path}${buildQuery(params)}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof payload.error === "string"
      ? payload.error
      : (payload.error && payload.error.message) || response.statusText;
    throw new ApiError(response.status, message);
  }
  return payload;
}

export const api = {
  login: (email, password) => request("POST", "/login", { body: { email, password } }),
  projects: () => request("GET", "/projects"),
  tasks: (projectId, params) => request("GET", `/projects/${projectId}/tasks/page`, { params }),
  searchTasks: (projectId, q) => request("GET", `/projects/${projectId}/tasks/search`, { params: { q } }),
  createTask: (projectId, task) => request("POST", `/projects/${projectId}/tasks`, { body: task }),
  setStatus: (taskId, status) => request("PUT", `/tasks/${taskId}/status`, { body: { status } }),
  comments: (taskId, page) => request("GET", `/tasks/${taskId}/comments`, { params: { page } }),
  addComment: (taskId, body) => request("POST", `/tasks/${taskId}/comments`, { body: { body } }),
};
