import { validateRegistration } from "./validation.js";
import {
  fetchPassStatus,
  passDownloadUrl,
  submitRegistration,
} from "./api.js";

const form = document.getElementById("registration-form");
const successPanel = document.getElementById("success-panel");
const submitBtn = document.getElementById("submit-btn");
const formError = document.getElementById("form-error");
const ticketIdEl = document.getElementById("ticket-id");
const successTitle = document.getElementById("success-title");
const successCopy = document.getElementById("success-copy");
const passReadyBlock = document.getElementById("pass-ready-block");
const passReadyHeading = document.getElementById("pass-ready-heading");
const passDownloadBtn = document.getElementById("pass-download-btn");
const passStatusNote = document.getElementById("pass-status-note");
const yearEl = document.getElementById("year");

const fieldIds = ["name", "phone", "email", "city", "invited_by"];
const PASS_POLL_INTERVAL_MS = 2000;
const PASS_POLL_MAX_ATTEMPTS = 45; // ~90s
const DOWNLOAD_LABEL = "Download Your Event Pass";

let isSubmitting = false;
let passPollTimer = null;

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

function stopPassPolling() {
  if (passPollTimer) {
    clearTimeout(passPollTimer);
    passPollTimer = null;
  }
}

function setPassButtonLoading(message) {
  passReadyBlock.hidden = false;
  passReadyBlock.classList.remove("is-ready");
  passReadyHeading.textContent = "Preparing Your Event Pass";
  passDownloadBtn.hidden = false;
  passDownloadBtn.classList.add("is-loading", "is-disabled");
  passDownloadBtn.setAttribute("aria-disabled", "true");
  passDownloadBtn.removeAttribute("href");
  passDownloadBtn.textContent = "Preparing Pass…";
  passStatusNote.textContent =
    message ||
    "Your personalized pass is being prepared. This usually takes a few seconds.";
  successCopy.textContent = successCopy.dataset.preparingCopy || successCopy.textContent;
}

function setPassButtonReady(registrationId, ticketId) {
  const filenameHint = ticketId ? `${ticketId}-event-pass.png` : "event-pass.png";
  passReadyBlock.hidden = false;
  passReadyBlock.classList.add("is-ready");
  passReadyHeading.textContent = "Your Event Pass Is Ready";
  passDownloadBtn.hidden = false;
  passDownloadBtn.classList.remove("is-loading", "is-disabled");
  passDownloadBtn.setAttribute("aria-disabled", "false");
  passDownloadBtn.href = passDownloadUrl(registrationId);
  passDownloadBtn.setAttribute("download", filenameHint);
  passDownloadBtn.textContent = DOWNLOAD_LABEL;
  passStatusNote.textContent =
    "Download your personalized pass below and keep it available on your phone for entry at the event.";
  successCopy.textContent =
    "Your registration has been confirmed and your event pass is ready.";
}

function setPassButtonFailed(message) {
  passReadyBlock.hidden = false;
  passReadyBlock.classList.remove("is-ready");
  passReadyHeading.textContent = "Pass Unavailable";
  passDownloadBtn.hidden = false;
  passDownloadBtn.classList.remove("is-loading");
  passDownloadBtn.classList.add("is-disabled");
  passDownloadBtn.setAttribute("aria-disabled", "true");
  passDownloadBtn.removeAttribute("href");
  passDownloadBtn.textContent = "Pass Unavailable";
  passStatusNote.textContent =
    message ||
    "We could not prepare your pass for download. Please contact support with your Ticket ID.";
}

async function pollPassUntilReady(registrationId, ticketId, attempt = 0) {
  stopPassPolling();

  try {
    const status = await fetchPassStatus(registrationId);
    if (status.download_ready) {
      setPassButtonReady(registrationId, status.ticket_id || ticketId);
      return;
    }
    if ((status.pass_generation_status || "").toUpperCase() === "FAILED") {
      setPassButtonFailed(status.message);
      return;
    }
    setPassButtonLoading(status.message);
  } catch {
    setPassButtonLoading("Still preparing your pass. Please keep this page open.");
  }

  if (attempt + 1 >= PASS_POLL_MAX_ATTEMPTS) {
    setPassButtonFailed(
      "Pass preparation is taking longer than expected. Please refresh this page in a minute, or check your email if you provided one."
    );
    return;
  }

  passPollTimer = setTimeout(() => {
    pollPassUntilReady(registrationId, ticketId, attempt + 1);
  }, PASS_POLL_INTERVAL_MS);
}

function showSuccess(result) {
  form.hidden = true;
  successPanel.hidden = false;
  stopPassPolling();

  successTitle.textContent = "Registration successful!";

  const preparingCopy = result.email_provided
    ? "Your registration has been confirmed. Your event pass is being prepared and will be sent to your email shortly."
    : "Your registration has been confirmed. Your event pass is being prepared.";
  successCopy.dataset.preparingCopy = preparingCopy;
  successCopy.textContent = preparingCopy;

  if (result.ticket_id) {
    ticketIdEl.hidden = false;
    ticketIdEl.textContent = `Ticket ID: ${result.ticket_id}`;
  } else {
    ticketIdEl.hidden = true;
  }

  setPassButtonLoading();
  pollPassUntilReady(result.registration_id, result.ticket_id);

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
    invited_by: form.invited_by.value,
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

passDownloadBtn.addEventListener("click", (event) => {
  if (
    passDownloadBtn.classList.contains("is-disabled") ||
    passDownloadBtn.getAttribute("aria-disabled") === "true" ||
    !passDownloadBtn.getAttribute("href")
  ) {
    event.preventDefault();
  }
});

fieldIds.forEach((id) => {
  document.getElementById(id)?.addEventListener("input", () => setFieldError(id, ""));
});
