-- Per-visitor rate limiting and retention clean-up.
--
-- client_hash is a salted SHA-256 of the visitor's IP (the IP itself is never
-- stored). The API counts a visitor's recent jobs with it, and the daily
-- clean-up finds old jobs by created_at (already indexed).

alter table public.conversions add column client_hash text;

create index conversions_client_hash_created_at_idx
  on public.conversions (client_hash, created_at desc)
  where client_hash is not null;
