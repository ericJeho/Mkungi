"use client";

import { useState } from "react";

import { supabase } from "@/lib/supabase";

export default function SignIn() {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!supabase) return;
    setState("sending");
    setError(null);
    const { error } = await supabase.auth.signInWithOtp({
      email: email.trim(),
      options: { emailRedirectTo: window.location.origin },
    });
    if (error) {
      setError(error.message);
      setState("idle");
    } else {
      setState("sent");
    }
  }

  if (state === "sent") {
    return (
      <div className="rounded-xl bg-paper px-4 py-8 text-center">
        <p className="font-semibold text-ink">Check your email</p>
        <p className="mt-1 text-sm text-ink-soft">
          We sent a sign-in link to <span className="font-medium text-ink">{email}</span>. Open it in this browser to
          continue.
        </p>
        <button onClick={() => setState("idle")} className="mt-4 text-sm font-medium text-clay hover:underline">
          Use a different email
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="rounded-xl bg-paper px-4 py-6">
      <p className="font-semibold text-ink">Sign in to convert documents</p>
      <p className="mt-1 text-sm text-ink-soft">No password needed — we&apos;ll email you a sign-in link.</p>
      <div className="mt-4 flex flex-col gap-2 sm:flex-row">
        <label htmlFor="email" className="sr-only">
          Email address
        </label>
        <input
          id="email"
          type="email"
          required
          autoComplete="email"
          placeholder="you@organisation.org"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="min-w-0 flex-1 rounded-lg border border-ink/20 bg-white px-3 py-2 text-sm text-ink outline-none focus:border-clay"
        />
        <button
          type="submit"
          disabled={state === "sending"}
          className="rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-white hover:bg-ink-soft disabled:opacity-60"
        >
          {state === "sending" ? "Sending…" : "Email me a link"}
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-red-700">{error}</p>}
    </form>
  );
}
