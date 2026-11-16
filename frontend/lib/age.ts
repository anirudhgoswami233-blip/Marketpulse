// Signup age gate helpers. The server enforces the minimum age (MIN_SIGNUP_AGE); this mirrors it so an
// under-age visitor is stopped before any personal data (email, password) leaves the browser.

export const MIN_SIGNUP_AGE = 13;

const BLOCK_KEY = "mp-signup-blocked";

/** Completed years between an ISO date of birth (YYYY-MM-DD) and `today`. NaN if the date is invalid. */
export function ageOn(birthDate: string, today: Date): number {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(birthDate);
  if (!match) return NaN;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const born = new Date(Date.UTC(year, month - 1, day));
  if (born.getUTCFullYear() !== year || born.getUTCMonth() !== month - 1 || born.getUTCDate() !== day) return NaN;
  const beforeBirthday = today.getMonth() + 1 < month || (today.getMonth() + 1 === month && today.getDate() < day);
  return today.getFullYear() - year - (beforeBirthday ? 1 : 0);
}

/**
 * Remember, in this browser, that signup was refused for age, so going back and entering a different date
 * doesn't get through. Only the fact of the refusal is kept; the date of birth is never stored anywhere.
 */
export function blockSignup(): void {
  try {
    localStorage.setItem(BLOCK_KEY, "1");
  } catch {
    // Storage unavailable (private mode): the block lasts for this page view.
  }
}

export function signupBlocked(): boolean {
  try {
    return localStorage.getItem(BLOCK_KEY) === "1";
  } catch {
    return false;
  }
}
