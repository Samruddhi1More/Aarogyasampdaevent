/** API helpers for registration. */

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
