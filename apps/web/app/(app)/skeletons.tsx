// What a tab shows the instant it is tapped, while the server renders it: the page's
// own shape in soft placeholders (each tab's loading.tsx). Next prefetches these, so
// switching tabs never waits on the server to show something.

export function Bone({ className = "" }: { className?: string }) {
  return <div aria-hidden className={`skeleton rounded-lg ${className}`} />;
}

export function Head({ wide = false, action = false }: { wide?: boolean; action?: boolean }) {
  return (
    <div className="flex items-end justify-between gap-3">
      <div className="flex flex-col gap-2">
        <Bone className="h-7 w-36" />
        <Bone className={`h-4 ${wide ? "w-72" : "w-52"} max-w-[70vw]`} />
      </div>
      {action && <Bone className="h-8 w-24 rounded-full" />}
    </div>
  );
}

function Loading({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div role="status" aria-label="Loading" className={`flex flex-col gap-5 ${className}`}>
      {children}
      <span className="sr-only">Loading…</span>
    </div>
  );
}

export function ListSkeleton({ rows = 5, className = "mx-auto w-full max-w-3xl" }: { rows?: number; className?: string }) {
  return (
    <Loading className={className}>
      <Head action />
      <div className="flex flex-col gap-3">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className="flex items-center gap-3 rounded-2xl border border-border bg-surface p-4">
            <Bone className="size-9 shrink-0 rounded-full" />
            <div className="flex flex-1 flex-col gap-2">
              <Bone className="h-4 w-2/5" />
              <Bone className="h-3 w-3/5" />
            </div>
          </div>
        ))}
      </div>
    </Loading>
  );
}

export function CardsSkeleton({ cards = 4, className = "mx-auto w-full max-w-2xl" }: { cards?: number; className?: string }) {
  return (
    <Loading className={className}>
      <Head action />
      <div className="grid gap-3 sm:grid-cols-2">
        {Array.from({ length: cards }, (_, i) => (
          <div key={i} className="flex h-40 flex-col gap-3 rounded-2xl border border-border bg-surface p-4">
            <Bone className="h-5 w-1/2" />
            <Bone className="h-3 w-full" />
            <Bone className="h-3 w-4/5" />
            <div className="mt-auto flex gap-2"><Bone className="h-6 w-16 rounded-full" /><Bone className="h-6 w-20 rounded-full" /></div>
          </div>
        ))}
      </div>
    </Loading>
  );
}

export function DeckSkeleton() {
  return (
    <Loading className="mx-auto w-full max-w-md">
      <Head action />
      <div className="flex min-h-[min(58vh,520px)] flex-col gap-3 rounded-3xl border border-border bg-surface p-5">
        <div className="flex gap-2"><Bone className="h-5 w-20 rounded-full" /><Bone className="h-5 w-40 rounded-full" /></div>
        <Bone className="aspect-video w-full rounded-2xl" />
        <Bone className="h-12 w-full rounded-xl" />
        <Bone className="h-7 w-4/5" />
        <Bone className="h-4 w-3/5" />
        <Bone className="h-3 w-full" />
        <Bone className="h-3 w-11/12" />
      </div>
      <div className="flex justify-center gap-8"><Bone className="size-16 rounded-full" /><Bone className="size-16 rounded-full" /></div>
    </Loading>
  );
}

export function VideoGridSkeleton({ cards = 6 }: { cards?: number }) {
  return (
    <ul aria-hidden className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: cards }, (_, i) => (
        <li key={i} className="flex flex-col overflow-hidden rounded-2xl border border-border bg-surface">
          <Bone className="aspect-video w-full rounded-none" />
          <div className="flex flex-col gap-2 p-3">
            <Bone className="h-4 w-11/12" />
            <Bone className="h-3 w-1/2" />
            <Bone className="h-3 w-2/3" />
            <Bone className="mt-1 h-8 w-full rounded-xl" />
          </div>
        </li>
      ))}
    </ul>
  );
}

export function PosterGridSkeleton({ cards = 10 }: { cards?: number }) {
  return (
    <Loading>
      <Head action />
      <div className="flex gap-2">{["w-16", "w-24", "w-32", "w-28"].map((w) => <Bone key={w} className={`h-7 rounded-full ${w}`} />)}</div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {Array.from({ length: cards }, (_, i) => (
          <div key={i} className="flex flex-col gap-2 rounded-2xl border border-border bg-surface p-2">
            <Bone className="aspect-[9/16] w-full rounded-xl" />
            <Bone className="h-4 w-11/12" />
            <Bone className="h-3 w-1/2" />
          </div>
        ))}
      </div>
    </Loading>
  );
}

export function CalendarSkeleton() {
  return (
    <Loading>
      <div className="flex items-center justify-between gap-3">
        <div className="flex flex-col gap-2"><Bone className="h-7 w-44" /><Bone className="h-4 w-28" /></div>
        <div className="flex gap-2"><Bone className="h-8 w-9" /><Bone className="h-8 w-16" /><Bone className="h-8 w-9" /></div>
      </div>
      <div className="grid grid-cols-7 gap-px overflow-hidden rounded-xl border border-border bg-border">
        {Array.from({ length: 35 }, (_, i) => (
          <div key={i} className="flex min-h-24 flex-col gap-1.5 bg-surface p-2">
            <Bone className="h-3 w-4" />
            {i % 3 === 0 && <Bone className="h-8 w-full" />}
          </div>
        ))}
      </div>
    </Loading>
  );
}

export function FormSkeleton({ blocks = 4 }: { blocks?: number }) {
  return (
    <Loading className="mx-auto w-full max-w-2xl">
      <Head />
      {Array.from({ length: blocks }, (_, i) => (
        <div key={i} className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-5">
          <Bone className="h-5 w-40" />
          <Bone className="h-3 w-3/4" />
          <Bone className="h-10 w-full rounded-md" />
          <Bone className="h-10 w-full rounded-md" />
        </div>
      ))}
    </Loading>
  );
}

export function PostSkeleton() {
  return (
    <Loading>
      <div className="flex flex-col gap-2"><Bone className="h-4 w-20" /><Bone className="h-8 w-3/4" /><Bone className="h-4 w-56" /></div>
      <div className="grid gap-5 md:grid-cols-[minmax(0,17rem)_minmax(0,1fr)] lg:grid-cols-[minmax(0,19rem)_minmax(0,1fr)]">
        <Bone className="aspect-[9/16] w-full max-w-xs justify-self-center rounded-2xl md:max-w-none" />
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-4">
            <Bone className="h-5 w-40" /><Bone className="h-3 w-2/3" /><Bone className="h-9 w-36 rounded-full" />
          </div>
          <div className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-4">
            {Array.from({ length: 6 }, (_, i) => (
              <div key={i} className="flex items-center gap-3"><Bone className="size-7 rounded-full" /><Bone className="h-4 w-48" /></div>
            ))}
          </div>
        </div>
      </div>
    </Loading>
  );
}
