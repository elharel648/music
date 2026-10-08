-- Alma beta: applications, approvals, license keys, feedback, releases.
-- Run once in Supabase › SQL Editor. Safe to re-run.

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  name text,
  about text,
  link text,
  applied_at timestamptz,
  approved boolean not null default false,
  approved_at timestamptz,
  founding boolean not null default true,          -- first fifty: free for good
  key text,                                        -- the ALMA-… license, issued once by the edge function
  key_issued_at timestamptz,
  created_at timestamptz not null default now()
);
alter table public.profiles enable row level security;
drop policy if exists "own profile read" on public.profiles;
create policy "own profile read" on public.profiles for select using (auth.uid() = id);
drop policy if exists "own profile write" on public.profiles;
create policy "own profile write" on public.profiles for insert with check (auth.uid() = id);
drop policy if exists "own profile update" on public.profiles;
create policy "own profile update" on public.profiles for update using (auth.uid() = id)
  with check (auth.uid() = id and approved = (select approved from public.profiles p where p.id = auth.uid()) and key is not distinct from (select key from public.profiles p where p.id = auth.uid()));
-- a user can edit their application but never flip approved or write a key

create or replace function public.handle_new_user() returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, email) values (new.id, new.email) on conflict (id) do nothing;
  return new;
end $$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users for each row execute function public.handle_new_user();

-- Feedback from inside the app. Insert-only for the anon key; only the dashboard (service role) reads it.
create table if not exists public.feedback (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  version text generated always as ((payload->>'version')) stored,
  email text generated always as ((payload->>'email')) stored,
  note text generated always as ((payload->>'note')) stored,
  payload jsonb not null
);
alter table public.feedback enable row level security;
drop policy if exists "anyone can insert feedback" on public.feedback;
create policy "anyone can insert feedback" on public.feedback for insert to anon, authenticated with check (true);

-- Releases: one row per uploaded build in the private 'releases' bucket.
create table if not exists public.releases (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  version text not null,
  platform text not null default 'mac',
  path text not null                                -- object path inside the 'releases' bucket, e.g. Alma-0.8.0-mac.dmg
);
alter table public.releases enable row level security;   -- no policies: only the service role (edge function) reads it

-- Storage: a private bucket. Create it in Storage › New bucket › "releases", Public: OFF. Upload the DMG there.
insert into storage.buckets (id, name, public) values ('releases', 'releases', false) on conflict (id) do nothing;
