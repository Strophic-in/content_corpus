import Link from "next/link";

import { asUser } from "@/lib/db";
import { postsBetween } from "@/lib/posts";
import { requireUser } from "@/lib/session";
import { statusBadge } from "@/lib/status";

export const metadata = { title: "Calendar · Content Corpus" };

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// Calendar days are plain Y-M-D strings throughout: a day in the plan is not an
// instant, and Date objects would shift it across the server's timezone.
function ymd(y: number, m: number, d: number) {
  return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

function todayIn(tz: string) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" })
    .format(new Date());
}

export default async function CalendarPage({ searchParams }: { searchParams: Promise<{ m?: string }> }) {
  const user = await requireUser();
  const tz = await asUser(user.id, async (db) => {
    const r = await db.query("select timezone from api.ensure_settings()");
    return (r.rows[0]?.timezone as string) ?? "Asia/Kolkata";
  });
  const today = todayIn(tz);
  const { m } = await searchParams;
  const [y, mo] = (m && /^\d{4}-\d{2}$/.test(m) ? m : today.slice(0, 7)).split("-").map(Number);

  const daysInMonth = new Date(Date.UTC(y, mo, 0)).getUTCDate();
  const firstWeekday = (new Date(Date.UTC(y, mo - 1, 1)).getUTCDay() + 6) % 7; // Monday = 0
  const posts = await postsBetween(user.id, ymd(y, mo, 1), ymd(y, mo, daysInMonth));
  const byDay = new Map(posts.map((p) => [p.slot_date, p]));

  const prev = mo === 1 ? `${y - 1}-12` : `${y}-${String(mo - 1).padStart(2, "0")}`;
  const next = mo === 12 ? `${y + 1}-01` : `${y}-${String(mo + 1).padStart(2, "0")}`;
  const title = new Intl.DateTimeFormat("en", { month: "long", year: "numeric", timeZone: "UTC" })
    .format(new Date(Date.UTC(y, mo - 1, 1)));

  const cells: (string | null)[] = [
    ...Array.from({ length: firstWeekday }, () => null),
    ...Array.from({ length: daysInMonth }, (_, i) => ymd(y, mo, i + 1)),
  ];
  // Pad the last week so the grid stays a clean rectangle.
  while (cells.length % 7) cells.push(null);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <div className="ml-auto flex gap-2 text-sm">
          <Link href={`/calendar?m=${prev}`} className="rounded-md border border-border px-2.5 py-1">←</Link>
          <Link href="/calendar" className="rounded-md border border-border px-2.5 py-1">Today</Link>
          <Link href={`/calendar?m=${next}`} className="rounded-md border border-border px-2.5 py-1">→</Link>
        </div>
      </div>

      <div className="grid grid-cols-7 gap-px overflow-hidden rounded-xl border border-border bg-border text-sm">
        {WEEKDAYS.map((d) => (
          <div key={d} className="bg-surface px-2 py-1.5 text-xs font-medium text-muted">{d}</div>
        ))}
        {cells.map((day, i) => {
          if (!day) return <div key={`pad-${i}`} className="min-h-24 bg-background" />;
          const post = byDay.get(day);
          const isToday = day === today;
          const isPast = day < today;
          return (
            <div key={day} className="flex min-h-24 flex-col gap-1 bg-surface p-1.5 sm:p-2">
              <span className={`text-xs tabular-nums ${isToday ? "font-semibold text-accent" : "text-muted"}`}>
                {Number(day.slice(8))}
              </span>
              {post ? (
                <Link href={`/posts/${post.id}`} className="flex flex-1 flex-col gap-1 rounded-md p-1 hover:bg-background">
                  <span className="line-clamp-2 text-xs font-medium sm:text-sm">{post.topic}</span>
                  <span className={`w-fit rounded px-1.5 py-0.5 text-[10px] font-medium sm:text-xs ${statusBadge(post.status).className}`}>
                    {statusBadge(post.status).label}
                  </span>
                </Link>
              ) : (
                !isPast && (
                  <Link
                    href={`/posts/new?date=${day}`}
                    aria-label={`New post on ${day}`}
                    className="mt-auto flex h-7 items-center justify-center rounded-md border border-dashed border-border text-muted hover:border-accent hover:text-accent"
                  >
                    +
                  </Link>
                )
              )}
            </div>
          );
        })}
      </div>
      <p className="text-xs text-muted">One post per day. Times are in {tz}.</p>
    </div>
  );
}
