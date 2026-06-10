import { NextRequest, NextResponse } from "next/server";

// Catch-all proxy: the browser hits Vercel's own /api/* routes, this handler
// forwards them to the Railway backend with the bearer token attached. The
// token reads from a PRIVATE env var (no NEXT_PUBLIC_ prefix), so it never
// gets shipped to the browser.

const BACKEND_URL = process.env.BACKEND_API_URL ?? "";
const BACKEND_TOKEN = process.env.BACKEND_API_TOKEN ?? "";

// Forces the Node runtime (not Edge) so streaming + standard fetch behaviour
// are predictable. Also keeps cold starts reasonable for this kind of pass-through.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function proxy(
  req: NextRequest,
  ctx: { params: { path: string[] } }
): Promise<NextResponse> {
  if (!BACKEND_URL || !BACKEND_TOKEN) {
    return NextResponse.json(
      { detail: "Backend proxy not configured. Set BACKEND_API_URL and BACKEND_API_TOKEN." },
      { status: 503 }
    );
  }

  const pathSegments = ctx.params.path ?? [];
  const search = new URL(req.url).search;
  const target = `${BACKEND_URL.replace(/\/$/, "")}/api/${pathSegments.join("/")}${search}`;

  const fwdHeaders = new Headers();
  fwdHeaders.set("Authorization", `Bearer ${BACKEND_TOKEN}`);
  const contentType = req.headers.get("content-type");
  if (contentType) fwdHeaders.set("Content-Type", contentType);

  const init: RequestInit = {
    method: req.method,
    headers: fwdHeaders,
    // No cache — every dashboard call should hit fresh state.
    cache: "no-store",
  };

  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.text();
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch (err) {
    return NextResponse.json(
      { detail: `Backend unreachable: ${(err as Error).message}` },
      { status: 502 }
    );
  }

  // Pass through status + body + content-type. Deliberately drop other
  // upstream headers (Set-Cookie, custom auth headers) so the proxy can't
  // accidentally surface backend internals to the browser.
  const respHeaders = new Headers();
  const upstreamCT = upstream.headers.get("content-type");
  if (upstreamCT) respHeaders.set("Content-Type", upstreamCT);

  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: respHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
