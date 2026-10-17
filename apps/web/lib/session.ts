import "server-only";

import { headers } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { cache } from "react";

import { auth } from "./auth";
import { asUser } from "./db";

export type Membership = { role: "owner" | "member"; status: "pending" | "active" | "suspended" };

/** One's own membership (RLS lets an account read only its own row). */
export const membership = cache(async (userId: string): Promise<Membership | undefined> =>
  asUser(userId, async (db) =>
    (await db.query("select role, status from memberships where user_id = $1", [userId])).rows[0] as
      | Membership | undefined));

// The Data Access Layer: the one place a request's user is established. Pages
// and server actions call requireUser(); nothing trusts proxy.ts's cookie check.
// An account that isn't active (waiting for approval, or suspended) is sent to
// /pending — and the database refuses its API calls anyway (private.caller()).
export const requireUser = cache(async () => {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) redirect("/login");
  const m = await membership(session.user.id);
  if (m?.status !== "active") redirect("/pending");
  return { ...session.user, role: m.role };
});

/** The owner's pages (members, health): anyone else gets a 404. */
export const requireOwner = cache(async () => {
  const user = await requireUser();
  if (user.role !== "owner") notFound();
  return user;
});
