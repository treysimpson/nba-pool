"""
SLBL NBA Playoff Pool — Stats Scraper
Scrapes Basketball-Reference for 2026 playoff stats
Runs locally on your PC via Task Scheduler, then pushes stats.json to GitHub
"""

import json
import os
import time
import subprocess
from collections import defaultdict
from datetime import datetime
from bs4 import BeautifulSoup, Comment

try:
    from curl_cffi import requests
    IMPERSONATE = "chrome120"
    print("Using curl_cffi for Chrome TLS impersonation")
except ImportError:
    import requests
    IMPERSONATE = None
    print("WARNING: curl_cffi not found, falling back to regular requests")

SEASON = 2026
REPO_DIR = os.path.dirname(os.path.abspath(__file__))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.basketball-reference.com/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
}

URLS = {
    "per_game": f"https://www.basketball-reference.com/playoffs/NBA_{SEASON}_per_game.html",
    "totals":   f"https://www.basketball-reference.com/playoffs/NBA_{SEASON}_totals.html",
    "games":    f"https://www.basketball-reference.com/playoffs/NBA_{SEASON}_games.html",
    "game_highs": f"https://www.basketball-reference.com/play-index/pgl_finder.fcgi?request=1&match=game&type=playoffs&year_min={SEASON}&year_max={SEASON}&age_min=0&age_max=99&is_playoffs=Y&order_by=pts&order_by_asc=&offset=0",
}


def fetch(url, retries=3):
    for attempt in range(retries):
        try:
            print(f"  Fetching {url}")
            if IMPERSONATE:
                r = requests.get(url, headers=HEADERS, impersonate=IMPERSONATE, timeout=20)
            else:
                r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 429:
                wait = 60 * (attempt + 1)
                print(f"  Rate limited — waiting {wait}s")
                time.sleep(wait)
                continue
            if r.status_code == 403:
                print(f"  403 Forbidden — retrying in 15s")
                time.sleep(15)
                continue
            r.raise_for_status()
            print(f"  OK ({r.status_code})")
            time.sleep(4)
            return r.text
        except Exception as e:
            print(f"  Error (attempt {attempt+1}): {e}")
            time.sleep(5)
    return None


def find_table(html, table_id):
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", {"id": table_id})
    if not table:
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            inner = BeautifulSoup(comment, "lxml")
            table = inner.find("table", {"id": table_id})
            if table:
                break
    return table


def parse_player_table(html, table_id):
    """Generic parser for BBRef player stat tables."""
    table = find_table(html, table_id)
    if not table:
        soup = BeautifulSoup(html, "lxml")
        tables = soup.find_all("table")
        print(f"  Table '{table_id}' not found. Available: {[t.get('id') for t in tables]}")
        return []

    players = []
    headers = []
    for row in table.find_all("tr"):
        cls = row.get("class", [])
        if "over_header" in cls:
            continue
        cells = row.find_all(["th", "td"])
        if not cells:
            continue
        if "thead" in cls or row.find("th", {"data-stat": "player"}):
            headers = [c.get("data-stat", "") for c in cells]
            continue
        if not headers:
            continue
        row_data = {headers[i]: c.get_text(strip=True) for i, c in enumerate(cells) if i < len(headers)}
        player = row_data.get("player", "").replace("*", "").strip()
        if not player or player == "Player":
            continue
        players.append(row_data)
    return players


def parse_per_game(html):
    print("Parsing per-game stats...")
    rows = parse_player_table(html, "per_game_stats")
    players = []
    for row_data in rows:
        player = row_data.get("player", "").replace("*", "").strip()
        try:
            entry = {
                "name": player,
                "gp":   int(row_data.get("g", 0) or 0),
                "pts":  float(row_data.get("pts_per_g", 0) or 0),
                "reb":  float(row_data.get("trb_per_g", 0) or 0),
                "ast":  float(row_data.get("ast_per_g", 0) or 0),
                "ftm":  float(row_data.get("ft_per_g", 0) or 0),
                "fg3m": float(row_data.get("fg3_per_g", 0) or 0),
                "blk":  float(row_data.get("blk_per_g", 0) or 0),
                "stl":  float(row_data.get("stl_per_g", 0) or 0),
                "tov":  float(row_data.get("tov_per_g", 0) or 0),
            }
            if entry["gp"] >= 1:
                players.append(entry)
        except (ValueError, TypeError):
            continue
    print(f"  {len(players)} players")
    return players


