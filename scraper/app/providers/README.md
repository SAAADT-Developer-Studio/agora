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
- [ ] [podcrto.py](scraper/app/providers/podcrto.py)
- [x] [zurnal24.py](scraper/app/providers/zurnal24.py)
- [x] [slovenskenovice.py](scraper/app/providers/slovenskenovice.py)
- [x] [sta.py](scraper/app/providers/sta.py): USE https://www.sta.si/rss-0
- [x] [bloombergadria](https://si.bloombergadria.com/rss)
- [x] [cekin.py](scraper/app/providers/cekin.py): rss: https://cekin.si/rss
- [ ] [forbes.n1info](scraper/app/providers/forbes.n1info.py) https://forbes.n1info.si/
- [x] [demokracija](https://demokracija.si/) https://demokracija.si/
- [x] [info360](https://info360.si/) https://info360.si//rss.xml
- [ ] [insajder](https://insajder.com/)
- [ ] [metropolitan](https://www.metropolitan.si/) https://www.metropolitan.si/feeds/latest/
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
- [ ] [študent](https://www.student.si/)
- [ ] [pomurec](https://pomurec.com/)
- [ ] [pozareport](https://pozareport.si)
- [ ] [primorski dnevnik](https://www.primorski.eu)
- [ ] [islamska skupnost novice](https://www.islamska-skupnost.si/novice/)
- [ ] [sobota info](https://sobotainfo.com/novice)
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
- [ ] [eposavje](https://www.eposavje.com/)

Idea: include government feeds, for example FURS https://www.fu.gov.si/rss

A news site for all slovenian news sites: https://www.telex.si/viri.php

TODO:

Go over all providers again and use rss if possible. You can typically find it
by viewing the page source and looking for <link> tags with rel="alternate" and
type="application/rss+xml" or type="application/atom+xml"

- dnevnik https://www.dnevnik.si/rss.xml

This website already implemented article grouping by news event:
https://www.times.si/ They scrape periodicaly every 10 minutes. This is where we
can get ideas for other news sources.

### English, hard to cluster with the other, but still might be important

- [ ] [sloveniatimes.py](scraper/app/providers/sloveniatimes.py): USE
      https://www.sloveniatimes.com/feed

### paywalled, which sucks

- [ ] [finance.py](scraper/app/providers/finance.py)

### TODO:

- [ ] check which providers are possibly have paywalled articles
