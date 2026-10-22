"use client";

import type { Session } from "@supabase/supabase-js";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError, apiUrl, authHeader } from "@/lib/api";
import { supabase } from "@/lib/supabase";

import SignIn from "./SignIn";

const ACCEPT = ".png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.pdf";
const MAX_MB = 25;

type Format = "auto" | "docx" | "xlsx";

type ServerJob = {
  id: string;
  status: "awaiting_upload" | "processing" | "done" | "failed";
  filename: string;
  created_at?: string;
  output_format?: "docx" | "xlsx";
  doc_type?: string;
  pages?: number;
  tables?: number;
  images?: number;
  error?: string;
};

type Job = Omit<ServerJob, "id" | "status"> & {
  /** Client-side key; for jobs loaded from history it is the server id. */
  key: string;
  id?: string;
  status: "uploading" | "processing" | "done" | "failed";
};

type Created = {
  id: string;
  upload: { method: string; url: string; headers: Record<string, string> };
};

const FORMATS: { value: Format; label: string }[] = [
  { value: "auto", label: "Auto" },
  { value: "docx", label: "Word" },
  { value: "xlsx", label: "Excel" },
];

function label(docType?: string) {
  const text = (docType ?? "").replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function fromServer(j: ServerJob): Job | null {
  const { status } = j;
  if (status === "awaiting_upload") return null; // never uploaded; nothing to show
  return { ...j, status, key: j.id };
}

/**
 * create job -> upload the file straight to storage -> run the conversion.
 * In production the upload URL is a signed Supabase Storage URL, so the file
 * never passes through the API (Vercel caps request bodies at 4.5 MB).
 */
async function convertFile(file: File, format: Format, update: (patch: Partial<Job>) => void) {
  if (file.size > MAX_MB * 1024 * 1024) throw new Error(`File is larger than ${MAX_MB} MB`);
  const job = await api<Created>("/v1/conversions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: file.name, output_format: format }),
  });
  update({ id: job.id });

  // Local API uploads need the sign-in token; signed Storage URLs carry their own.
  const relative = job.upload.url.startsWith("/");
  const headers = { ...job.upload.headers, ...(relative ? await authHeader() : {}) };
  const put = await fetch(apiUrl(job.upload.url), { method: job.upload.method, headers, body: file });
  if (!put.ok) throw new Error(`Upload failed (${put.status})`);

  update({ status: "processing" });
  return api<ServerJob>(`/v1/conversions/${job.id}/process`, { method: "POST" });
}

async function download(job: Job) {
  // A plain link can't carry the sign-in token, so ask for a short-lived signed link first.
  const { url, filename } = await api<{ url: string; filename: string }>(`/v1/conversions/${job.id}/download-url`);
  if (!url.startsWith("/")) {
    window.location.href = url; // signed Storage URL: no token needed
    return;
  }
  // A path on the API itself (local storage): fetch it with the token and save the file.
  const res = await fetch(apiUrl(url), { headers: await authHeader() });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const href = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href, download: filename });
  a.click();
  setTimeout(() => URL.revokeObjectURL(href), 10_000);
}

function useSession() {
  // undefined while loading; null when signed out (or sign-in is off).
  const [session, setSession] = useState<Session | null | undefined>(supabase ? undefined : null);
  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((_event, s) => setSession(s));
    return () => data.subscription.unsubscribe();
  }, []);
  return session;
}

