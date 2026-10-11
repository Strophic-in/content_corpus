import { ImageResponse } from "next/og";
import type { NextRequest } from "next/server";

// App icons, drawn on request (no binary files to keep): a play mark on the
// accent gradient. ?maskable=1 leaves the safe-zone padding Android masks expect.
export async function GET(req: NextRequest, ctx: RouteContext<"/icons/[size]">) {
  const { size } = await ctx.params;
  const px = [180, 192, 512].includes(Number(size)) ? Number(size) : 192;
  const maskable = req.nextUrl.searchParams.has("maskable");
  const mark = Math.round(px * (maskable ? 0.32 : 0.42));
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center",
                    background: "linear-gradient(135deg, #6366f1 0%, #a855f7 55%, #ec4899 100%)",
                    borderRadius: maskable ? 0 : Math.round(px * 0.22) }}>
        <svg width={mark} height={mark} viewBox="0 0 100 100" style={{ marginLeft: Math.round(mark * 0.12) }}>
          <path d="M18 8 L92 50 L18 92 Z" fill="white" strokeLinejoin="round" stroke="white" strokeWidth="10" />
        </svg>
      </div>
    ),
    { width: px, height: px, headers: { "Cache-Control": "public, max-age=604800, immutable" } },
  );
}
