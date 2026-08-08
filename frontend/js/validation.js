/** Client-side validation for the registration form. */

const INDIAN_MOBILE = /^[6-9]\d{9}$/;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

function normalizePhone(value) {
  let digits = value.replace(/[\s\-()]/g, "");
  if (digits.startsWith("+91")) digits = digits.slice(3);
  else if (digits.startsWith("91") && digits.length === 12) digits = digits.slice(2);
  else if (digits.startsWith("0") && digits.length === 11) digits = digits.slice(1);
  return digits;
}

export function validateRegistration(data) {
  const errors = {};

  const name = (data.name || "").trim().replace(/\s+/g, " ");
  if (!name) {
    errors.name = "Name cannot be empty";
  } else if (name.length < 2) {
    errors.name = "Please enter your full name";
  }

  const phone = normalizePhone(data.phone || "");
  if (!phone) {
    errors.phone = "Mobile number is required";
  } else if (!INDIAN_MOBILE.test(phone)) {
    errors.phone = "Enter a valid 10-digit Indian mobile number";
  }

  const email = (data.email || "").trim();
  if (email && !EMAIL.test(email)) {
    errors.email = "Please enter a valid email address";
  }

  const city = (data.city || "").trim().replace(/\s+/g, " ");
  if (!city) {
    errors.city = "City is required";
  } else if (city.length < 2) {
    errors.city = "Please enter a valid city name";
  }

  const organization = (data.organization || "").trim().replace(/\s+/g, " ");

  return {
    ok: Object.keys(errors).length === 0,
    errors,
    payload: {
      name,
      phone,
      email: email || null,
      city,
      organization: organization || null,
    },
  };
}
