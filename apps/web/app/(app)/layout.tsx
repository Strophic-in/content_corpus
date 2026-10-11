import Link from "next/link";

import { workspace } from "@/lib/channels";
import { requireUser } from "@/lib/session";

import { BottomTabs, ChannelSwitcher, DesktopNav } from "./nav";
import { SignOutButton } from "./sign-out-button";

// One layout, two feels: on a desktop a top bar with links; on a phone (or the
// installed app) a slim top bar with the channel switcher and a tab bar at the
// bottom, like a native app.
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const user = await requireUser();
  const { channels, active } = await workspace(user.id);
  return (
    <div className="flex flex-1 flex-col">
      <header className="sticky top-0 z-30 border-b border-border bg-surface/95 pt-[env(safe-area-inset-top)] backdrop-blur">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center gap-4 px-4">
          <Link href="/discover" className="hidden font-semibold tracking-tight md:block">Content Corpus</Link>
          <ChannelSwitcher channels={channels.map(({ id, name }) => ({ id, name }))} activeId={active.id} />
          <DesktopNav />
          <div className="ml-auto flex items-center gap-3 text-sm text-muted">
            <span className="hidden lg:inline">{user.email}</span>
            <SignOutButton />
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 pt-6 pb-28 md:py-8">{children}</main>
      <BottomTabs />
    </div>
  );
}
