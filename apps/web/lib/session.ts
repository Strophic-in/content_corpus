import "server-only";

import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";

import { auth } from "./auth";

// The Data Access Layer: the one place a request's user is established. Pages
// and server actions call requireUser(); nothing trusts proxy.ts's cookie check.
export const requireUser = cache(async () => {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) redirect("/login");
  return session.user;
});
