import { api } from "./api.js";
import { clear, el, escapeHtml, formatDate, debounce, showMessage } from "./dom.js";

const STATUS_LABELS = {
  open: "Open",
  in_progress: "In progress",
  blocked: "Blocked",
  done: "Done",
};

export function createTaskList(container, messages, { onOpen }) {
  const state = { projectId: null, items: [], cursor: 0, nextCursor: null };

  const table = el("table", { class: "task-table" });
  const body = el("tbody");
  table.append(
    el("thead", {}, el("tr", {}, [
      el("th", {}, "#"),
      el("th", {}, "Title"),
      el("th", {}, "Status"),
      el("th", {}, "Updated"),
    ])),
    body,
  );
  const more = el("button", { type: "button", class: "load-more", hidden: true }, "Load more");
  container.append(table, more);

  function statusSelect(task) {
    const select = el("select", { "aria-label": `Status of ${task.title}` });
    Object.entries(STATUS_LABELS).forEach(([value, label]) => {
      select.append(el("option", { value, selected: value === task.status }, label));
    });
    select.addEventListener("change", async () => {
      try {
        await api.setStatus(task.id, select.value);
        task.status = select.value;
      } catch (error) {
        select.value = task.status;
        showMessage(messages, error.message);
      }
    });
    return select;
  }

  function renderRow(task) {
    const row = el("tr", { "data-task-id": task.id });
    row.innerHTML = `<td>${task.number}</td><td class="title">${task.title}</td>`;
    const statusCell = el("td", {}, statusSelect(task));
    const updated = el("td", {}, formatDate(task.updated_at));
    row.append(statusCell, updated);
    row.querySelector(".title").addEventListener("click", () => onOpen(task));
    return row;
  }

  function renderLabels(task) {
    return task.labels
      .map((label) => `<span class="label">${escapeHtml(label)}</span>`)
      .join("");
  }

  function paint() {
    clear(body);
    state.items.forEach((task) => {
      const row = renderRow(task);
      const titleCell = row.querySelector(".title");
      titleCell.insertAdjacentHTML("beforeend", renderLabels(task));
      body.append(row);
    });
    more.hidden = state.nextCursor === null;
  }

  async function load(reset) {
    if (reset) {
      state.items = [];
      state.cursor = 0;
    }
    try {
      const page = await api.tasks(state.projectId, { after: state.cursor, per_page: 25 });
      state.items = state.items.concat(page.items);
      state.nextCursor = page.next_cursor;
      state.cursor = page.next_cursor || state.cursor;
      paint();
    } catch (error) {
      showMessage(messages, error.message);
    }
  }

  const runSearch = debounce(async (text) => {
    if (!text) {
      await load(true);
      return;
    }
    try {
      const result = await api.searchTasks(state.projectId, text);
      state.items = result.items;
      state.nextCursor = null;
      paint();
    } catch (error) {
      showMessage(messages, error.message);
    }
  }, 250);

  more.addEventListener("click", () => load(false));

  return {
    open(projectId) {
      state.projectId = projectId;
      return load(true);
    },
    search: runSearch,
    prepend(task) {
      state.items.unshift(task);
      paint();
    },
  };
}
