-- =====================================================================
-- Redlok : classement mondial et événement mensuel (Supabase / Postgres)
-- À coller tel quel dans Supabase → SQL Editor → Run. Ré-exécutable.
--
-- Règles :
--   * Chaque joueur est un utilisateur anonyme Supabase. Il peut, s'il le
--     veut, lier une adresse e-mail pour retrouver son compte (code par e-mail).
--   * L'événement démarre 7 jours après l'inscription du 30e joueur.
--   * Pendant l'événement, le classement repart de zéro chaque mois
--     (saison 1 = 1er mois après le début, saison 2 = mois suivant…).
--   * Avant l'événement : « pré-saison » (saison 0), déjà classée.
--   * Le classement de l'événement est celui du mode Classique ;
--     les autres modes ont aussi leur classement mensuel.
--   * Les tables ne sont pas accessibles directement : tout passe par
--     les fonctions ci-dessous, qui vérifient la vraisemblance des scores.
-- =====================================================================

-- ---------- réglages ----------
create or replace function public.redless_settings()
returns table (players_needed int, delay interval, modes text[])
language sql immutable as $$
  select 30, interval '7 days',
         array['classic','chrono','sudden','feint','expansion','rhythm','mirror','chaos']::text[]
$$;

-- ---------- tables ----------
create table if not exists public.players (
  id uuid primary key references auth.users (id) on delete cascade,
  name text not null check (name ~ '^[A-Za-z0-9À-ÖØ-öø-ÿ _.-]{2,14}$'),
  created_at timestamptz not null default now(),
  last_submit_at timestamptz
);
create unique index if not exists players_name_unique on public.players (lower(name));

create table if not exists public.best_scores (
  player_id uuid not null references public.players (id) on delete cascade,
  mode text not null,
  season int not null,
  score int not null check (score >= 0),
  level int not null,
  bpm int not null,
  updated_at timestamptz not null default now(),
  primary key (player_id, mode, season)
);
create index if not exists best_scores_board on public.best_scores (mode, season, score desc, updated_at);

create table if not exists public.runs (
  id bigint generated always as identity primary key,
  player_id uuid not null references public.players (id) on delete cascade,
  mode text not null,
  season int not null,
  score int not null,
  level int not null,
  bpm int not null,
  duration_ms int not null,
  created_at timestamptz not null default now()
);

create table if not exists public.app_state (
  key text primary key,
  value timestamptz
);

-- Nobody reads or writes the tables directly: only the functions below.
alter table public.players enable row level security;
alter table public.best_scores enable row level security;
alter table public.runs enable row level security;
alter table public.app_state enable row level security;
revoke all on public.players, public.best_scores, public.runs, public.app_state from anon, authenticated;

-- ---------- état de l'événement ----------
-- season 0 = pré-saison ; season n >= 1 = n-ième mois de l'événement.
create or replace function public.event_info()
returns table (
  players int, players_needed int, threshold_at timestamptz, event_start timestamptz,
  season int, season_start timestamptz, season_end timestamptz, server_now timestamptz
)
language plpgsql stable security definer set search_path = public as $$
#variable_conflict use_column
declare
  cfg record;
  t timestamptz;
  st timestamptz;
  n int;
begin
  select * into cfg from redless_settings();
  select value into t from app_state where key = 'threshold_reached_at';
  st := t + cfg.delay;
  players := (select count(*) from public.players)::int;
  players_needed := cfg.players_needed;
  threshold_at := t;
  event_start := st;
  server_now := now();
  if st is null or now() < st then
    season := 0; season_start := null; season_end := st;
  else
    n := (date_part('year', age(now(), st)) * 12 + date_part('month', age(now(), st)))::int;
    season := n + 1;
    season_start := st + make_interval(months => n);
    season_end := st + make_interval(months => n + 1);
  end if;
  return next;
end $$;

-- ---------- envoi d'un score ----------
create or replace function public.submit_score(
  p_mode text, p_score int, p_level int, p_bpm int, p_duration_ms int, p_name text default null
)
returns table (season int, best int, rank int, players int)
language plpgsql volatile security definer set search_path = public as $$
#variable_conflict use_column
declare
  uid uuid := auth.uid();
  cfg record;
  me public.players%rowtype;
  s int;
  clean_name text := nullif(btrim(coalesce(p_name, '')), '');
