
import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "https://example.invalid",
  "Access-Control-Allow-Headers": "authorization, content-type, x-idempotency-key",
};

Deno.serve(async (request: Request): Promise<Response> => {
  if (request.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const idempotencyKey = request.headers.get("x-idempotency-key");
    if (!idempotencyKey) {
      return Response.json(
        { error: "missing_idempotency_key" },
        { status: 400, headers: corsHeaders },
      );
    }

    const body: unknown = await request.json();
    if (typeof body !== "object" || body === null) {
      return Response.json(
        { error: "invalid_body" },
        { status: 400, headers: corsHeaders },
      );
    }

    // Verify JWT or webhook signature.
    // Perform bounded, idempotent work. Keep privileged secrets server-side.
    return Response.json({ ok: true, idempotencyKey }, { headers: corsHeaders });
  } catch {
    return Response.json(
      { error: "unexpected_error" },
      { status: 500, headers: corsHeaders },
    );
  }
});
