import "server-only";

// Postgres errors the UI can explain. Anything else is logged and reported
// generically — never echo raw SQL errors to the page.
export function friendly(err: unknown): string {
  const e = err as { code?: string; message?: string; constraint?: string };
  if (e?.code === "23505") return "That name is already taken — pick another.";
  if (e?.code === "P0002") return "That item no longer exists.";
  if (e?.code === "55000" && e.message) return e.message.charAt(0).toUpperCase() + e.message.slice(1) + ".";
  if (e?.code === "42501") {
    console.error("action refused by database permissions:", e.message);
    return "The database refused that change — it isn't allowed in the current state.";
  }
  if (e?.code === "23514") return "One of the values is out of range.";
  console.error("action failed", err);
  return "Something went wrong. Please try again.";
}