def parse_totals(html):
    """Parse totals page for total minutes played."""
    print("Parsing totals (for minutes)...")
    rows = parse_player_table(html, "totals_stats")
    players = []
    for row_data in rows:
        player = row_data.get("player", "").replace("*", "").strip()
        try:
            entry = {
                "name": player,
                "gp":   int(row_data.get("g", 0) or 0),
                "min":  float(row_data.get("mp", 0) or 0),  # total minutes, not per-game
            }
            if entry["gp"] >= 1:
                players.append(entry)
        except (ValueError, TypeError):
            continue
    print(f"  {len(players)} players with minutes data")
    return players


def compute_per_game_leaders(per_game_players, totals_players):
    """Build top 5 leaders. Uses per-game for most stats, totals for minutes."""
    qualified = [p for p in per_game_players if p["gp"] >= 2]

    # Build minutes lookup from totals
    min_lookup = {p["name"]: p["min"] for p in totals_players if p["gp"] >= 2}

    cats = {
        "ppg":   "pts",
        "rpg":   "reb",
        "apg":   "ast",
        "ftpg":  "ftm",
        "tpm":   "fg3m",
        "bpg":   "blk",
        "spg":   "stl",
        "tovpg": "tov",
    }
    leaders = {}
    for key, field in cats.items():
        ranked = sorted(
            [{"name": p["name"], "value": round(p[field], 1), "gp": p["gp"]}
             for p in qualified if p.get(field, 0) > 0],
            key=lambda x: x["value"], reverse=True
        )
        leaders[key] = ranked[:5]
        if ranked:
            print(f"  {key}: {ranked[0]['name']} {ranked[0]['value']}")

    # Minutes — total minutes from totals page
    min_ranked = sorted(
        [{"name": name, "value": round(mins, 0), "gp": 0}
         for name, mins in min_lookup.items() if mins > 0],
        key=lambda x: x["value"], reverse=True
    )
    leaders["min"] = min_ranked[:5]
    if min_ranked:
        print(f"  min (total): {min_ranked[0]['name']} {min_ranked[0]['value']}")

    return leaders


def parse_games(html):
    """Parse all game results from the games page."""
    print("Parsing game results...")
    soup = BeautifulSoup(html, "lxml")

    all_tables = list(soup.find_all("table"))
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        inner = BeautifulSoup(comment, "lxml")
        all_tables.extend(inner.find_all("table"))

    games = []
    for table in all_tables:
        for row in table.find_all("tr"):
            tds = row.find_all("td")
            if not tds:
                continue
            row_data = {td.get("data-stat"): td.get_text(strip=True) for td in tds}
            visitor = row_data.get("visitor_team_name", "")
            home = row_data.get("home_team_name", "")
            vpts = row_data.get("visitor_pts", "")
            hpts = row_data.get("home_pts", "")
            date = row_data.get("date_game", "")
            if not visitor or not home or not vpts or not hpts:
                continue
            try:
                games.append({
                    "visitor": visitor, "home": home,
                    "visitor_pts": int(vpts), "home_pts": int(hpts),
                    "date": date,
                })
            except:
                continue

    print(f"  {len(games)} games parsed")
    return games


