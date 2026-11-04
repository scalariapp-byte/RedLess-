-- =====================================================================
-- Redlok : statistiques de fréquentation (lecture seule).
-- Supabase → SQL Editor → colle UNE requête à la fois → Run.
-- Aucune donnée nouvelle n'est collectée : tout vient des tables déjà
-- remplies par le jeu (installs, players, runs, saves, auth.users).
-- « Joueur » = compte qui a envoyé au moins un score au classement
-- (parties classées : mode Facile et campagne exclus, voir js/game.js).
-- =====================================================================

-- 1. Vue d'ensemble
select
  (select count(*) from public.installs)                                         as installations,
  (select count(*) from public.players)                                          as joueurs_classes,
  (select count(*) from auth.users where email is not null)                      as comptes_avec_email,
  (select count(*) from public.saves)                                            as sauvegardes_en_ligne,
  (select count(*) from public.runs)                                             as parties_classees,
  (select count(distinct player_id) from public.runs where created_at > now() - interval '1 day')  as actifs_24h,
  (select count(distinct player_id) from public.runs where created_at > now() - interval '7 days') as actifs_7j;

-- 2. Par jour (30 derniers jours) : installations, nouveaux joueurs, joueurs actifs, parties
with days as (
  select generate_series(current_date - 29, current_date, interval '1 day')::date as jour
)
select d.jour,
  (select count(*) from public.installs i where i.created_at::date = d.jour)               as installations,
  (select count(*) from public.players p where p.created_at::date = d.jour)               as nouveaux_joueurs,
  (select count(distinct r.player_id) from public.runs r where r.created_at::date = d.jour) as joueurs_actifs,
  (select count(*) from public.runs r where r.created_at::date = d.jour)                  as parties
from days d
order by d.jour desc;

-- 3. Rétention : sur les joueurs arrivés une semaine donnée, combien rejouent
--    le lendemain (J1), entre J2 et J7 (S1) et entre J8 et J30 (M1).
--    Une semaine trop récente donne des chiffres incomplets (affichés vides).
with first_day as (
  select p.id, p.created_at::date as d0 from public.players p
),
back as (
  select f.id, f.d0,
    bool_or(r.created_at::date = f.d0 + 1)                                  as j1,
    bool_or(r.created_at::date between f.d0 + 2 and f.d0 + 7)               as s1,
    bool_or(r.created_at::date between f.d0 + 8 and f.d0 + 30)              as m1
  from first_day f left join public.runs r on r.player_id = f.id
  group by f.id, f.d0
)
select date_trunc('week', d0)::date as semaine,
  count(*)                                                                                      as nouveaux,
  case when max(d0) + 1  < current_date then round(100.0 * count(*) filter (where j1) / count(*)) end as "J1 %",
  case when max(d0) + 7  < current_date then round(100.0 * count(*) filter (where s1) / count(*)) end as "S1 %",
  case when max(d0) + 30 < current_date then round(100.0 * count(*) filter (where m1) / count(*)) end as "M1 %"
from back
group by 1
order by 1 desc;

-- 4. Modes joués (30 derniers jours) : parties, joueurs, score moyen et record
select mode, count(*) as parties, count(distinct player_id) as joueurs,
  round(avg(score)) as score_moyen, max(score) as record,
  round(avg(duration_ms) / 1000.0) as duree_moyenne_s
from public.runs
where created_at > now() - interval '30 days'
group by mode
order by parties desc;

-- 5. Installations par plateforme et par version
select platform, version, count(*) as installations, max(created_at)::date as derniere
from public.installs
group by platform, version
order by installations desc;

-- 6. Joueurs les plus assidus (30 derniers jours) : utile aussi pour repérer un tricheur
--    (beaucoup de parties très courtes avec de gros scores).
select p.name, count(*) as parties, max(r.score) as meilleur,
  round(avg(r.duration_ms) / 1000.0) as duree_moyenne_s,
  round(max(r.score / greatest(r.duration_ms / 1000.0, 1)), 1) as points_par_s_max
from public.runs r join public.players p on p.id = r.player_id
where r.created_at > now() - interval '30 days'
group by p.name
order by parties desc
limit 30;
