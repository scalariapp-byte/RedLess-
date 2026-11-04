# Connecte Redlok à Supabase : colle l'adresse du projet et la clé publique,
# le script vérifie tout et écrit js/online-config.js (la config livrée à tous les joueurs).
# Lancement : double-clic sur connecter-supabase.cmd (à la racine du projet).
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$racine = Split-Path $PSScriptRoot
$fichier = Join-Path $racine 'js\online-config.js'
$schema = Join-Path $racine 'supabase\schema.sql'

function Ok($t) { Write-Host "  [OK] $t" -ForegroundColor Green }
function Ko($t, $aide) {
    Write-Host "  [X]  $t" -ForegroundColor Red
    if ($aide) { Write-Host "       $aide" -ForegroundColor Yellow }
}
function Role-Jwt($j) {
    try {
        $p = $j.Split('.')[1].Replace('-', '+').Replace('_', '/')
        while ($p.Length % 4) { $p += '=' }
        ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($p)) | ConvertFrom-Json).role
    } catch { '' }
}

# Lit l'adresse et la clé dans n'importe quel texte collé (tableau de bord, .env, online-config.js…)
function Lire-Texte($t) {
    $r = @{ url = ''; key = ''; secret = $false }
    if ($t -match 'https://[a-z0-9-]+\.supabase\.(co|in)') { $r.url = $Matches[0].ToLower() }
    elseif ($t -match 'supabase\.com/dashboard/project/([a-z0-9]{20})') { $r.url = "https://$($Matches[1].ToLower()).supabase.co" }
    elseif ($t -match '^\s*([a-z0-9]{20})\s*$') { $r.url = "https://$($Matches[1].ToLower()).supabase.co" }
    elseif ($t -match 'https://[^\s"''`,;]+') { $r.url = $Matches[0].TrimEnd('/') }
    if ($t -match 'sb_secret_') { $r.secret = $true }
    if ($t -match 'sb_publishable_[A-Za-z0-9_-]+') { $r.key = $Matches[0] }
    foreach ($m in [regex]::Matches($t, 'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')) {
        $role = Role-Jwt $m.Value
        if ($role -eq 'service_role') { $r.secret = $true }
        if ($role -eq 'anon' -and -not $r.key) { $r.key = $m.Value }
    }
    $r
}

