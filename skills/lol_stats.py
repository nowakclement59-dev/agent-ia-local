import os
import re
import requests
from urllib.parse import quote

SKILL_PROMPT = '- `{"action": "lol_stats", "region": "euw1", "summoner_name": "Pseudo#EUW", "count": 5}` (Skill Riot API Officielle : récupère le rang SoloQ/Flex, le Winrate, l\'historique des 5 derniers matchs et le KDA exact via Account-V1, Summoner-V4, League-V4 et Match-V5)'

# Table de routage officielle Riot Games (Platform -> Regional Routing)
PLATFORM_TO_REGIONAL = {
    "euw1": "europe", "euw": "europe",
    "eun1": "europe", "eune": "europe",
    "tr1": "europe",  "tr": "europe",
    "ru": "europe",
    "na1": "americas", "na": "americas",
    "br1": "americas", "br": "americas",
    "la1": "americas", "lan": "americas",
    "la2": "americas", "las": "americas",
    "kr": "asia",
    "jp1": "asia",     "jp": "asia",
    "oc1": "sea",      "oce": "sea",
    "ph2": "sea", "sg2": "sea", "th2": "sea", "tw2": "sea", "vn2": "sea"
}

PLATFORM_NORMALIZE = {
    "euw": "euw1", "eune": "eun1", "na": "na1", "br": "br1",
    "kr": "kr", "jp": "jp1", "tr": "tr1", "ru": "ru", "oce": "oc1"
}

DEFAULT_TAG_BY_PLATFORM = {
    "euw1": "EUW", "eun1": "EUNE", "na1": "NA1", "kr": "KR1",
    "br1": "BR1", "jp1": "JP1", "tr1": "TR1", "oc1": "OCE"
}

def _fallback_opgg(platform: str, game_name: str, tag_line: str, reason: str) -> tuple[str, bool]:
    opgg_region_map = {"euw1": "euw", "eun1": "eune", "na1": "na", "br1": "br", "kr": "kr", "jp1": "jp", "tr1": "tr", "oc1": "oce"}
    opgg_reg = opgg_region_map.get(platform, "euw")
    formatted = quote(f"{game_name}-{tag_line}")
    url = f"https://www.op.gg/summoners/{opgg_reg}/{formatted}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    try:
        r = requests.get(url, headers=headers, timeout=12)
        title_m = re.search(r"<title>(.*?)</title>", r.text, re.IGNORECASE | re.DOTALL)
        desc_m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', r.text, re.IGNORECASE)
        title_txt = title_m.group(1).strip() if title_m else "Profil OP.GG"
        desc_txt = desc_m.group(1).strip() if desc_m else "Pas de description disponible."
        return (
            f"⚠️ [Fallback OP.GG activé — Raison : {reason}]\n"
            f"Joueur : {game_name}#{tag_line} ({opgg_reg.upper()})\n"
            f"URL    : {url}\n"
            f"Titre  : {title_txt}\n"
            f"Résumé : {desc_txt}"
        ), False
    except Exception as e:
        return f"❌ Échec Riot API ({reason}) et échec Fallback OP.GG : {e}", True

