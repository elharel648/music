// Alma: issue a license key and a one-hour download link to an approved, signed-in user.
//
// Deploy:  supabase functions deploy issue --no-verify-jwt=false
// Secrets: supabase secrets set ALMA_PRIVATE_SEED_HEX=<64 hex chars from `python tools/keygen.py export-seed`>
//          supabase secrets set ALMA_PUBLIC_KEY_HEX=<the PUBLIC_KEY_HEX in flow/license.py>
// SUPABASE_URL / SUPABASE_ANON_KEY / SUPABASE_SERVICE_ROLE_KEY are provided by the platform.
//
// The key format must match flow/license.py exactly:
//   ALMA-<b64url(json)>.<b64url(ed25519 signature over the json bytes)>
//   json = {"email":...,"expires":null,"issued":"YYYY-MM-DD","product":"Alma","seats":1}   (keys sorted, no spaces)
import { createClient } from "npm:@supabase/supabase-js@2";

const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type" };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { ...CORS, "Content-Type": "application/json" } });

const hexToBytes = (hex: string) => new Uint8Array(hex.match(/.{2}/g)!.map((h) => parseInt(h, 16)));
const b64url = (bytes: Uint8Array) => btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

async function issueKey(email: string, days: number | null): Promise<string> {
  const seed = hexToBytes(Deno.env.get("ALMA_PRIVATE_SEED_HEX")!);
  const pub = hexToBytes(Deno.env.get("ALMA_PUBLIC_KEY_HEX")!);
  const jwk = { kty: "OKP", crv: "Ed25519", d: b64url(seed), x: b64url(pub), ext: true };
  const key = await crypto.subtle.importKey("jwk", jwk, { name: "Ed25519" }, false, ["sign"]);
  const today = new Date().toISOString().slice(0, 10);
  const expires = days ? new Date(Date.now() + days * 86400000).toISOString().slice(0, 10) : null;
  const payload = { email, expires, issued: today, product: "Alma", seats: 1 };   // alphabetical = Python's sort_keys
  const body = new TextEncoder().encode(JSON.stringify(payload));
  const sig = new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, key, body));
  return `ALMA-${b64url(body)}.${b64url(sig)}`;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  const url = Deno.env.get("SUPABASE_URL")!;
  const auth = req.headers.get("Authorization") ?? "";
  const asUser = createClient(url, Deno.env.get("SUPABASE_ANON_KEY")!, { global: { headers: { Authorization: auth } } });
  const { data: { user } } = await asUser.auth.getUser();
  if (!user?.email) return json({ error: "not signed in" }, 401);

  const admin = createClient(url, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
  const { data: prof } = await admin.from("profiles").select("approved, founding, key").eq("id", user.id).maybeSingle();
  if (!prof?.approved) return json({ status: "pending" });

  let key = prof.key as string | null;
  if (!key) {
    key = await issueKey(user.email, prof.founding ? null : 365);
    await admin.from("profiles").update({ key, key_issued_at: new Date().toISOString() }).eq("id", user.id);
  }
  const { data: rel } = await admin.from("releases").select("version, path").eq("platform", "mac").order("created_at", { ascending: false }).limit(1).maybeSingle();
  if (!rel) return json({ status: "approved", key, version: null, url: null });
  const { data: signed, error } = await admin.storage.from("releases").createSignedUrl(rel.path, 3600, { download: rel.path });
  if (error) return json({ status: "approved", key, version: rel.version, url: null, error: error.message });
  return json({ status: "approved", key, version: rel.version, url: signed.signedUrl });
});
