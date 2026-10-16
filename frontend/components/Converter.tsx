"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const ACCEPT = ".png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.pdf";

type Format = "auto" | "docx" | "xlsx";

type Job = {
  id: string;
  status: "queued" | "processing" | "done" | "failed";
  filename: string;
  output_format?: "docx" | "xlsx";
  doc_type?: string;
  pages?: number;
  tables?: number;
  images?: number;
  error?: string;
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

export default function Converter() {
  const [format, setFormat] = useState<Format>("auto");
  const [dragging, setDragging] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const upload = useCallback(
    async (files: FileList | File[]) => {
      setError(null);
      for (const file of Array.from(files)) {
        const body = new FormData();
        body.append("file", file);
        body.append("output_format", format);
        try {
          const res = await fetch(`${API}/v1/conversions`, { method: "POST", body });
          if (!res.ok) {
            const detail = await res.json().catch(() => ({}));
            throw new Error(detail.detail ?? `Upload failed (${res.status})`);
          }
          const job: Job = await res.json();
          setJobs((prev) => [job, ...prev]);
        } catch (e) {
          setError(`${file.name}: ${e instanceof Error ? e.message : "upload failed"}`);
        }
      }
    },
    [format],
  );

  // Poll unfinished jobs.
  useEffect(() => {
    const pending = jobs.filter((j) => j.status === "queued" || j.status === "processing");
    if (!pending.length) return;
    const t = setTimeout(async () => {
      const updates = await Promise.all(
        pending.map((j) =>
          fetch(`${API}/v1/conversions/${j.id}`)
            .then((r) => r.json() as Promise<Job>)
            .catch(() => j),
        ),
      );
      setJobs((prev) => prev.map((j) => updates.find((u) => u.id === j.id) ?? j));
    }, 1000);
    return () => clearTimeout(t);
  }, [jobs]);

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
      </button>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        onChange={(e) => e.target.files && upload(e.target.files)}
      />

      {error && <p className="mt-3 text-sm text-red-700">{error}</p>}

      {jobs.length > 0 && (
        <ul className="mt-5 divide-y divide-ink/10">
          {jobs.map((job) => (
            <li key={job.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-ink">{job.filename}</p>
                <p className="text-xs text-ink-soft">
                  {job.status === "done"
                    ? `${label(job.doc_type)} · ${job.pages} page(s) · ${job.tables} table(s) · ${job.images} image(s)`
                    : job.status === "failed"
                      ? job.error
                      : job.status === "queued" ? "Queued…" : "Processing…"}
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
