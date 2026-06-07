# Rekentool Fruitpakketten

Webapplicatie voor het berekenen van de goedkoopste inkoopsamenstelling voor fruitpakketten, gebaseerd op een dagelijkse prijslijst van de leverancier.

## Applicaties

### App 1 – Handelaar (`/`)
- Upload de PDF-prijslijst van de dag
- Voer in hoeveel pakketten per type nodig zijn
- Zie direct welke producten het goedkoopst zijn en wat de totale inkoopkosten zijn

### App 2 – Beheer (`/admin`)
- Configureer pakketsoorten (naam, totaal stuks, categoriepercentages)
- Beheer fruitcategorieën en zoekwoorden
- Koppel producten handmatig aan categorieën
- Stel gewicht per stuk in voor producten die per kilo worden verkocht
- Bekijk en activeer eerder geüploade prijslijsten

## Installatie

```bash
pip install -r requirements.txt
cd backend
python main.py
```

Of via Docker:
```bash
docker build -t rekentool .
docker run -p 8000:8000 -v $(pwd)/data:/app/data rekentool
```

Open in browser: http://localhost:8000

## Hoe werkt de berekening?

1. De prijslijst-PDF wordt geanalyseerd en producten worden automatisch aan categorieën gekoppeld op basis van zoekwoorden.
2. Per categorie wordt de prijs per stuk berekend:
   - Producten per *stuk*: prijs = stuksprijs
   - Producten per *colli*: prijs = colli-prijs ÷ aantal stuks in colli
   - Producten per *kilo*: prijs = kilo-prijs × (gramgewicht ÷ 1000) — vereist handmatige invoer van gramgewicht in Beheer
3. Een lineair programma (scipy linprog) bepaalt de optimale percentageverdeling binnen de ingestelde marges.
4. Per pakketsoort wordt de goedkoopste productcombinatie getoond.
