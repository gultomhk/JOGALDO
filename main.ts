import { serve } from "https://deno.land/std/http/server.ts";

// Ambil cookie dari ENV
const VIDIO_VISITOR = Deno.env.get("VIDIO_VISITOR") || "";
const VIDIO_VISIT = Deno.env.get("VIDIO_VISIT") || "";

serve(async (req: Request): Promise<Response> => {
  const url = new URL(req.url);
  const pathname = url.pathname;
  const id = url.searchParams.get("id");

  if (pathname !== "/play.m3u8") {
    return new Response("Not Found", { status: 404 });
  }

  if (!id) {
    return new Response("Missing id parameter", { status: 400 });
  }

  const token_url = `https://www.vidio.com/live/${id}/tokens`;
  const headers = {
    "User-Agent": "Mozilla/5.0",
    "Referer": `https://www.vidio.com/live/${id}`,
    "Origin": "https://www.vidio.com",
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "Cookie": `ahoy_visitor=${VIDIO_VISITOR}; ahoy_visit=${VIDIO_VISIT};`
  };

  try {
    const tokenRes = await fetch(token_url, {
      method: "POST",
      headers,
    });

    if (tokenRes.status === 403) {
      return new Response("Access forbidden (403)", { status: 403 });
    }

    if (!tokenRes.ok) {
      return new Response(`Error: ${tokenRes.status}`, { status: tokenRes.status });
    }

    const tokenData = await tokenRes.json();
    const hls_url = tokenData.hls_url;

    if (!hls_url) {
      return new Response("No HLS URL found in response", { status: 500 });
    }

    return new Response(hls_url + "\n", {
      status: 200,
      headers: {
        "Content-Type": "application/vnd.apple.mpegurl",
      },
    });

  } catch (err) {
    return new Response("Server error: " + err.message, { status: 500 });
  }
});
