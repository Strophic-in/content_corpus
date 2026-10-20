import { ImageResponse } from "next/og";
import type { NextRequest } from "next/server";

// App icons, drawn on request (no binary files to keep): a paper-white play mark on
// ink, with the red on-air light. ?maskable=1 leaves the safe-zone padding Android masks expect.
export async function GET(req: NextRequest, ctx: RouteContext<"/icons/[size]">) {
  const { size } = await ctx.params;
  const px = [180, 192, 512].includes(Number(size)) ? Number(size) : 192;
  const maskable = req.nextUrl.searchParams.has("maskable");
  const mark = Math.round(px * (maskable ? 0.32 : 0.42));
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center",
                    position: "relative", background: "#17140f",
                    borderRadius: maskable ? 0 : Math.round(px * 0.22) }}>
        <svg width={mark} height={mark} viewBox="0 0 100 100" style={{ marginLeft: Math.round(mark * 0.12) }}>
          <path d="M18 8 L92 50 L18 92 Z" fill="#f1ece2" strokeLinejoin="round" stroke="#f1ece2" strokeWidth="10" />
        </svg>
        {/* the on-air light */}
        <div style={{ position: "absolute", top: Math.round(px * (maskable ? 0.24 : 0.16)),
                      right: Math.round(px * (maskable ? 0.24 : 0.16)), width: Math.round(px * 0.13),
                      height: Math.round(px * 0.13), borderRadius: 9999, background: "#e2291f" }} />
      </div>
    ),
    { width: px, height: px, headers: { "Cache-Control": "public, max-age=604800, immutable" } },
  );
}
