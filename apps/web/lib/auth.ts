import "./env";

import { betterAuth } from "better-auth";
import { APIError } from "better-auth/api";
import { nextCookies } from "better-auth/next-js";

import { pool } from "./db";

// Signup is closed to everyone but the owner(s) for now. The check sits on user
// creation rather than on the signup form, so it covers email+password and Google
// alike — a second sign-in path cannot be the one that forgets to check.
const allowed = (process.env.AUTH_ALLOWED_EMAILS ?? "")
  .split(",")
  .map((e) => e.trim().toLowerCase())
  .filter(Boolean);

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
          if (!allowed.includes(user.email.toLowerCase())) {
            throw new APIError("FORBIDDEN", { message: "Sign-ups are closed." });
          }
          return { data: user };
        },
      },
    },
  },
  plugins: [nextCookies()],
});

export type Session = typeof auth.$Infer.Session;
