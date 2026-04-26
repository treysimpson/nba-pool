# SLBL NBA Playoff Pool

Live tracker for the SLBL NBA Playoff Pool. Auto-updates every 6 hours via GitHub Actions.

## Setup

### 1. Create the GitHub repo

```bash
git init
git remote add origin https://github.com/treysimpson/nba-pool.git
git add .
git commit -m "initial commit"
git push -u origin main
```

### 2. Add the API key as a GitHub secret

1. Go to your repo on GitHub
2. **Settings → Secrets and variables → Actions → New repository secret**
3. Name: `BALLDONTLIE_API_KEY`
4. Value: `ccfa99dc-879c-4ce8-b87b-9ddcdaeb61d2`

### 3. Connect to Netlify

1. Go to [netlify.com](https://netlify.com) → **Add new site → Import from Git**
2. Connect your GitHub account, select this repo
3. Build command: *(leave blank)*
4. Publish directory: `.` (root)
5. Deploy

Netlify will auto-deploy every time GitHub Actions pushes an updated `stats.json`.

### 4. Run the scraper manually (first time)

After setting the secret, go to **Actions tab → Update Playoff Stats → Run workflow**.
This populates `stats.json` immediately without waiting 6 hours.

## Updating manual fields

Some fields (techs, ejections, trophies) can't be scraped automatically.

**Option A — In the browser:** Click the ⚙ ADMIN button in the top right of the page. Changes apply to your session instantly but aren't saved permanently.

**Option B — Edit stats.json directly:** Update the `manual` section in `stats.json` and push to GitHub. Netlify will redeploy in ~30 seconds.

```json
"manual": {
  "techs_leader": "Dillon Brooks",
  "ejections_leader": "Dillon Brooks",
  "larry_bird_trophy": null,
  "magic_trophy": null,
  "finals_mvp": null
}
```

## File structure

```
nba-pool/
├── index.html          ← the dashboard (rename nba_pool.html → index.html)
├── stats.json          ← auto-updated by scraper
├── scraper.py          ← pulls from balldontlie API
└── .github/
    └── workflows/
        └── scrape.yml  ← runs scraper every 6 hours
```