def execute(data: dict) -> tuple[str, bool]:
    # 1. Extraction souple des paramètres (supporte region/summoner_name ou query)
    raw_region = (data.get("region") or "euw1").lower().strip()
    summoner_input = (data.get("summoner_name") or data.get("query") or "").strip()
    match_count = max(1, min(10, int(data.get("count") or 5)))

    if not summoner_input:
        return "Erreur : Le paramètre 'summoner_name' est requis (format 'Pseudo#TAG', ex: 'Agurin#EUW').", True

    # Si l'agent a passé "euw1:Pseudo#TAG" dans query
    if ":" in summoner_input and not data.get("region"):
        parts = summoner_input.split(":", 1)
        if parts[0].lower() in PLATFORM_TO_REGIONAL:
            raw_region = parts[0].lower()
            summoner_input = parts[1].strip()

    platform = PLATFORM_NORMALIZE.get(raw_region, raw_region)
    regional = PLATFORM_TO_REGIONAL.get(platform, "europe")

    if "#" in summoner_input:
        game_name, tag_line = summoner_input.split("#", 1)
    else:
        game_name = summoner_input
        tag_line = DEFAULT_TAG_BY_PLATFORM.get(platform, "EUW")

    game_name = game_name.strip()
    tag_line = tag_line.strip()

    # 2. Récupération de la clé API Riot Games
    api_key = os.environ.get("RIOT_API_KEY", "METTRE_TA_CLE_RGAPI_ICI").strip()
    if not api_key or api_key == "METTRE_TA_CLE_RGAPI_ICI":
        return _fallback_opgg(platform, game_name, tag_line, "Variable d'environnement RIOT_API_KEY non configurée")

    headers = {"X-Riot-Token": api_key}

    try:
        # =========================================================================
        # ÉTAPE A : ACCOUNT-V1 (Riot ID -> PUUID)
        # =========================================================================
        acc_url = f"https://{regional}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{quote(game_name)}/{quote(tag_line)}"
        acc_resp = requests.get(acc_url, headers=headers, timeout=10)

        if acc_resp.status_code in (401, 403):
            return _fallback_opgg(platform, game_name, tag_line, f"Clé RIOT_API_KEY expirée ou invalide (HTTP {acc_resp.status_code})")
        elif acc_resp.status_code == 404:
            return f"❌ Joueur introuvable sur Riot Account-V1 : '{game_name}#{tag_line}' (région routage: {regional}). Vérifie le #TAG exact.", True
        elif acc_resp.status_code != 200:
            return f"❌ Erreur Account-V1 (HTTP {acc_resp.status_code}) : {acc_resp.text}", True

        acc_data = acc_resp.json()
        puuid = acc_data["puuid"]
        real_name = f"{acc_data.get('gameName', game_name)}#{acc_data.get('tagLine', tag_line)}"

        # =========================================================================
        # ÉTAPE B : SUMMONER-V4 (PUUID -> Summoner ID & Niveau)
        # =========================================================================
        sum_url = f"https://{platform}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
        sum_resp = requests.get(sum_url, headers=headers, timeout=10)
        summoner_level = "?"
        summoner_id = None
        if sum_resp.status_code == 200:
            sum_data = sum_resp.json()
            summoner_level = sum_data.get("summonerLevel", "?")
            summoner_id = sum_data.get("id")

        # =========================================================================
        # ÉTAPE C : LEAGUE-V4 (Classement Solo/Duo & Flex)
        # =========================================================================
        ranks_summary = []
        # Supporte l'endpoint moderne by-puuid ou classique by-summoner
        league_url = f"https://{platform}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
        league_resp = requests.get(league_url, headers=headers, timeout=10)
        if league_resp.status_code != 200 and summoner_id:
            league_url = f"https://{platform}.api.riotgames.com/lol/league/v4/entries/by-summoner/{summoner_id}"
            league_resp = requests.get(league_url, headers=headers, timeout=10)

        if league_resp.status_code == 200:
            for entry in league_resp.json():
                q_type = entry.get("queueType", "")
                q_label = "Solo/Duo" if q_type == "RANKED_SOLO_5x5" else ("Flex 5v5" if q_type == "RANKED_FLEX_SR" else q_type)
                tier = entry.get("tier", "UNRANKED")
                rank = entry.get("rank", "")
                lp = entry.get("leaguePoints", 0)
                wins = entry.get("wins", 0)
                losses = entry.get("losses", 0)
                total_g = wins + losses
                wr = round((wins / total_g) * 100, 1) if total_g > 0 else 0.0
                ranks_summary.append(f"  - {q_label:10s} : {tier} {rank} ({lp} LP) | {wins}V / {losses}D (Winrate: {wr}%)")

        ranks_block = "\n".join(ranks_summary) if ranks_summary else "  - Non classé (Unranked) cette saison."

        # =========================================================================
        # ÉTAPE D : MATCH-V5 (Historique des N derniers matchs & Calcul KDA exact)
        # =========================================================================
        ids_url = f"https://{regional}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count={match_count}"
        ids_resp = requests.get(ids_url, headers=headers, timeout=10)
        match_ids = ids_resp.json() if ids_resp.status_code == 200 else []

        matches_lines = []
        tot_k, tot_d, tot_a, tot_wins, valid_matches = 0, 0, 0, 0, 0

        for m_id in match_ids:
            m_url = f"https://{regional}.api.riotgames.com/lol/match/v5/matches/{m_id}"
            m_resp = requests.get(m_url, headers=headers, timeout=10)
            if m_resp.status_code != 200:
                continue
            m_data = m_resp.json()
            info = m_data.get("info", {})
            duration_sec = info.get("gameDuration", 0)
            duration_min = max(1.0, duration_sec / 60.0)
            game_mode = info.get("gameMode", "CLASSIC")

            # Chercher le joueur dans la liste des 10 participants via son PUUID
            player = next((p for p in info.get("participants", []) if p.get("puuid") == puuid), None)
            if not player:
                continue

            valid_matches += 1
            win = player.get("win", False)
            if win:
                tot_wins += 1
            champ = player.get("championName", "Inconnu")
            role = player.get("teamPosition") or player.get("individualPosition") or "ANY"
            k = player.get("kills", 0)
            d = player.get("deaths", 0)
            a = player.get("assists", 0)
            cs = player.get("totalMinionsKilled", 0) + player.get("neutralMinionsKilled", 0)
            cs_min = round(cs / duration_min, 1)
            dmg = player.get("totalDamageDealtToChampions", 0)
            kda_ratio = "Perfect" if d == 0 else f"{round((k + a) / d, 2):.2f}"

            tot_k += k
            tot_d += d
            tot_a += a

            res_icon = "🟢 VICTOIRE" if win else "🔴 DÉFAITE "
            matches_lines.append(
                f"  {res_icon} | {champ:12s} ({role:6s}) | KDA: {k:2d}/{d:2d}/{a:2d} ({kda_ratio:7s}) | "
                f"CS: {cs:3d} ({cs_min}/m) | Dégâts: {dmg:6d} | {int(duration_min)} min [{game_mode}]"
            )

        if valid_matches > 0:
            avg_k = round(tot_k / valid_matches, 1)
            avg_d = round(tot_d / valid_matches, 1)
            avg_a = round(tot_a / valid_matches, 1)
            global_kda = round((tot_k + tot_a) / max(1, tot_d), 2)
            recent_wr = round((tot_wins / valid_matches) * 100, 1)
            kda_header = (
                f"📊 BILAN SUR LES {valid_matches} DERNIERS MATCHS :\n"
                f"  - Winrate récent : {tot_wins}V / {valid_matches - tot_wins}D ({recent_wr}%)\n"
                f"  - KDA Moyen      : {avg_k} / {avg_d} / {avg_a} (Ratio KDA exact : {global_kda}:1)"
            )
            matches_block = "\n".join(matches_lines)
        else:
            kda_header = "📊 Aucun match récent trouvé dans Match-V5."
            matches_block = "  (Vide)"

        report = (
            f"🏆 [RAPPORT OFFICIEL RIOT GAMES API — {real_name} ({platform.upper()})]\n"
            f"Niveau d'invocateur : {summoner_level}\n\n"
            f"🎖️ CLASSEMENT ACTUEL (League-V4) :\n{ranks_block}\n\n"
            f"{kda_header}\n\n"
            f"⚔️ HISTORIQUE DÉTAILLÉ (Match-V5) :\n{matches_block}"
        )
        return report, False

    except Exception as e:
        return f"Exception lors de l'appel Riot Games API : {e}", True
