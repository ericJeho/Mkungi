"use client";

import { useCallback, useRef, useState } from "react";

const API = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const ACCEPT = ".png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.pdf";
const MAX_MB = 25;

type Format = "auto" | "docx" | "xlsx";

type Job = {
  /** Client-side key; the server id arrives once the job is created. */
  key: string;
  id?: string;
  status: "uploading" | "processing" | "done" | "failed";
  filename: string;
  output_format?: "docx" | "xlsx";
  doc_type?: string;
  pages?: number;
  tables?: number;
  images?: number;
  error?: string;
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

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
  return body as T;
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

  const target = job.upload.url.startsWith("/") ? `${API}${job.upload.url}` : job.upload.url;
  const put = await fetch(target, { method: job.upload.method, headers: job.upload.headers, body: file });
  if (!put.ok) throw new Error(`Upload failed (${put.status})`);

  update({ status: "processing" });
  return api<Job>(`/v1/conversions/${job.id}/process`, { method: "POST" });
}

export default function Converter() {
  const [format, setFormat] = useState<Format>("auto");
  const [dragging, setDragging] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]);
  const input = useRef<HTMLInputElement>(null);

  const upload = useCallback(
    (files: FileList | File[]) => {
      for (const file of Array.from(files)) {
        const key = crypto.randomUUID();
        const update = (patch: Partial<Job>) =>
          setJobs((prev) => prev.map((j) => (j.key === key ? { ...j, ...patch } : j)));
        setJobs((prev) => [{ key, filename: file.name, status: "uploading" }, ...prev]);
        convertFile(file, format, update)
          .then((done) => update({ ...done, key }))
          .catch((e) => update({ status: "failed", error: e instanceof Error ? e.message : "Conversion failed" }));
      }
    },
    [format],
  );

  return (
    <div className="rounded-2xl border border-ink/10 bg-white p-5 shadow-sm sm:p-6">
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
        <ul className="mt-5 divide-y divide-ink/10">
          {jobs.map((job) => (
            <li key={job.key} className="flex flex-wrap items-center justify-between gap-2 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-ink">{job.filename}</p>
                <p className="text-xs text-ink-soft">
                  {job.status === "done"
                    ? `${label(job.doc_type)} · ${job.pages} page(s) · ${job.tables} table(s) · ${job.images} image(s)`
                    : job.status === "failed"
                      ? <span className="text-red-700">{job.error}</span>
                      : job.status === "uploading" ? "Uploading…" : "Converting…"}
                </p>
              </div>
              {job.status === "done" && (
                <a
                  href={`${API}/v1/conversions/${job.id}/download`}
                  className="rounded-lg bg-clay px-3 py-1.5 text-sm font-semibold text-white hover:bg-clay/90"
                >
                  Download .{job.output_format}
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
