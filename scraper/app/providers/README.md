News providers TODO:

- [x] [24ur.py](scraper/app/providers/_24ur.py)
- [x] [rtv.py](scraper/app/providers/rtv.py)
- [x] [delo.py](scraper/app/providers/delo.py)
- [x] [siol.py](scraper/app/providers/siol.py)
- [x] [nova24tv.py](scraper/app/providers/nova24tv.py)
- [x] [necenzurirano.py](scraper/app/providers/necenzurirano.py)
- [x] [dnevnik.py](scraper/app/providers/dnevnik.py)
- [x] [svet24.py](scraper/app/providers/svet24.py):
- [x] [vecer.py](scraper/app/providers/vecer.py)
- [x] [mladina.py](scraper/app/providers/mladina.py)
- [x] [primorskenovice.py](scraper/app/providers/primorskenovice.py)
- [x] [ljubljanskenovice.py](scraper/app/providers/ljubljanskenovice.py)
- [x] [maribor24.py](scraper/app/providers/maribor24.py)
- [x] [slotech.py](scraper/app/providers/slotech.py)
- [x] [reporter.py](scraper/app/providers/reporter.py)
- [x] [n1info.py](scraper/app/providers/n1info.py)
- [x] [zurnal24.py](scraper/app/providers/zurnal24.py)
- [x] [slovenskenovice.py](scraper/app/providers/slovenskenovice.py)
- [x] [sta.py](scraper/app/providers/sta.py): USE https://www.sta.si/rss-0
- [x] [bloombergadria](https://si.bloombergadria.com/rss)
- [x] [cekin.py](scraper/app/providers/cekin.py): rss: https://cekin.si/rss
- [x] [demokracija](https://demokracija.si/) https://demokracija.si/
- [x] [info360](https://info360.si/) https://info360.si//rss.xml
- [x] [lokalec](https://www.lokalec.si) https://www.lokalec.si/feed/
- [ ] [portal24](https://portal24.si/)
- [ ] [metropolitan](https://www.metropolitan.si/) https://www.metropolitan.si/feeds/latest/
- [ ] [nadlani](nadlani.si) https://www.nadlani.si/feed/
- [ ] [sobota info](https://sobotainfo.com/novice)
- [ ] [forbes.n1info](scraper/app/providers/forbes.n1info.py) https://forbes.n1info.si/
- [ ] [mariborinfo](https://mariborinfo.com/)
- [ ] [ljubljanainfo](https://ljubljanainfo.com/novice)
- [ ] [finance](https://www.finance.si/) PAYWALLED, make sure this is handled https://feeds.feedburner.com/financesi
- [ ] [pomurec](https://pomurec.com/)
- [ ] [ptujinfo](https://ptujinfo.com/novice)
- [ ] [obalaplus](https://obalaplus.si/)
- [ ] [eposavje](https://www.eposavje.com/)
- [ ] [študent](https://www.student.si/)
- [ ] [zon](https://zon.si/) https://zon.si/feed/
- [ ] [insajder](https://insajder.com/)
- [ ] [avto-magazin](https://avto-magazin.metropolitan.si/)
- [ ] [vestnik](https://vestnik.svet24.si/novice)
- [ ] [regional](https://www.regionalobala.si/)
- [ ] [politikis](https://www.politikis.si/)
- [ ] [monitor](https://www.monitor.si/)
- [ ] [dolenjski list](https://dolenjskilist.svet24.si)
- [ ] [gorenjski glas](https://www.gorenjskiglas.si)
- [ ] [ekipa24](https://ekipa.svet24.si)
- [ ] [moja-dolenjska](https://moja-dolenjska.si/)
- [ ] [domovina](https://www.domovina.je/)
- [ ] [casnik](https://casnik.si)
- [ ] [pozareport](https://pozareport.si)
- [ ] [primorski dnevnik](https://www.primorski.eu)
- [ ] [islamska skupnost novice](https://www.islamska-skupnost.si/novice/)
- [ ] [celjske novice](https://www.celje.info)
- [ ] [regional obala](https://www.regionalobala.si)
- [ ] [velenjcan](https://www.velenjcan.si)
- [ ] [ptujinfo](https://ptujinfo.com)
- [ ] [kamniške novice](https://www.kamnik.info/novice_kamnik/)
- [ ] [zasavske online novice](https://zon.si)
- [ ] [domžalske novice](https://www.domzalske-novice.si)
- [ ] [škofje loške novice](https://loske-novice.si)
- [ ] [lokalne goriške novice](https://www.robin.si/kategorija/lokalne-novice/)
- [ ] [koroske novice](https://www.koroskenovice.si/)
- [ ] [pomurske novice](https://pomurske-novice.si) https://pomurske-novice.si/feed/
- [ ] [mojaobcina](https://www.mojaobcina.si/ljubljana) every municipality has its own feed
- [ ] [posavskiobzornik](https://www.posavskiobzornik.si/)
- [ ] [podcrto.py](scraper/app/providers/podcrto.py)

Idea: include government feeds, for example FURS https://www.fu.gov.si/rss

A news site for all slovenian news sites: https://www.telex.si/viri.php

## Adding a Provider

### 1. Locate the RSS Feed

Identify the RSS feed URL for the target website. This can typically be found by:

- **Viewing Page Source:** Inspect the HTML source code for `<link>` tags with the following attributes:
  - `rel="alternate"`
  - `type="application/rss+xml"` or `type="application/atom+xml"`

### 2. Create the Provider File

Create a new Python file at `/scraper/app/providers/[providername].py`.

```python
from app.providers.news_provider import NewsProvider


class DeloProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key="delo",  # Unique key for the provider, used in the command line to run with specific providers
            name="Delo",  # Display name of the provider
            url="https://www.delo.si",  # Base URL of the website
            rss_feeds=["https://www.delo.si/rss"],  # List of RSS feed URLs
        )
      # If website has no rss feed, implement fetching of new articles manually
    async def fetch_articles(self) -> list[ArticleMetadata]:
        pass

```

### 3. Add to the list of providers in [providers.py](/scraper/app/providers/providers.py)

### 4. Assign a rank to the provider in [ranks.py](/scraper/app/providers/ranks.py)

### 5. Find the provider logo, resize if needed to get 1x1 aspect ratio.

```bash
# Store logo  in /data/logos_source and run
make sync-images
```

### 6. Test the Provider

Verify the new provider by running the following command:

```bash
uv run python3 -m app.main --providers=delo
```

## Other

This website already implemented article grouping by news event:
https://www.times.si/ They scrape periodicaly every 10 minutes. This is where we
can get ideas for other news sources.

### English providers, can still be clustered with others, since embeddings are based on a translated summary

- [ ] [sloveniatimes.py](scraper/app/providers/sloveniatimes.py): USE
      https://www.sloveniatimes.com/feed
- [ ] [total-slovenia-news](https://www.total-slovenia-news.com/)

### TODO:

- [ ] check which providers are possibly have paywalled articles
