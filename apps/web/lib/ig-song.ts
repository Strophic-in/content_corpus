// The Instagram song the worker picked for a reel (worker ig_music.py, posts.ig_music):
// one place that words it, for the Progress step and the reel panels alike.

export type IgMusic = {
  audio_id?: string; title?: string; artist?: string; trending_rank?: number | null;
  found_by?: string | null; picked_by?: "decisions" | "rule" | "only" | string | null;
  confidence?: number | string | null; skipped_silent?: string[] | null;
  picked_at?: string; attached?: boolean; dropped?: string;
};

const PICKERS: Record<string, string> = { decisions: "OpenAI Decisions", rule: "fallback rule", only: "only option" };

/** "trending #3", or "search: hindi trending". */
export function songFound(m: IgMusic): string | null {
  if (m.trending_rank) return `trending #${m.trending_rank}`;
  if (m.found_by) return m.found_by.startsWith("search") ? m.found_by : `search: ${m.found_by}`;
  return null;
}

export function songConfidence(c: IgMusic["confidence"]): string | null {
  if (c === null || c === undefined || c === "") return null;
  const n = Number(c);
  if (Number.isNaN(n)) return `${c} confidence`;
  return `${Math.round(n <= 1 ? n * 100 : n)}% confidence`;
}

/** “Title” — Artist, with how it was found, who picked it and how sure. Null with no song. */
export function songSummary(m: IgMusic): { title: string; how: string; note: string | null } | null {
  if (!m.title) return null;
  const how = [songFound(m), m.picked_by ? (PICKERS[m.picked_by] ?? m.picked_by) : null, songConfidence(m.confidence)]
    .filter(Boolean).join(" · ");
  const n = m.skipped_silent?.length ?? 0;
  return {
    title: m.artist ? `${m.title} — ${m.artist}` : m.title, how,
    note: n ? `skipped ${n} silent song${n === 1 ? "" : "s"}` : null,
  };
}

/** The reel panels' line. The API gives no confirmation that the song is audible, so it
 *  says what was done: the song was sent to Instagram. */
export function songLine(m: IgMusic): string {
  if (m.dropped) return "Instagram refused the song — posted with the background track.";
  const s = songSummary(m);
  return s ? `Song sent to Instagram: ${s.title}${songFound(m) ? ` · ${songFound(m)}` : ""}` : "";
}
