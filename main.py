import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LETTERBOXD_LIST_URL = "https://letterboxd.com/jack/list/official-top-250-films-with-the-most-fans/"

_cache = {
    "movies": None
}


def scrape_letterboxd_top250():
    """
    Scrape the Letterboxd list for top movies with titles, years, poster images, and links.
    Returns a list of dicts.
    """
    url = LETTERBOXD_LIST_URL
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    resp = requests.get(url, headers=headers, timeout=20)
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Failed to fetch source list: {resp.status_code}")

    soup = BeautifulSoup(resp.text, "lxml")

    movies = []

    # Two common structures on Letterboxd lists: posters grid and list entries.
    # We'll attempt to parse poster-grid first.
    grid = soup.select("ul.poster-list -p125, ul.poster-list, ul.poster-list -grid")

    # Fallback: generic posters
    posters = soup.select("ul.poster-list li.poster-container")
    if not posters:
        posters = soup.select("li.poster-container")

    for li in posters:
        anchor = li.select_one("a.poster")
        if not anchor:
            anchor = li.select_one("a.frame")
        if not anchor:
            continue

        href = anchor.get("href") or ""
        link = f"https://letterboxd.com{href}" if href.startswith("/") else href

        # Title and year often in data attributes or img alt
        img = anchor.select_one("img")
        title = None
        year = None
        if img:
            title = img.get("alt")
            # alt often like "Movie Title (Year)"
            if title and title.endswith(")") and "(" in title:
                try:
                    base, yr = title.rsplit("(", 1)
                    title = base.strip()
                    year = yr.strip(") ")
                except Exception:
                    pass

        # Poster source
        poster_url = None
        if img:
            poster_url = img.get("data-src") or img.get("src")
            if poster_url and poster_url.startswith("//"):
                poster_url = "https:" + poster_url

        # If still missing title, try tooltip
        if not title:
            title = anchor.get("data-film-name") or anchor.get("aria-label")

        if title:
            movies.append({
                "title": title,
                "year": year,
                "poster": poster_url,
                "link": link,
            })

    # Deduplicate and keep first 250
    dedup = []
    seen = set()
    for m in movies:
        key = (m.get("title"), m.get("year"))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(m)
        if len(dedup) >= 250:
            break

    return dedup


@app.get("/")
def read_root():
    return {"message": "Movie API running"}


@app.get("/api/movies")
def get_movies():
    # Return cached if available during session
    if _cache["movies"]:
        return {"count": len(_cache["movies"]), "results": _cache["movies"]}

    try:
        movies = scrape_letterboxd_top250()
        _cache["movies"] = movies
        return {"count": len(movies), "results": movies}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        from database import db
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = getattr(db, 'name', '✅ Connected')
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except ImportError:
        response["database"] = "❌ Database module not found"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
