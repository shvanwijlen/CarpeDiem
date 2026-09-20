// Picks which of the configured Pi addresses to talk to. Kept free of
// React/RN imports so it can be unit-tested with plain Node.
export type Slot = 'primary' | 'alt';

export interface Candidate {
  slot: Slot;
  url: string;
}

export const SLOT_NAME: Record<Slot, string> = { primary: 'boat', alt: 'away' };

export type FailoverResult<T> =
  | { ok: true; slot: Slot; url: string; value: T }
  | { ok: false; error: string };

/**
 * Tries the address that worked last first (so a working connection costs one
 * request, not two), then the others. Returns the first success, or one error
 * string naming every address that failed.
 */
export async function firstReachable<T>(
  candidates: Candidate[],
  preferred: Slot | null,
  load: (url: string, slot: Slot) => Promise<T>,
): Promise<FailoverResult<T>> {
  const ordered = [...candidates].sort((a, b) => Number(b.slot === preferred) - Number(a.slot === preferred));
  const errors: string[] = [];
  for (const c of ordered) {
    try {
      return { ok: true, slot: c.slot, url: c.url, value: await load(c.url, c.slot) };
    } catch (e) {
      errors.push(`${SLOT_NAME[c.slot]}: ${e instanceof Error ? e.message : String(e)}`);
    }
  }
  return { ok: false, error: errors.length ? errors.join(' · ') : 'no address set' };
}
