News providers TODO:

- [x] [24ur.py](scraper/app/providers/_24ur.py): Verify and improve fetching articles.
- [x] [rtv.py](scraper/app/providers/rtv.py): Implement scraping logic.
- [x] [delo.py](scraper/app/providers/delo.py): Implement scraping logic.
- [x] [siol.py](scraper/app/providers/siol.py): Implement scraping logic.
- [x] [nova24tv.py](scraper/app/providers/nova24tv.py): Implement scraping logic.
- [x] [necenzurirano.py](scraper/app/providers/necenzurirano.py): Implement scraping logic.
- [x] [dnevnik.py](scraper/app/providers/dnevnik.py): Implement scraping logic.
- [x] [svet24.py](scraper/app/providers/svet24.py):
- [x] [vecer.py](scraper/app/providers/vecer.py): Implement scraping logic.
- [x] [mladina.py](scraper/app/providers/mladina.py): Implement scraping logic.
- [x] [primorskenovice.py](scraper/app/providers/primorskenovice.py): Implement scraping logic.
- [x] [ljubljanskenovice.py](scraper/app/providers/ljubljanskenovice.py): Implement scraping logic.
- [x] [maribor24.py](scraper/app/providers/maribor24.py): Implement scraping logic.
- [x] [planettv.py](scraper/app/providers/planettv.py): Implement scraping logic.
- [x] [slotech.py](scraper/app/providers/slotech.py): Implement scraping logic.
- [x] [reporter.py](scraper/app/providers/reporter.py): Implement scraping logic.
- [x] [n1info.py](scraper/app/providers/n1info.py): Implement scraping logic.
- [ ] [podcrto.py](scraper/app/providers/podcrto.py): Implement scraping logic.
- [x] [zurnal24.py](scraper/app/providers/zurnal24.py): Implement scraping logic.
- [x] [slovenskenovice.py](scraper/app/providers/slovenskenovice.py): Implement scraping logic.
- [x] [sta.py](scraper/app/providers/sta.py): USE https://www.sta.si/rss-0

This website already implemented article grouping by news event: https://www.times.si/
They scrape periodicaly every 10 minutes.
This is where we can get ideas for other news sources.

### English, hard to cluster with the other, but still might be important

- [ ] [sloveniatimes.py](scraper/app/providers/sloveniatimes.py): USE https://www.sloveniatimes.com/feed

### paywalled, which sucks

- [ ] [finance.py](scraper/app/providers/finance.py): Implement scraping logic.

### No longer publishing

- [ ] [skandal24.py](scraper/app/providers/skandal24.py): Stopped publishing in 2023.

### regional providers, maybe relevant for some localized news feature

- [ ] koroske novice
- [ ] primorske novice
- [ ] ljubljanske novice
- [ ] pomurske novice
- [ ] ...

### TODO:

- [ ] check which providers are possibly have paywalled articles
- [ ] check edge cases where we scrape only for todays date. if we scrape every 4 hours, we can miss up to 4 hours of articles before midnight
