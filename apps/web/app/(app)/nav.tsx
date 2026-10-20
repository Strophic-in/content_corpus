"use client";

import { motion } from "motion/react";
import Link, { useLinkStatus } from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { switchChannel } from "./channel-actions";

type Tab = { href: string; label: string; icon: React.ReactNode };

const I = (d: string) => (
  <svg viewBox="0 0 24 24" aria-hidden className="size-6" fill="none" stroke="currentColor" strokeWidth={1.8}
       strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>
);

export const TABS: Tab[] = [
  { href: "/discover", label: "Discover",
    icon: I("M12 3c.5 3.5 4 5.5 4 9.5a4 4 0 0 1-8 0c0-1.6.7-2.8 1.5-3.7.2 1.4 1 2.4 2 2.7C11 9 11.4 5.6 12 3Z") },
  // What's trending on YouTube right now, by country and topic (Explore YouTube).
  { href: "/explore", label: "Explore", icon: I("M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM15.5 8.5l-2 5-5 2 2-5 5-2Z") },
  { href: "/calendar", label: "Calendar", icon: I("M4 6h16v14H4zM4 10h16M9 3v4M15 3v4") },
  { href: "/library", label: "Library", icon: I("M5 4h5v16H5zM10 4h4v16h-4zM14.5 4.5l4.5 1.2-3.8 14.3-4.5-1.2") },
  { href: "/channels", label: "Channels", icon: I("M5 12a7 7 0 0 1 14 0M8.5 12a3.5 3.5 0 0 1 7 0M12 12v8") },
  { href: "/settings", label: "Settings",
    icon: I("M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6ZM19 12l2-1-1-3-2 .3-1.3-1.3.3-2-3-1-1 2h-2l-1-2-3 1 .3 2L6 7.3 4 7l-1 3 2 1v2l-2 1 1 3 2-.3 1.3 1.3-.3 2 3 1 1-2h2l1 2 3-1-.3-2 1.3-1.3 2 .3 1-3-2-1Z") },
];

function isActive(path: string, href: string) {
  return path === href || path.startsWith(href + "/") || (href === "/library" && path.startsWith("/posts"));
}

/** The tab just tapped, lit at once (before its page arrives); cleared once the
 *  address changes, when the real active tab takes over. */
function useTapped() {
  const path = usePathname();
  // Remembered with the page it was tapped on: once the address moves on, it lapses.
  const [tapped, setTapped] = useState<{ href: string; from: string } | null>(null);
  const live = tapped?.from === path ? tapped.href : null;
  const on = (href: string) => (live ? live === href : isActive(path, href));
  return [on, (href: string) => setTapped({ href, from: path })] as const;
}

/** A tab's label or icon, pulsing while its page is on the way. */
function Pending({ children }: { children: React.ReactNode }) {
  const { pending } = useLinkStatus();
  return <span className={`transition-opacity ${pending ? "animate-pulse" : ""}`}>{children}</span>;
}

/** The desk's sections; a red rule slides under the one you're on. */
export function DesktopNav() {
  const [on, tap] = useTapped();
  return (
    <nav className="hidden h-full items-stretch gap-1 text-sm md:flex">
      {TABS.map((t) => {
        const active = on(t.href);
        return (
          <Link key={t.href} href={t.href} onClick={() => tap(t.href)}
                className={`relative flex items-center px-3 transition-colors ${active
                  ? "font-medium text-foreground" : "text-muted hover:text-foreground"}`}>
            <Pending>{t.label}</Pending>
            {active && (
              <motion.span layoutId="desk-rule" aria-hidden
                           className="absolute inset-x-2 -bottom-px h-[3px] rounded-full bg-accent"
                           transition={{ type: "spring", stiffness: 500, damping: 38 }} />
            )}
          </Link>
        );
      })}
    </nav>
  );
}

/** The phone's tab bar: fixed at the bottom, above the home indicator. The active
 *  tab's icon sits on a soft pill; a tap lights the tab at once and gives a tick. */
export function BottomTabs() {
  const [on, tap] = useTapped();
  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-surface/92 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl md:hidden">
      <div className="mx-auto grid max-w-lg grid-cols-6 px-1">
        {TABS.map((t) => {
          const active = on(t.href);
          return (
            <Link key={t.href} href={t.href} aria-current={active ? "page" : undefined}
                  onClick={() => { tap(t.href); navigator.vibrate?.(8); }}
                  className={`group relative flex flex-col items-center gap-0.5 pt-2 pb-1.5 text-[10.5px] font-medium transition-colors active:scale-95 ${active ? "text-accent" : "text-muted"}`}>
              {active && (
                <motion.span layoutId="tab-light" aria-hidden
                             className="absolute -top-px left-1/2 h-[3px] w-8 -translate-x-1/2 rounded-b-full bg-accent"
                             transition={{ type: "spring", stiffness: 500, damping: 36 }} />
              )}
              <span className={`grid h-7 w-12 place-items-center transition-transform duration-300 ease-out ${active
                ? "[&>span>svg]:scale-110" : ""}`}>
                <Pending>{t.icon}</Pending>
              </span>
              {t.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

/** Switch the active channel. On a channel's Discover deck, go to the new channel's
 *  deck (its URL names the channel); anywhere else, re-render for the new channel. */
function useSwitch() {
  const router = useRouter();
  const path = usePathname();
  const [pending, start] = useTransition();
  const go = (id: string) => start(async () => {
    await switchChannel(id);
    if (path.startsWith("/discover/")) router.push(`/discover/${id}`);
    else router.refresh();
  });
  return [pending, go] as const;
}

/** The channel name as a tap-to-switch picker, for page titles (phones have no top bar). */
export function ChannelPicker({ channels, activeId }: { channels: { id: string; name: string }[]; activeId: string }) {
  const [pending, go] = useSwitch();
  const name = channels.find((c) => c.id === activeId)?.name ?? "";
  if (channels.length < 2) return <span className="font-medium text-foreground">{name}</span>;
  return (
    <span className="relative inline-flex items-center font-medium text-foreground">
      {name}<span aria-hidden className="ml-0.5 text-muted">▾</span>
      <select aria-label="Switch channel" value={activeId} disabled={pending}
              onChange={(e) => go(e.target.value)}
              className="absolute inset-0 cursor-pointer opacity-0">
        {channels.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
    </span>
  );
}

export function ChannelSwitcher({ channels, activeId }: { channels: { id: string; name: string }[]; activeId: string }) {
  const [pending, go] = useSwitch();
  if (channels.length < 2)
    return <span className="max-w-[45vw] truncate text-sm font-medium">{channels[0]?.name}</span>;
  return (
    <select aria-label="Channel" value={activeId} disabled={pending}
            onChange={(e) => go(e.target.value)}
            className="max-w-[45vw] truncate rounded-md border border-border bg-background px-2 py-1 text-sm font-medium outline-none focus:border-accent">
      {channels.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
    </select>
  );
}
