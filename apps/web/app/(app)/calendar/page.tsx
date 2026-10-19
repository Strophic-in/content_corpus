import Link from "next/link";

import { workspace } from "@/lib/channels";
import { postsBetween } from "@/lib/posts";
import { requireUser } from "@/lib/session";
import { statusBadge } from "@/lib/status";

import { ChannelPicker } from "../nav";
import { DropDay } from "./drop-day";
import { PostChip } from "./post-chip";

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
  const { channels, active } = await workspace(user.id);
  const tz = active.timezone;
  const today = todayIn(tz);
  const { m } = await searchParams;
  const [y, mo] = (m && /^\d{4}-\d{2}$/.test(m) ? m : today.slice(0, 7)).split("-").map(Number);

  const daysInMonth = new Date(Date.UTC(y, mo, 0)).getUTCDate();
  const firstWeekday = (new Date(Date.UTC(y, mo - 1, 1)).getUTCDay() + 6) % 7; // Monday = 0
  const posts = await postsBetween(user.id, active.id, ymd(y, mo, 1), ymd(y, mo, daysInMonth));
  const byDay = new Map<string, typeof posts>();
  for (const p of posts) byDay.set(p.slot_date, [...(byDay.get(p.slot_date) ?? []), p]);

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
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="text-sm text-muted"><ChannelPicker channels={channels.map(({ id, name }) => ({ id, name }))} activeId={active.id} /></p>
        </div>
        <div className="ml-auto flex gap-2 text-sm">
          <Link href={`/calendar?m=${prev}`} className="rounded-md border border-border px-2.5 py-1">←</Link>
          <Link href="/calendar" className="rounded-md border border-border px-2.5 py-1">Today</Link>
          <Link href={`/calendar?m=${next}`} className="rounded-md border border-border px-2.5 py-1">→</Link>
        </div>
      </div>

      {/* A phone: the month as a list of days, each post at full width. */}
      <ol className="flex flex-col overflow-hidden rounded-xl border border-border bg-surface text-sm sm:hidden">
        {cells.filter((d): d is string => d !== null).map((day) => {
          const dayPosts = byDay.get(day) ?? [];
          const isToday = day === today;
          const isPast = day < today;
          if (isPast && !dayPosts.length) return null;
          const weekday = WEEKDAYS[(new Date(`${day}T00:00:00Z`).getUTCDay() + 6) % 7];
          return (
            <li key={day} className={`flex gap-3 border-b border-border px-3 last:border-b-0 ${dayPosts.length ? "py-2.5" : "py-1.5"}`}>
              <span className={`w-10 shrink-0 pt-1 text-center leading-tight ${isToday ? "text-accent" : "text-muted"}`}>
                <span className="block text-[11px] uppercase">{weekday}</span>
                <span className={`block text-lg tabular-nums ${isToday ? "font-semibold" : ""}`}>{Number(day.slice(8))}</span>
              </span>
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                {dayPosts.map((post) => (
                  <PostChip key={post.id} id={post.id} topic={post.topic} time={post.publish_time} status={post.status}
                            badge={statusBadge(post.status)} day={day} today={today} />
                ))}
                {!isPast && (
                  <Link href={`/posts/new?date=${day}`} aria-label={`New post on ${day}`}
                        className={`flex items-center rounded-md text-muted hover:text-accent ${dayPosts.length ? "px-1 text-xs" : "min-h-9 px-1"}`}>
                    + New post
                  </Link>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      <div className="hidden grid-cols-7 gap-px overflow-hidden rounded-xl border border-border bg-border text-sm sm:grid">
        {WEEKDAYS.map((d) => (
          <div key={d} className="bg-surface px-2 py-1.5 text-xs font-medium text-muted">{d}</div>
        ))}
        {cells.map((day, i) => {
          if (!day) return <div key={`pad-${i}`} className="min-h-24 bg-background" />;
          const dayPosts = byDay.get(day) ?? [];
          const isToday = day === today;
          const isPast = day < today;
          return (
            <DropDay key={day} day={day} past={isPast} className="flex min-h-24 flex-col gap-1 bg-surface p-1.5 sm:p-2">
              <span className={`text-xs tabular-nums ${isToday ? "font-semibold text-accent" : "text-muted"}`}>
                {Number(day.slice(8))}
              </span>
              {dayPosts.map((post) => (
                <PostChip key={post.id} id={post.id} topic={post.topic} time={post.publish_time} status={post.status}
                          badge={statusBadge(post.status)} day={day} today={today} />
              ))}
              {!isPast && (
                <Link
                  href={`/posts/new?date=${day}`}
                  aria-label={`New post on ${day}`}
                  className={`mt-auto flex items-center justify-center rounded-md border border-dashed border-border text-muted hover:border-accent hover:text-accent ${dayPosts.length ? "h-5 text-xs" : "h-7"}`}
                >
                  +
                </Link>
              )}
            </DropDay>
          );
        })}
      </div>
      <p className="text-xs text-muted">{active.name} · times are in {tz}. <span className="hidden sm:inline">Drag a post to
        another day to move it.</span></p>
    </div>
  );
}
