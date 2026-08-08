import { validateRegistration } from "./validation.js";
import { submitRegistration } from "./api.js";

const form = document.getElementById("registration-form");
const successPanel = document.getElementById("success-panel");
const submitBtn = document.getElementById("submit-btn");
const formError = document.getElementById("form-error");
const registrationIdEl = document.getElementById("registration-id");
const ticketIdEl = document.getElementById("ticket-id");
const successTitle = document.getElementById("success-title");
const successCopy = document.getElementById("success-copy");
const passLink = document.getElementById("pass-link");
const yearEl = document.getElementById("year");

const fieldIds = ["name", "phone", "email", "city", "organization"];
let isSubmitting = false;

yearEl.textContent = String(new Date().getFullYear());

function setFieldError(field, message) {
  const input = document.getElementById(field);
  const errorEl = document.getElementById(`${field}-error`);
  if (!input || !errorEl) return;

  if (message) {
    input.classList.add("is-invalid");
    input.setAttribute("aria-invalid", "true");
    errorEl.hidden = false;
    errorEl.textContent = message;
  } else {
    input.classList.remove("is-invalid");
    input.removeAttribute("aria-invalid");
    errorEl.hidden = true;
    errorEl.textContent = "";
  }
}

function clearErrors() {
  fieldIds.forEach((id) => setFieldError(id, ""));
  formError.hidden = true;
  formError.textContent = "";
}

function setLoading(loading) {
  isSubmitting = loading;
  submitBtn.disabled = loading;
  submitBtn.classList.toggle("is-loading", loading);
  submitBtn.setAttribute("aria-busy", loading ? "true" : "false");
}

function showSuccess(result) {
  form.hidden = true;
  successPanel.hidden = false;

  successTitle.textContent = "Registration successful!";
  successCopy.textContent = result.email_provided
    ? "Your registration has been confirmed. Your event pass is being prepared and will be sent to your email shortly."
    : "Your registration has been confirmed. Your event pass is being prepared.";

  registrationIdEl.textContent = `Registration ID: ${result.registration_id}`;
  if (result.ticket_id) {
    ticketIdEl.hidden = false;
    ticketIdEl.textContent = `Ticket ID: ${result.ticket_id}`;
  } else {
    ticketIdEl.hidden = true;
  }

  // Pass URL is produced asynchronously — hide download until available later
  passLink.hidden = true;

  successPanel.scrollIntoView({ behavior: "smooth", block: "center" });
}

function mapServerErrors(payload) {
  if (payload?.errors && typeof payload.errors === "object") {
    Object.entries(payload.errors).forEach(([field, message]) => {
      if (fieldIds.includes(field)) setFieldError(field, message);
      else {
        formError.hidden = false;
        formError.textContent = message;
      }
    });
    return;
  }

  if (Array.isArray(payload?.detail)) {
    payload.detail.forEach((item) => {
      const field = item?.loc?.[item.loc.length - 1];
      const msg = item?.msg?.replace(/^Value error,\s*/i, "") || "Invalid value";
      if (fieldIds.includes(field)) setFieldError(field, msg);
    });
    return;
  }

  formError.hidden = false;
  formError.textContent =
    typeof payload?.detail === "string"
      ? payload.detail
      : "Unable to complete registration. Please try again.";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (isSubmitting) return;

  clearErrors();

  const raw = {
    name: form.name.value,
    phone: form.phone.value,
    email: form.email.value,
    city: form.city.value,
    organization: form.organization.value,
  };

  const { ok, errors, payload } = validateRegistration(raw);
  if (!ok) {
    Object.entries(errors).forEach(([field, message]) => setFieldError(field, message));
    const firstInvalid = fieldIds.find((id) => errors[id]);
    if (firstInvalid) document.getElementById(firstInvalid)?.focus();
    return;
  }

  setLoading(true);

  try {
    const result = await submitRegistration(payload);
    showSuccess(result);
  } catch (err) {
    mapServerErrors(err.payload);
    if (!err.payload?.errors && formError.hidden) {
      formError.hidden = false;
      formError.textContent = err.message || "Something went wrong. Please try again.";
    }
  } finally {
    setLoading(false);
  }
});

fieldIds.forEach((id) => {
  document.getElementById(id)?.addEventListener("input", () => setFieldError(id, ""));
});
