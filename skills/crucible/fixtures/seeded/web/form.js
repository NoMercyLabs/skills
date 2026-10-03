import { api } from "./api.js";
import { el, showMessage } from "./dom.js";

const LABEL_PATTERN = /^[a-z0-9][a-z0-9_.-]{0,29}$/;

export function parseLabels(text) {
  return text
    .split(",")
    .map((part) => part.trim().toLowerCase())
    .filter((part) => part.length > 0);
}

export function validateTask(values) {
  const errors = {};
  if (values.title.trim().length === 0) {
    errors.title = "Enter a title";
  } else if (values.title.length > 200) {
    errors.title = "Keep the title under 200 characters";
  }
  const bad = values.labels.filter((label) => !LABEL_PATTERN.test(label));
  if (bad.length > 0) {
    errors.labels = `Invalid labels: ${bad.join(", ")}`;
  }
  if (values.labels.length > 10) {
    errors.labels = "Use at most 10 labels";
  }
  return errors;
}

export function createTaskForm(container, messages, { onCreated }) {
  const form = el("form", { class: "task-form", noValidate: true });
  const title = el("input", { name: "title", type: "text", maxLength: 200 });
  const body = el("textarea", { name: "body", rows: 4 });
  const labels = el("input", { name: "labels", type: "text", placeholder: "frontend, urgent" });
  const submit = el("button", { type: "submit" }, "Create task");
  const fieldErrors = {
    title: el("span", { class: "field-error" }),
    labels: el("span", { class: "field-error" }),
  };

  form.append(
    el("label", {}, ["Title", title, fieldErrors.title]),
    el("label", {}, ["Details", body]),
    el("label", {}, ["Labels", labels, fieldErrors.labels]),
    submit,
  );
  container.append(form);

  let projectId = null;

  function showErrors(errors) {
    Object.entries(fieldErrors).forEach(([name, node]) => {
      node.textContent = errors[name] || "";
    });
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = {
      title: title.value,
      body: body.value,
      labels: parseLabels(labels.value),
    };
    const errors = validateTask(values);
    showErrors(errors);
    if (Object.keys(errors).length > 0) {
      return;
    }
    submit.disabled = true;
    try {
      const created = await api.createTask(projectId, {
        title: values.title.trim(),
        body: values.body,
        labels: values.labels,
      });
      form.reset();
      onCreated(created.id);
    } catch (error) {
      showMessage(messages, error.message);
    } finally {
      submit.disabled = false;
    }
  });

  return {
    open(id) {
      projectId = id;
      form.reset();
      showErrors({});
    },
  };
}
