-- Mkungi: conversion jobs and the private buckets that hold their files.
--
-- Only the API touches these, using the project's secret key (which bypasses
-- row-level security). RLS is on with no policies, so the publishable/anon key
-- cannot read or write anything here. Browsers upload through signed URLs
-- minted by the API, which need no storage policies either.

create table public.conversions (
  id               uuid primary key,
  status           text not null default 'awaiting_upload'
                   check (status in ('awaiting_upload', 'processing', 'done', 'failed')),
  filename         text not null,
  requested_format text not null default 'auto' check (requested_format in ('auto', 'docx', 'xlsx')),
  input_path       text not null,
  output_format    text check (output_format in ('docx', 'xlsx')),
  output_file      text,
  output_path      text,
  doc_type         text,
  pages            integer,
  tables           integer,
  images           integer,
  error            text,
  created_at       timestamptz not null default now(),
  finished_at      timestamptz
);

comment on table public.conversions is 'One row per scan-to-Word/Excel conversion.';

create index conversions_created_at_idx on public.conversions (created_at desc);

alter table public.conversions enable row level security;
revoke all on table public.conversions from anon, authenticated;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
  ('uploads', 'uploads', false, 26214400, array[
    'application/pdf', 'image/png', 'image/jpeg', 'image/tiff', 'image/bmp', 'image/webp'
  ]),
  ('outputs', 'outputs', false, 52428800, array[
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
  ])
on conflict (id) do nothing;
