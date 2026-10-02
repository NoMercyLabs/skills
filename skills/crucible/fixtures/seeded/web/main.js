import { api, setToken, getToken } from "./api.js";
import { clear, el, showMessage } from "./dom.js";
import { createTaskList } from "./tasks.js";
import { createTaskForm } from "./form.js";

const messages = document.getElementById("messages");
const projectSelect = document.getElementById("project");
const searchBox = document.getElementById("search");
const loginForm = document.getElementById("login");
const workspace = document.getElementById("workspace");

const taskList = createTaskList(document.getElementById("tasks"), messages, {
  onOpen: (task) => window.location.hash = `#task-${task.id}`,
});
const taskForm = createTaskForm(document.getElementById("new-task"), messages, {
  onCreated: () => taskList.open(Number(projectSelect.value)),
});

async function loadProjects() {
  const result = await api.projects();
  clear(projectSelect);
  result.items.forEach((project) => {
    projectSelect.append(el("option", { value: project.id }, project.name));
  });
  if (result.items.length > 0) {
    await selectProject(result.items[0].id);
  }
}

async function selectProject(projectId) {
  taskForm.open(projectId);
  await taskList.open(projectId);
}

function showWorkspace(visible) {
  workspace.hidden = !visible;
  loginForm.hidden = visible;
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(loginForm);
  try {
    const result = await api.login(data.get("email"), data.get("password"));
    setToken(result.token);
    showWorkspace(true);
    await loadProjects();
  } catch (error) {
    showMessage(messages, error.status === 401 ? "Wrong email or password" : error.message);
  }
});

projectSelect.addEventListener("change", () => selectProject(Number(projectSelect.value)));
searchBox.addEventListener("input", () => taskList.search(searchBox.value.trim()));

if (getToken()) {
  showWorkspace(true);
  loadProjects().catch(() => {
    setToken(null);
    showWorkspace(false);
  });
} else {
  showWorkspace(false);
}