def compute_game_records(games):
    print("Computing game records...")
    team_games = defaultdict(int)
    max_mov, max_mov_team, max_mod_team, max_mov_context = 0, None, None, None
    max_team_score, max_team_score_team, max_team_score_context = 0, None, None
    series_games = defaultdict(list)

    for g in games:
        v, h = g["visitor"], g["home"]
        vpts, hpts = g["visitor_pts"], g["home_pts"]
        margin = abs(hpts - vpts)
        winner = h if hpts > vpts else v
        loser = v if hpts > vpts else h
        w_pts = max(hpts, vpts)
        l_pts = min(hpts, vpts)

        series_key = tuple(sorted([h, v]))
        series_games[series_key].append(g)
        game_num = len(series_games[series_key])

        if margin > max_mov:
            max_mov = margin
            max_mov_team = winner
            max_mod_team = loser
            max_mov_context = f"{winner} def. {loser} {w_pts}-{l_pts} (Game {game_num})"

        for score, team in [(hpts, h), (vpts, v)]:
            if score > max_team_score:
                max_team_score = score
                max_team_score_team = team
                opp = v if team == h else h
                max_team_score_context = f"{team} vs {opp}, Game {game_num}"

        team_games[h] += 1
        team_games[v] += 1

    game7s = sum(1 for gl in series_games.values() if len(gl) == 7)
    most = max(team_games, key=team_games.get) if team_games else None
    least = min(team_games, key=team_games.get) if team_games else None

    print(f"  MOV: {max_mov} — {max_mov_context}")
    print(f"  Max score: {max_team_score} — {max_team_score_context}")
    print(f"  Most games: {most} ({team_games.get(most,0)})")
    print(f"  Fewest: {least} ({team_games.get(least,0)})")
    print(f"  Game 7s: {game7s}")
    print(f"  Teams: {sorted(team_games.keys())}")

    return {
        "mov_num": max_mov,
        "mov_team": max_mov_team,
        "mod_team": max_mod_team,
        "mov_context": max_mov_context,
        "most_games_team": most,
        "most_games_count": team_games.get(most, 0) if most else 0,
        "least_games_team": least,
        "least_games_count": team_games.get(least, 0) if least else 0,
        "max_team_pts": max_team_score,
        "max_team_pts_team": max_team_score_team,
        "max_team_pts_context": max_team_score_context,
        "game7s": game7s,
    }


def fetch_player_game_highs():
    """Scrape BBRef playoff game finder for highest single-game scores."""
    print("Fetching player single-game highs...")
    # BBRef game finder URL — sorted by pts descending, playoffs only
    url = URLS["game_highs"]
    html = fetch(url)
    if not html:
        print("  Could not fetch game highs")
        return []

    soup = BeautifulSoup(html, "lxml")
    # Also check comments
    table = soup.find("table", {"id": "pgl_basic"})
    if not table:
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            inner = BeautifulSoup(comment, "lxml")
            table = inner.find("table", {"id": "pgl_basic"})
            if table:
                break

    if not table:
        print("  pgl_basic table not found")
        return []

    results = []
    headers = []
    for row in table.find_all("tr"):
        cls = row.get("class", [])
        if "over_header" in cls or "thead" in cls:
            cells = row.find_all(["th", "td"])
            if cells:
                headers = [c.get("data-stat", "") for c in cells]
            continue
        cells = row.find_all(["th", "td"])
        if not cells or not headers:
            continue
        row_data = {headers[i]: c.get_text(strip=True) for i, c in enumerate(cells) if i < len(headers)}
        player = row_data.get("player", "").replace("*", "").strip()
        pts_str = row_data.get("pts", "")
        date = row_data.get("date_game", "")
        opp = row_data.get("opp_id", "")
        if not player or not pts_str:
            continue
        try:
            results.append({
                "name": player,
                "pts": int(pts_str),
                "date": date,
                "opp": opp,
            })
        except:
            continue

    print(f"  {len(results)} game log entries")
    return results


