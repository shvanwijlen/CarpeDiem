// When the app locks, and what counts as "can't authenticate" - kept free of
// React/RN imports so the rules can be tested with plain Node.

/** Leaving the app for less than this doesn't relock it (so answering a text
 *  or glancing at another app doesn't make you re-authenticate every time). */
export const LOCK_GRACE_MS = 30_000;

export function shouldRelock(backgroundedAt: number | null, now: number, graceMs = LOCK_GRACE_MS): boolean {
  return backgroundedAt !== null && now - backgroundedAt >= graceMs;
}

// expo-local-authentication errors meaning the *device* can't authenticate at
// all (no passcode set, no Face ID hardware/enrolment). Locking someone out of
// their own boat data because their phone has no passcode helps nobody, so the
// app opens instead. Everything else (cancelled, failed, lockout) stays locked.
const CANNOT_AUTHENTICATE = new Set(['not_available', 'not_enrolled', 'passcode_not_set']);

export function opensAnyway(error: string | undefined): boolean {
  return error !== undefined && CANNOT_AUTHENTICATE.has(error);
}
