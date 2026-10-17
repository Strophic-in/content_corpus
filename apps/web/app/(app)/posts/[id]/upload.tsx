"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { deleteUpload, startUpload, type ActionState } from "../../actions";

type Item = { name: string; pct: number; error?: string; done?: boolean };

function put(assetId: string, file: File, progress: (pct: number) => void): Promise<string | null> {
  return new Promise((resolve) => {
    const x = new XMLHttpRequest();
    x.open("PUT", `/api/upload/${assetId}`);
    x.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    x.upload.onprogress = (e) => e.lengthComputable && progress(Math.round((100 * e.loaded) / e.total));
    x.onload = () => {
      if (x.status >= 200 && x.status < 300) return resolve(null);
      try {
        resolve((JSON.parse(x.responseText) as { error?: string }).error ?? `upload failed (${x.status})`);
      } catch {
        resolve(`upload failed (${x.status})`);
      }
    };
    x.onerror = () => resolve("the connection dropped — try again");
    x.send(file);
  });
}

/** Add your own videos or photos to a post: they are yours (no credit), and the
 *  script can use them once they are checked and analysed. */
export function UploadFootage({ postId }: { postId: string }) {
  const router = useRouter();
  const [items, setItems] = useState<Item[]>([]);
  const busy = items.some((i) => !i.done && !i.error);
  const set = (n: number, patch: Partial<Item>) => setItems((all) => all.map((it, k) => (k === n ? { ...it, ...patch } : it)));

  async function onFiles(list: FileList | null) {
    const files = Array.from(list ?? []);
    if (!files.length) return;
    const base = items.length;
    setItems((all) => [...all, ...files.map((f) => ({ name: f.name, pct: 0 }))]);
    for (const [k, f] of files.entries()) {
      const r = await startUpload(postId, f.name, f.size, f.type);
      if (!r.ok || !r.assetId) {
        set(base + k, { error: r.error ?? "couldn't start" });
        continue;
      }
      const err = await put(r.assetId, f, (pct) => set(base + k, { pct }));
      set(base + k, err ? { error: err } : { done: true, pct: 100 });
      router.refresh();
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <label className={`w-fit cursor-pointer rounded-md border border-border px-3 py-2 text-sm font-medium hover:border-accent ${busy ? "pointer-events-none opacity-60" : ""}`}>
        {busy ? "Uploading…" : "+ Add your own videos or photos"}
        <input type="file" multiple accept="video/mp4,video/quicktime,video/webm,image/jpeg,image/png,image/webp"
               className="sr-only" onChange={(e) => { void onFiles(e.target.files); e.target.value = ""; }} />
      </label>
      <p className="text-xs text-muted">Up to 300 MB and 15 minutes a video, 25 MB a photo, 12 files a post. They&apos;re
        treated as yours — never credited to anyone — so upload only what you own or may use.</p>
      {items.length > 0 && (
        <ul className="flex flex-col gap-1 text-xs">
          {items.map((it, k) => (
            <li key={k} className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate">{it.name}</span>
              {it.error ? <span className="text-danger">{it.error}</span>
                : it.done ? <span className="text-ok">uploaded — checking it…</span>
                : <span className="tabular-nums text-muted">{it.pct}%</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function DeleteUploadButton({ assetId }: { assetId: string }) {
  const [state, setState] = useState<ActionState>(null);
  const [pending, start] = useTransition();
  return (
    <span className="flex flex-col items-end gap-1">
      <button disabled={pending} onClick={() => start(async () => setState(await deleteUpload(assetId)))}
              className="text-xs font-medium text-danger hover:underline disabled:opacity-50">Remove</button>
      {state?.error && <span className="text-xs text-danger">{state.error}</span>}
    </span>
  );
}