def compute_player_records(per_game_players, game_highs):
    """Use actual game log data for single-game highs."""
    if not game_highs and not per_game_players:
        return {"top_scorer_game": None, "top_scorer_context": None,
                "max_player_pts": None, "max_player_pts_context": None}

    if game_highs:
        top = game_highs[0]  # already sorted by pts desc
        return {
            "top_scorer_game": top["name"],
            "top_scorer_context": f"{top['pts']} pts vs {top['opp']} ({top['date']})",
            "max_player_pts": top["pts"],
            "max_player_pts_context": f"{top['name']} — {top['pts']} pts vs {top['opp']} ({top['date']})",
        }

    # Fallback to per-game leader
    if per_game_players:
        top = max(per_game_players, key=lambda p: p["pts"])
        return {
            "top_scorer_game": top["name"],
            "top_scorer_context": f"{top['pts']} PPG over {top['gp']} games",
            "max_player_pts": None,
            "max_player_pts_context": None,
        }

    return {"top_scorer_game": None, "top_scorer_context": None,
            "max_player_pts": None, "max_player_pts_context": None}


def push_to_github():
    print("\nPushing to GitHub...")
    try:
        subprocess.run(["git", "add", "stats.json"], cwd=REPO_DIR, check=True)
        result = subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=REPO_DIR)
        if result.returncode == 0:
            print("  No changes to push")
            return
        subprocess.run(["git", "commit", "-m",
            f"chore: update playoff stats [{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}]"],
            cwd=REPO_DIR, check=True)
        subprocess.run(["git", "push"], cwd=REPO_DIR, check=True)
        print("  Pushed!")
    except subprocess.CalledProcessError as e:
        print(f"  Git error: {e}")



def compute_series_results(games):
    """Build a series results dict keyed by 'TeamA vs TeamB'."""
    from collections import defaultdict
    series = defaultdict(lambda: {'wins': {}, 'games': 0})

    for g in games:
        v, h = g['visitor'], g['home']
        vpts, hpts = g['visitor_pts'], g['home_pts']
        winner = h if hpts > vpts else v
        key = ' vs '.join(sorted([h, v]))
        series[key]['games'] += 1
        series[key]['wins'][winner] = series[key]['wins'].get(winner, 0) + 1

    result = {}
    for key, data in series.items():
        teams = key.split(' vs ')
        winner = None
        for team, wins in data['wins'].items():
            if wins >= 4:
                winner = team
                break
        result[key] = {
            'wins': data['wins'],
            'games': data['games'],
            'winner': winner,
        }
    return result

def main():
    print(f"=== SLBL NBA Playoff Pool Scraper (BBRef {SEASON}) ===\n")

    pg_html = fetch(URLS["per_game"])
    if not pg_html:
        print("ERROR: Could not fetch per-game stats")
        exit(1)
    per_game_players = parse_per_game(pg_html)

    totals_html = fetch(URLS["totals"])
    totals_players = parse_totals(totals_html) if totals_html else []

    games_html = fetch(URLS["games"])
    if not games_html:
        print("ERROR: Could not fetch game results")
        exit(1)
    games = parse_games(games_html)

    game_highs = fetch_player_game_highs()

    output = {
        "updated": datetime.utcnow().isoformat() + "Z",
        "season": SEASON,
        "per_game_leaders": compute_per_game_leaders(per_game_players, totals_players),
        "game_records": compute_game_records(games),
        "player_records": compute_player_records(per_game_players, game_highs),
        "series": compute_series_results(games),
        "manual": {
            "techs_leader": None,
            "ejections_leader": None,
            "larry_bird_trophy": None,
            "magic_trophy": None,
            "finals_mvp": None,
        }
    }

    # Preserve existing manual values
    stats_path = os.path.join(REPO_DIR, "stats.json")
    if os.path.exists(stats_path):
        try:
            with open(stats_path) as f:
                existing = json.load(f)
            for key in output["manual"]:
                if existing.get("manual", {}).get(key) is not None:
                    output["manual"][key] = existing["manual"][key]
            print("Preserved manual values")
        except Exception as e:
            print(f"Could not read existing stats.json: {e}")

    with open(stats_path, "w") as f:
        json.dump(output, f, indent=2)
    print("stats.json written")

    push_to_github()
    print("\n=== Done! ===")


if __name__ == "__main__":
    main()

