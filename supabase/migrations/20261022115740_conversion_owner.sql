-- Sign-in: each conversion belongs to the Supabase Auth user who created it.
--
-- The API (secret key) enforces ownership on every request. "on delete set
-- null" keeps the row when an account is deleted, so the daily clean-up still
-- finds it and removes its files from Storage (a cascade would drop the row and
-- orphan the files).

alter table public.conversions
  add column user_id uuid references auth.users (id) on delete set null;

create index conversions_user_id_created_at_idx
  on public.conversions (user_id, created_at desc)
  where user_id is not null;