export default function Converter() {
  const session = useSession();
  const [format, setFormat] = useState<Format>("auto");
  const [dragging, setDragging] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const userId = session?.user.id;

  // Load the signed-in user's recent conversions; clear the list on sign-out.
  useEffect(() => {
    if (!userId) {
      setJobs([]);
      return;
    }
    api<ServerJob[]>("/v1/conversions")
      .then((list) => {
        const history = list.map(fromServer).filter((j): j is Job => j !== null);
        // Merge, don't replace: uploads started before this returned are already
        // in the list, and their own updates must keep landing on them.
        setJobs((prev) => [...prev, ...history.filter((h) => !prev.some((p) => p.id === h.id))]);
      })
      .catch(() => undefined);
  }, [userId]);

  const upload = useCallback(
    (files: FileList | File[]) => {
      for (const file of Array.from(files)) {
        const key = crypto.randomUUID();
        const update = (patch: Partial<Job>) =>
          setJobs((prev) => prev.map((j) => (j.key === key ? { ...j, ...patch } : j)));
        setJobs((prev) => [{ key, filename: file.name, status: "uploading" }, ...prev]);
        convertFile(file, format, update)
          .then((done) => update({ ...fromServer(done), key }))
          .catch((e) => {
            const expired = e instanceof ApiError && e.status === 401;
            update({ status: "failed", error: expired ? "Please sign in again." : e.message || "Conversion failed" });
          });
      }
    },
    [format],
  );

  const failDownload = (job: Job) => (e: unknown) =>
    setJobs((prev) =>
      prev.map((j) =>
        j.key === job.key ? { ...j, status: "failed", error: e instanceof Error ? e.message : "Download failed" } : j,
      ),
    );

  if (session === undefined) {
    return <div className="h-64 animate-pulse rounded-2xl border border-ink/10 bg-white" aria-busy="true" />;
  }

  return (
    <div className="rounded-2xl border border-ink/10 bg-white p-5 shadow-sm sm:p-6">
      {supabase && session && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-ink/10 pb-3 text-sm">
          <span className="truncate text-ink-soft">
            Signed in as <span className="font-medium text-ink">{session.user.email}</span>
          </span>
          <button onClick={() => supabase?.auth.signOut()} className="font-medium text-clay hover:underline">
            Sign out
          </button>
        </div>
      )}

      {supabase && !session ? (
        <SignIn />
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <span className="text-sm font-medium text-ink-soft">Convert to</span>
            <div role="radiogroup" className="inline-flex rounded-lg bg-paper p-1">
              {FORMATS.map((f) => (
                <button
                  key={f.value}
                  role="radio"
                  aria-checked={format === f.value}
                  onClick={() => setFormat(f.value)}
                  className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
                    format === f.value ? "bg-ink text-white" : "text-ink-soft hover:text-ink"
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>

          <button
            type="button"
            onClick={() => input.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              upload(e.dataTransfer.files);
            }}
            className={`flex w-full flex-col items-center justify-center rounded-xl border-2 border-dashed px-4 py-10 text-center transition ${
              dragging ? "border-clay bg-clay-light" : "border-ink/20 hover:border-clay"
            }`}
          >
            <span className="text-base font-semibold text-ink">Drop scans here or click to upload</span>
            <span className="mt-1 text-sm text-ink-soft">PDF, JPG, PNG or TIFF · up to 25 MB · several files at once</span>
            <span className="mt-2 text-xs text-ink-soft">Your files are deleted automatically after 24 hours.</span>
          </button>
          <input
            ref={input}
            type="file"
            accept={ACCEPT}
            multiple
            hidden
            onChange={(e) => e.target.files && upload(e.target.files)}
          />

          {jobs.length > 0 && (
            <>
              {session && <h3 className="mt-5 text-sm font-semibold text-ink">Your conversions</h3>}
              <ul className="mt-2 divide-y divide-ink/10">
                {jobs.map((job) => (
                  <li key={job.key} className="flex flex-wrap items-center justify-between gap-2 py-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-ink">{job.filename}</p>
                      <p className="text-xs text-ink-soft">
                        {job.status === "done" ? (
                          `${label(job.doc_type)} · ${job.pages} page(s) · ${job.tables} table(s) · ${job.images} image(s)`
                        ) : job.status === "failed" ? (
                          <span className="text-red-700">{job.error}</span>
                        ) : job.status === "uploading" ? (
                          "Uploading…"
                        ) : (
                          "Converting…"
                        )}
                      </p>
                    </div>
                    {job.status === "done" && (
                      <button
                        onClick={() => download(job).catch(failDownload(job))}
                        className="rounded-lg bg-clay px-3 py-1.5 text-sm font-semibold text-white hover:bg-clay/90"
                      >
                        Download .{job.output_format}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </div>
  );
}
