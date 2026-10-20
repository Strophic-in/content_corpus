import "./env";

import { betterAuth } from "better-auth";
import { APIError } from "better-auth/api";
import { nextCookies } from "better-auth/next-js";

import { pool } from "./db";
import { ownerEmails, sendEmail } from "./email";

// Anyone may ask for an account (owner, 2026-10-20) and waits for an owner's approval
// (memberships, migration 0019: app_config.signups_need_approval); SIGNUPS_OPEN=false
// closes sign-ups to everyone but the owner(s). The check sits on user creation rather
// than on the form, so email+password and Google are held alike.
const allowed = (process.env.AUTH_ALLOWED_EMAILS ?? "")
  .split(",")
  .map((e) => e.trim().toLowerCase())
  .filter(Boolean);
const signupsOpen = process.env.SIGNUPS_OPEN !== "false";

export const auth = betterAuth({
  database: pool,
  secret: process.env.BETTER_AUTH_SECRET,
  baseURL: process.env.BETTER_AUTH_URL,
  emailAndPassword: {
    enabled: true,
    minPasswordLength: 12,
  },
  // Google checks the address it signs in, so an account made with a password on that
  // address and the same person's Google sign-in are one account (it failed with
  // account_not_linked, live 2026-10-20).
  account: { accountLinking: { enabled: true, trustedProviders: ["google"] } },
  // Registered only once its keys exist; the login page hides the button to match.
  socialProviders:
    process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET
      ? {
          google: {
            clientId: process.env.GOOGLE_CLIENT_ID,
            clientSecret: process.env.GOOGLE_CLIENT_SECRET,
          },
        }
      : {},
  databaseHooks: {
    user: {
      create: {
        before: async (user) => {
          if (!allowed.includes(user.email.toLowerCase()) && !signupsOpen) {
            throw new APIError("FORBIDDEN", { message: "Sign-ups are closed." });
          }
          return { data: user };
        },
        // Someone new: the database made them a member waiting for approval
        // (app_config.signups_need_approval); tell the owners.
        after: async (user) => {
          if (allowed.includes(user.email.toLowerCase())) return;
          const site = process.env.BETTER_AUTH_URL ?? "";
          await sendEmail(ownerEmails(), `New access request: ${user.name || user.email}`,
            `${user.name} <${user.email}> asked for access to Content Corpus.\n\n`
            + `Approve or decline them in Admin: ${site}/admin`, user.email);
          await sendEmail(user.email, "We got your request for Content Corpus",
            `Hi ${user.name || "there"},\n\nThanks for asking for access to Content Corpus. Accounts are let in by `
            + `hand, so yours is waiting for approval. We'll email you as soon as it's ready.\n\n`
            + `Content Corpus\n${site}`);
        },
      },
    },
  },
  plugins: [nextCookies()],
});

export type Session = typeof auth.$Infer.Session;
