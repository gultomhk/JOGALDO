export default {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    const targetUrl = url.pathname.slice(1); // Hapus "/" depan

    if (!targetUrl.startsWith("https://")) {
      return new Response("Invalid target URL", { status: 400 });
    }

    const clonedRequest = request.clone();

    // Override User-Agent
    const headers = new Headers(clonedRequest.headers);
    headers.set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36");

    const proxyRes = await fetch(targetUrl, {
      method: clonedRequest.method,
      headers,
      body: ["GET", "HEAD"].includes(clonedRequest.method) ? undefined : await clonedRequest.blob(),
      redirect: "follow",
    });

    // Buat headers baru yang aman
    const responseHeaders = new Headers();
    for (const [key, value] of proxyRes.headers.entries()) {
      if (!["content-encoding", "transfer-encoding"].includes(key.toLowerCase())) {
        responseHeaders.set(key, value);
      }
    }

    return new Response(proxyRes.body, {
      status: proxyRes.status,
      headers: responseHeaders,
    });
  }
}
