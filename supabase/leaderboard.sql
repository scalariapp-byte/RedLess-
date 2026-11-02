-- =====================================================================
-- Redless : classement en ligne du score total (Supabase / Postgres)
-- À coller tel quel dans Supabase → SQL Editor → Run. Ré-exécutable.
--
-- Principe :
--   * Le téléphone calcule lui-même le score total du joueur (somme de
--     tous les scores de ses parties, « points de carrière »).
--   * Il lit sa ligne sur le classement (board_me). Si son total local est
--     plus haut, il l'envoie (board_submit). Sinon il n'envoie rien.
--   * Une ligne par téléphone. Le téléphone est reconnu par un secret
--     aléatoire tiré au premier lancement ; le serveur n'en garde que
--     l'empreinte SHA-256, et le classement ne l'affiche jamais.
--   * Pas de compte Supabase à activer : seule la clé publique (anon)
--     est utilisée. La table est fermée, tout passe par les 3 fonctions.
-- =====================================================================

create extension if not exists pgcrypto with schema extensions;

create table if not exists public.board (
  id bigint generated always as identity primary key,
  secret_hash bytea not null unique,
  name text not null check (name ~ '^[A-Za-z0-9À-ÖØ-öø-ÿ _.-]{2,14}$'),
  total bigint not null default 0 check (total >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists board_rank on public.board (total desc, updated_at asc);

alter table public.board enable row level security;
revoke all on public.board from anon, authenticated;

create or replace function public.board_hash(p_secret uuid)
returns bytea language sql immutable set search_path = public, extensions as $$
  select extensions.digest(p_secret::text, 'sha256')
$$;
revoke all on function public.board_hash(uuid) from public, anon, authenticated;

-- Ligne du téléphone qui demande : son total, son pseudo et son rang (rien s'il n'a jamais envoyé).
create or replace function public.board_me(p_secret uuid)
returns table (name text, total bigint, rank bigint, players bigint)
language sql stable security definer set search_path = public as $$
  select b.name, b.total,
         1 + (select count(*) from board o where o.total > b.total
                or (o.total = b.total and o.updated_at < b.updated_at)),
         (select count(*) from board)
  from board b where b.secret_hash = board_hash(p_secret)
$$;

-- Envoi du total. Le serveur ne baisse jamais un total : il garde le plus haut des deux.
-- Le pseudo, lui, est toujours remplacé par celui envoyé.
create or replace function public.board_submit(p_secret uuid, p_name text, p_total bigint)
returns table (name text, total bigint, rank bigint, players bigint)
language plpgsql volatile security definer set search_path = public as $$
declare
  clean_name text := btrim(coalesce(p_name, ''));
begin
  if p_secret is null then raise exception 'appareil inconnu'; end if;
  if p_total is null or p_total < 0 or p_total > 1000000000 then raise exception 'score invalide'; end if;
  begin
    insert into board as b (secret_hash, name, total)
      values (board_hash(p_secret), clean_name, p_total)
      on conflict (secret_hash) do update
        set name = excluded.name,
            total = greatest(b.total, excluded.total),
            updated_at = case when excluded.total > b.total then now() else b.updated_at end;
  exception
    when check_violation then raise exception 'pseudo invalide (2 à 14 lettres, chiffres, espace, . _ -)';
  end;
  return query select * from board_me(p_secret);
end $$;

-- Top p_limit (200 au plus). is_me marque la ligne du téléphone qui demande,
-- ajoutée en bas si elle est hors du top.
create or replace function public.board_top(p_secret uuid default null, p_limit int default 100)
returns table (rank bigint, name text, total bigint, is_me boolean)
language sql stable security definer set search_path = public as $$
  with ranked as (
    select row_number() over (order by b.total desc, b.updated_at asc) as rank,
           b.name, b.total, (p_secret is not null and b.secret_hash = board_hash(p_secret)) as is_me
    from board b
  )
  select * from ranked
  where rank <= least(greatest(coalesce(p_limit, 100), 1), 200) or is_me
  order by rank
$$;

revoke all on function public.board_me(uuid) from public;
revoke all on function public.board_submit(uuid, text, bigint) from public;
revoke all on function public.board_top(uuid, int) from public;
grant execute on function public.board_me(uuid) to anon, authenticated;
grant execute on function public.board_submit(uuid, text, bigint) to anon, authenticated;
grant execute on function public.board_top(uuid, int) to anon, authenticated;
