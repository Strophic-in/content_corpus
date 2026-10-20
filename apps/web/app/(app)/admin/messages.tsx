"use client";

import { useState, useTransition } from "react";

import { markMessage } from "./admin-actions";

export type Message = {
  id: string; name: string; email: string; topic: string; message: string; emailed: boolean;
  read_at: string | null; created_at: string;
};

/** The contact page's messages: newest first, unread ones lit. */
export function Messages({ items }: { items: Message[] }) {
  if (!items.length) {
    return <p className="p-5 text-sm text-muted">No messages yet. They arrive here from the contact page.</p>;
  }
  return (
    <ul className="flex flex-col divide-y divide-border">
      {items.map((m) => <Row key={m.id} m={m} />)}
    </ul>
  );
}

function Row({ m }: { m: Message }) {
  const [read, setRead] = useState(Boolean(m.read_at));
  const [pending, start] = useTransition();
  const flip = () => {
    const next = !read;
    setRead(next);
    start(async () => { const r = await markMessage(m.id, next); if (!r?.ok) setRead(!next); });
  };
  const when = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" })
    .format(new Date(m.created_at));
  const reply = `mailto:${m.email}?subject=${encodeURIComponent(`Re: ${m.topic || "your message"}`)}`;
  return (
    <li className={`flex flex-col gap-2 p-5 ${read ? "" : "border-l-2 border-accent bg-accent/5"}`}>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm">
        {!read && <span className="kicker text-accent">New</span>}
        <span className="font-semibold">{m.name || "(no name)"}</span>
        <a href={`mailto:${m.email}`} className="text-muted hover:text-foreground">{m.email}</a>
        <span className="ml-auto text-xs text-muted">{when}</span>
      </div>
      <p className="kicker text-muted">{m.topic}{m.emailed ? " · also emailed" : ""}</p>
      <p className="text-sm whitespace-pre-wrap">{m.message}</p>
      <div className="flex gap-4 text-sm">
        <a href={reply} className="font-medium text-accent hover:underline">Reply</a>
        <button type="button" onClick={flip} disabled={pending} className="text-muted hover:text-foreground disabled:opacity-60">
          {read ? "Mark unread" : "Mark read"}
        </button>
      </div>
    </li>
  );
}