begin
  if uid is null then raise exception 'non connecté' using errcode = '28000'; end if;
  select * into cfg from redless_settings();
  if not (p_mode = any (cfg.modes)) then raise exception 'mode inconnu'; end if;
  if p_score is null or p_score < 0 or p_score > 100000 then raise exception 'score invalide'; end if;
  if p_level is null or p_level < 1 or p_level > 300 then raise exception 'niveau invalide'; end if;
  if p_bpm is null or p_bpm < 40 or p_bpm > 260 then raise exception 'tempo invalide'; end if;
  if p_duration_ms is null or p_duration_ms < 3000 or p_duration_ms > 7200000 then raise exception 'durée invalide'; end if;
  -- Plausibility: even a perfect player cannot score faster than ~40 points per second
  -- (the tempo has no ceiling: past the music's limit, tiles also fall between the beats).
  if p_score > p_duration_ms / 1000.0 * 40 + 60 then raise exception 'score invraisemblable'; end if;

  select * into me from public.players where id = uid for update;
  if not found then
    if clean_name is null then raise exception 'pseudo requis'; end if;
    begin
      insert into public.players (id, name) values (uid, clean_name) returning * into me;
    exception
      when unique_violation then raise exception 'pseudo déjà pris';
      when check_violation then raise exception 'pseudo invalide (2 à 14 lettres, chiffres, espace, . _ -)';
    end;
    -- 30th player: start the 7-day countdown (only once).
    if (select count(*) from public.players) >= cfg.players_needed then
      insert into app_state (key, value) values ('threshold_reached_at', now()) on conflict (key) do nothing;
    end if;
  elsif clean_name is not null and clean_name <> me.name then
    begin
      update public.players set name = clean_name where id = uid;
    exception
      when unique_violation then raise exception 'pseudo déjà pris';
      when check_violation then raise exception 'pseudo invalide (2 à 14 lettres, chiffres, espace, . _ -)';
    end;
  end if;
  if me.last_submit_at is not null and me.last_submit_at > now() - interval '5 seconds' then
    raise exception 'trop rapide';
  end if;
  update public.players set last_submit_at = now() where id = uid;

  s := (select e.season from event_info() e);
  insert into public.runs (player_id, mode, season, score, level, bpm, duration_ms)
    values (uid, p_mode, s, p_score, p_level, p_bpm, p_duration_ms);
  insert into public.best_scores as b (player_id, mode, season, score, level, bpm)
    values (uid, p_mode, s, p_score, p_level, p_bpm)
    on conflict (player_id, mode, season) do update
      set score = excluded.score, level = excluded.level, bpm = excluded.bpm, updated_at = now()
      where excluded.score > b.score;

  season := s;
  best := (select b.score from public.best_scores b where b.player_id = uid and b.mode = p_mode and b.season = s);
  rank := 1 + (select count(*) from public.best_scores b where b.mode = p_mode and b.season = s and b.score > best)::int;
  players := (select count(*) from public.players)::int;
  return next;
end $$;

-- ---------- changement de pseudo ----------
create or replace function public.set_name(p_name text)
returns void language plpgsql volatile security definer set search_path = public as $$
begin
  if auth.uid() is null then raise exception 'non connecté' using errcode = '28000'; end if;
  update public.players set name = btrim(p_name) where id = auth.uid();
exception
  when unique_violation then raise exception 'pseudo déjà pris';
  when check_violation then raise exception 'pseudo invalide (2 à 14 lettres, chiffres, espace, . _ -)';
end $$;

-- Pseudo libre ? Vérifié dès la création du compte (écran Connexion), avant le premier score.
-- Le pseudo du joueur qui demande compte comme libre. Rien n'est réservé : seul submit_score l'enregistre.
create or replace function public.name_available(p_name text)
returns boolean language sql stable security definer set search_path = public as $$
  select not exists (
    select 1 from public.players p
    where lower(p.name) = lower(btrim(p_name)) and p.id is distinct from auth.uid()
  )
$$;
grant execute on function public.name_available(text) to anon, authenticated;

-- Nombre de personnes venues : un compte (anonyme ou protégé) est créé automatiquement
-- par appareil au premier lancement en ligne. Affiché sur le menu du jeu.
create or replace function public.visitor_count()
returns bigint language sql stable security definer set search_path = public, auth as $$
  select count(*) from auth.users
$$;
revoke all on function public.visitor_count() from public;
grant execute on function public.visitor_count() to anon, authenticated;

-- ---------- classement ----------
-- Top p_limit de la saison demandée (par défaut la saison en cours), plus la ligne du joueur
-- qui appelle s'il est plus bas.
create or replace function public.get_leaderboard(p_mode text, p_season int default null, p_limit int default 50)
returns table (rank bigint, name text, score int, level int, bpm int, is_me boolean)
language sql stable security definer set search_path = public as $$
  with s as (select coalesce(p_season, (select e.season from event_info() e)) as season),
  ranked as (
    select rank() over (order by b.score desc, b.updated_at asc) as rank,
           p.name, b.score, b.level, b.bpm, (b.player_id = auth.uid()) as is_me
    from public.best_scores b
    join public.players p on p.id = b.player_id, s
    where b.mode = p_mode and b.season = s.season
  )
  select * from ranked where rank <= least(greatest(coalesce(p_limit, 50), 1), 200) or is_me
  order by rank
$$;

-- ---------- accès ----------
revoke all on function public.submit_score(text, int, int, int, int, text) from public;
revoke all on function public.set_name(text) from public;
grant execute on function public.event_info() to anon, authenticated;
grant execute on function public.get_leaderboard(text, int, int) to anon, authenticated;
grant execute on function public.submit_score(text, int, int, int, int, text) to authenticated;
grant execute on function public.set_name(text) to authenticated;
grant execute on function public.redless_settings() to anon, authenticated;

-- =====================================================================
-- Installations : un e-mail au propriétaire à chaque nouvelle installation
-- (premier lancement de l'APK, ou de l'appli installée depuis Safari / Chrome).
-- Envoi par Resend (https://resend.com) via pg_net. Clé Resend rangée dans le
-- coffre Supabase (Vault) : voir supabase/README.md, section « E-mail ».
-- =====================================================================
create extension if not exists pg_net with schema extensions;

create or replace function public.redless_install_settings()
returns table (notify_email text, max_mails_per_hour int)
language sql immutable as $$ select 'scalariapp@gmail.com', 30 $$;

create table if not exists public.installs (
  id bigint generated always as identity primary key,
  device_id uuid not null unique,
  platform text not null check (platform in ('android', 'ios', 'web-app')),
  version text,
  created_at timestamptz not null default now()
);
alter table public.installs enable row level security;
revoke all on public.installs from anon, authenticated;

-- Called once per device at first launch. No account needed.
-- Same device twice = ignored. Above the hourly cap, installs are still counted but not mailed.
create or replace function public.register_install(p_device uuid, p_platform text, p_version text default null)
returns boolean
language plpgsql volatile security definer set search_path = public, extensions as $$
declare
  cfg record;
  total int;
  recent int;
  api_key text;
begin
  if p_device is null or p_platform not in ('android', 'ios', 'web-app') then raise exception 'installation invalide'; end if;
  insert into public.installs (device_id, platform, version)
    values (p_device, p_platform, left(coalesce(p_version, ''), 20))
    on conflict (device_id) do nothing;
  if not found then return false; end if;

  select * into cfg from redless_install_settings();
  total := (select count(*) from public.installs)::int;
  recent := (select count(*) from public.installs where created_at > now() - interval '1 hour')::int;
  if recent > cfg.max_mails_per_hour then return true; end if;

  select decrypted_secret into api_key from vault.decrypted_secrets where name = 'resend_api_key' limit 1;
  if api_key is null then return true; end if; -- e-mail not configured yet: install still counted

  perform net.http_post(
    url := 'https://api.resend.com/emails',
    headers := jsonb_build_object('Authorization', 'Bearer ' || api_key, 'Content-Type', 'application/json'),
    body := jsonb_build_object(
      'from', 'Redlok <onboarding@resend.dev>',
      'to', jsonb_build_array(cfg.notify_email),
      'subject', format('Redlok : nouvelle installation (%s au total)', total),
      'text', format(E'Une personne vient d''installer Redlok.\n\nPlateforme : %s\nVersion : %s\nDate : %s (UTC)\nInstallations au total : %s\n\n— Supabase, projet Redlok',
                     case p_platform when 'android' then 'Android (APK)' when 'ios' then 'iPhone / iPad (appli web)' else 'Appli web installée' end,
                     coalesce(nullif(p_version, ''), '?'),
                     to_char(now() at time zone 'UTC', 'DD/MM/YYYY HH24:MI'),
                     total)
    )
  );
  return true;
end $$;

revoke all on function public.register_install(uuid, text, text) from public;
grant execute on function public.register_install(uuid, text, text) to anon, authenticated;

-- =====================================================================
-- Comptes protégés par e-mail : sauvegarde en ligne de la progression
-- (crédits, achats, records, missions…). Seuls les comptes liés à une
-- adresse e-mail peuvent sauvegarder : un compte anonyme ne pourrait
-- de toute façon pas être retrouvé. Voir supabase/README.md, « Comptes ».
-- =====================================================================
create table if not exists public.saves (
  user_id uuid primary key references auth.users (id) on delete cascade,
  data jsonb not null,
  updated_at timestamptz not null default now()
);
alter table public.saves enable row level security;
revoke all on public.saves from anon, authenticated;

create or replace function public.save_progress(p_data jsonb)
returns timestamptz
language plpgsql security definer set search_path = public as $$
declare
  uid uuid := auth.uid();
  t timestamptz := now();
begin
  if uid is null then raise exception 'Connexion requise'; end if;
  if coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false) then
    raise exception 'Protège d''abord ton compte avec ton adresse e-mail';
  end if;
  if p_data is null or jsonb_typeof(p_data) <> 'object' or octet_length(p_data::text) > 200000 then
    raise exception 'Sauvegarde invalide';
  end if;
  insert into saves (user_id, data, updated_at) values (uid, p_data, t)
  on conflict (user_id) do update set data = excluded.data, updated_at = t;
  return t;
end $$;

create or replace function public.load_progress()
returns table (data jsonb, updated_at timestamptz)
language sql stable security definer set search_path = public as $$
  select s.data, s.updated_at from saves s where s.user_id = auth.uid()
$$;

revoke all on function public.save_progress(jsonb) from public, anon;
revoke all on function public.load_progress() from public, anon;
grant execute on function public.save_progress(jsonb) to authenticated;
grant execute on function public.load_progress() to authenticated;

-- =====================================================================
-- Classement général : une ligne par joueur, total de ses meilleurs scores
-- de la saison dans tous les modes. La fiche d'un joueur détaille ses
-- meilleurs scores mode par mode (Classique, Chrono, Mort subite…).
-- =====================================================================
create or replace function public.get_overall(p_season int default null, p_limit int default 100)
returns table (rank bigint, name text, total int, modes int, is_me boolean)
language sql stable security definer set search_path = public as $$
  with s as (select coalesce(p_season, (select e.season from event_info() e)) as season),
  per as (
    select b.player_id, sum(b.score)::int as total, count(*)::int as modes, max(b.updated_at) as last_at
    from public.best_scores b, s
    where b.season = s.season
    group by b.player_id
  ),
  ranked as (
    select rank() over (order by per.total desc, per.last_at asc) as rank,
           p.name, per.total, per.modes, (per.player_id = auth.uid()) as is_me
    from per join public.players p on p.id = per.player_id
  )
  select * from ranked where rank <= least(greatest(coalesce(p_limit, 100), 1), 200) or is_me
  order by rank
$$;

create or replace function public.get_profile(p_name text, p_season int default null)
returns table (mode text, score int, level int, bpm int, rank bigint, updated_at timestamptz)
language sql stable security definer set search_path = public as $$
  with s as (select coalesce(p_season, (select e.season from event_info() e)) as season),
  ranked as (
    select b.player_id, b.mode, b.score, b.level, b.bpm, b.updated_at,
           rank() over (partition by b.mode order by b.score desc, b.updated_at asc) as rank
    from public.best_scores b, s
    where b.season = s.season
  )
  select r.mode, r.score, r.level, r.bpm, r.rank, r.updated_at
  from ranked r join public.players p on p.id = r.player_id
  where lower(p.name) = lower(btrim(p_name))
  order by r.score desc
$$;

grant execute on function public.get_overall(int, int) to anon, authenticated;
grant execute on function public.get_profile(text, int) to anon, authenticated;