function Appel($url, $key, $chemin, $methode) {
    $h = @{ apikey = $key }
    try {
        if ($methode -eq 'GET') { $rep = Invoke-WebRequest "$url$chemin" -Headers $h -UseBasicParsing -TimeoutSec 15 }
        else { $rep = Invoke-WebRequest "$url$chemin" -Method Post -Headers $h -ContentType 'application/json' -Body '{}' -UseBasicParsing -TimeoutSec 15 }
        @{ ok = $true; data = ($rep.Content | ConvertFrom-Json) }
    } catch {
        $code = 0; $texte = ''
        if ($_.Exception.Response) {
            $code = [int]$_.Exception.Response.StatusCode
            try { $texte = (New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd() } catch {}
        }
        @{ ok = $false; code = $code; texte = $texte }
    }
}

function Tester($url, $key) {
    if ($url -notmatch '^https://[^/\s]+$') { Ko "Adresse inattendue : $url" 'Elle doit ressembler à https://xxxx.supabase.co'; return $false }
    if (-not $key) { Ko 'Clé publique manquante' 'Project Settings -> API Keys -> clé « publishable » (ou « anon »).'; return $false }
    Ok 'Adresse et clé bien formées'

    $r = Appel $url $key '/auth/v1/settings' 'GET'
    if (-not $r.ok) {
        if ($r.code -eq 0) { Ko 'Serveur injoignable' 'Vérifie l''adresse. Projet en pause (inactif 7 jours) ? Ouvre-le sur supabase.com et touche « Restore ».' }
        elseif ($r.code -eq 401 -or $r.texte -match 'API key') { Ko 'Clé refusée par le serveur' 'Recopie la clé publishable de CE projet (elle a peut-être été régénérée).' }
        else { Ko "Réponse inattendue du serveur ($($r.code))" 'Vérifie l''adresse du projet.' }
        return $false
    }
    Ok 'Serveur joint, clé acceptée'
    if ($r.data.external.anonymous_users -eq $false) {
        Ko 'Connexion anonyme désactivée' 'Authentication -> Sign In / Providers -> active « Allow anonymous sign-ins » -> Save.'
        return $false
    }
    Ok 'Connexion anonyme des joueurs autorisée'

    $r = Appel $url $key '/rest/v1/rpc/event_info' 'POST'
    if (-not $r.ok) {
        if ($r.code -eq 404 -or $r.texte -match 'PGRST202') {
            Ko 'Tables du classement absentes' 'SQL Editor -> New query -> colle supabase/schema.sql -> Run.'
            $rep = Read-Host '       Copier schema.sql dans le presse-papier maintenant ? (o/n)'
            if ($rep -match '^[oOyY]') { Get-Content $schema -Raw -Encoding UTF8 | Set-Clipboard; Write-Host '       Copié : colle-le dans le SQL Editor puis relance ce script.' -ForegroundColor Cyan }
        } else { Ko "Erreur des tables ($($r.code))" 'Relance supabase/schema.sql dans le SQL Editor.' }
        return $false
    }
    $n = @($r.data)[0].players
    Ok "Tables du classement installées ($n joueur(s))"
    return $true
}

Write-Host ''
Write-Host '=== Connecter Redlok à Supabase ===' -ForegroundColor Cyan
$actuel = ''
if (Test-Path $fichier) { $actuel = Get-Content $fichier -Raw -Encoding UTF8 }
$cfg = Lire-Texte $actuel
if ($cfg.url) {
    Write-Host "Config actuelle : $($cfg.url)"
    Tester $cfg.url $cfg.key | Out-Null
    Write-Host ''
}

Write-Host 'Supabase -> Project Settings -> API : copie le « Project URL » et la clé « publishable ».'
Write-Host 'Colle-les ici (les deux sur une ligne, ou l''un après l''autre). Entrée vide = quitter.'
$texte = ''
while ($true) {
    $ligne = Read-Host '>'
    if (-not $ligne) { break }
    $texte += " $ligne"
    $c = Lire-Texte $texte
    if ($c.secret) { Ko 'Clé SECRÈTE détectée : elle ne doit JAMAIS aller dans le jeu.' 'Prends la clé « publishable » (sb_publishable_…) ou « anon ».'; $texte = $texte -replace 'sb_secret_\S+', '' }
    if ($c.url -and $c.key) { break }
    if ($c.url) { Write-Host '  Adresse lue. Colle maintenant la clé :' } elseif ($c.key) { Write-Host '  Clé lue. Colle maintenant l''adresse :' }
}
$c = Lire-Texte $texte
if (-not ($c.url -and $c.key)) { Write-Host 'Rien de changé.'; Read-Host 'Entrée pour fermer' | Out-Null; exit }

Write-Host ''
if (Tester $c.url $c.key) {
    $js = @"
// Classement mondial (Supabase). URL du projet + clé PUBLIQUE uniquement (jamais la clé secrète).
window.REDLESS_ONLINE = {
  url: "$($c.url)",
  key: "$($c.key)",
};
"@
    [IO.File]::WriteAllText($fichier, $js.Replace("`r`n", "`n"), (New-Object Text.UTF8Encoding $false))
    Write-Host ''
    Write-Host 'C''est connecté ! js/online-config.js est à jour.' -ForegroundColor Green
    Write-Host 'Il reste à publier : pousse sur GitHub (Vercel + APK se refont tout seuls).'
} else {
    Write-Host ''
    Write-Host 'Pas enregistré : corrige le point en rouge, puis relance.' -ForegroundColor Yellow
}
Read-Host 'Entrée pour fermer' | Out-Null
