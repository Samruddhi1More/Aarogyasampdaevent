/** API helpers for registration and pass download. */

export async function submitRegistration(payload) {
  const response = await fetch("/register", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(payload),
  });

  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    const message =
      data?.detail ||
      data?.message ||
      (typeof data?.detail === "string" ? data.detail : null) ||
      "Unable to complete registration. Please try again.";

    const error = new Error(
      typeof message === "string" ? message : "Unable to complete registration. Please try again."
    );
    error.status = response.status;
    error.payload = data;
    throw error;
  }

  return data;
}

export async function fetchPassStatus(registrationId) {
  const response = await fetch(
    `/register/${encodeURIComponent(registrationId)}/pass-status`,
    {
      method: "GET",
      headers: { Accept: "application/json" },
    }
  );

  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    const message =
      (typeof data?.detail === "string" && data.detail) ||
      data?.message ||
      "Unable to check pass status.";
    const error = new Error(message);
    error.status = response.status;
    error.payload = data;
    throw error;
  }

  return data;
}

export function passDownloadUrl(registrationId) {
  return `/register/${encodeURIComponent(registrationId)}/pass`;
}
