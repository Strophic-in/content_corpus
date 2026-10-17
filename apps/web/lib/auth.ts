import "./env";

import { betterAuth } from "better-auth";
import { APIError } from "better-auth/api";
import { nextCookies } from "better-auth/next-js";

import { pool } from "./db";
import { ownerEmails, sendEmail } from "./email";

// Signup is closed to everyone but the owner(s) unless SIGNUPS_OPEN=true; then
// anyone may sign up and waits for an owner's approval (memberships, migration
// 0019). The check sits on user creation rather than on the signup form, so it
// covers email+password and Google alike — a second sign-in path cannot be the
// one that forgets to check.
const allowed = (process.env.AUTH_ALLOWED_EMAILS ?? "")
  .split(",")
  .map((e) => e.trim().toLowerCase())
  .filter(Boolean);
const signupsOpen = process.env.SIGNUPS_OPEN === "true";

export const auth = betterAuth({
  database: pool,
  secret: process.env.BETTER_AUTH_SECRET,
  baseURL: process.env.BETTER_AUTH_URL,
  emailAndPassword: {
    enabled: true,
    minPasswordLength: 12,
  },
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
          await sendEmail(ownerEmails(), "New sign-up on Content Corpus",
            `${user.name} <${user.email}> signed up. Approve or decline them on the Members page:\n`
            + `${process.env.BETTER_AUTH_URL ?? ""}/admin`);
        },
      },
    },
  },
  plugins: [nextCookies()],
});

export type Session = typeof auth.$Infer.Session;
