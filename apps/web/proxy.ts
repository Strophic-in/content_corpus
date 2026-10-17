import { getSessionCookie } from "better-auth/cookies";
import { NextResponse, type NextRequest } from "next/server";

// Optimistic gate only: it checks that a session cookie exists, not that it is
// valid. Every page and server action verifies the session itself through
// lib/session.ts, so a forged cookie gets past this redirect and no further.
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasSession = Boolean(getSessionCookie(request));

  // The homepage is public: Google's app verification rejects one behind a login.
  if (pathname === "/") return NextResponse.next();
  // The login page checks the session itself: a stale cookie (its session ended on
  // the server) used to bounce between /login and /discover forever.
  if (pathname === "/login") return NextResponse.next();
  if (!hasSession) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    // Everything except auth API, Next internals, static assets and the app manifest
    // and icons (a phone fetches those without cookies when installing the app), and
    // robots.txt.
    "/((?!api/auth|_next/static|_next/image|favicon.ico|manifest.webmanifest|robots.txt|icons/|privacy|terms|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};
