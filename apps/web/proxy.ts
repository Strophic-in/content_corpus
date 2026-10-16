import { getSessionCookie } from "better-auth/cookies";
import { NextResponse, type NextRequest } from "next/server";

// Optimistic gate only: it checks that a session cookie exists, not that it is
// valid. Every page and server action verifies the session itself through
// lib/session.ts, so a forged cookie gets past this redirect and no further.
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasSession = Boolean(getSessionCookie(request));

  if (pathname === "/login") {
    return hasSession
      ? NextResponse.redirect(new URL("/discover", request.url))
      : NextResponse.next();
  }
  if (!hasSession) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    // Everything except auth API, Next internals, static assets and the app manifest
    // and icons (a phone fetches those without cookies when installing the app).
    "/((?!api/auth|_next/static|_next/image|favicon.ico|manifest.webmanifest|icons/|privacy|terms|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};
