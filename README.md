# TikTok Shop × Libri Automation

Eine Python-Pipeline für den Buchhandel, die Libri-Daten für TikTok Shop aufbereitet, Bestände abgleicht und neue Bestellungen für die weitere Verarbeitung vorbereitet.

## Ziel

Das Projekt verbindet wiederkehrende Abläufe zwischen Libri und TikTok Shop. Daten werden nicht ungeprüft veröffentlicht: unvollständige oder riskante Einträge landen in separaten Prüf- und Fehlerlisten.

## Module

### 1. Produktimport

Aus gespeicherten Libri-Produktseiten, Bestseller-Daten oder einer manuellen CSV entstehen:

- `tiktok_upload_green.xlsx` mit freigegebenen Produkten
- `candidate_report.csv` als Gesamtprüfung
- `review_hold.csv` für manuelle Kontrolle
- `rejects.csv` für unvollständige oder ungeeignete Datensätze
- `upload_log.md` als Zusammenfassung

Die Seller-SKU folgt dem Muster `LIBRI-{EAN}`. Das originale TikTok-Template wird kopiert und nicht strukturell verändert.

### 2. Bestandsabgleich

Das Inventory-Script liest den aktuellen Libri-Bestand und aktualisiert die zugehörige TikTok-SKU. Ein Dry-Run zeigt geplante Änderungen ohne Schreibzugriff.

```powershell
.\scripts\run_inventory_update_once.ps1 -DryRun -Limit 5
```

Der Abgleich kann lokal oder täglich über GitHub Actions ausgeführt werden. Pro Lauf entsteht ein nachvollziehbares CSV-Protokoll.

### 3. Bestellvorbereitung

Neue TikTok-Bestellungen werden aus der API oder testweise aus einem Seller-Center-CSV-Export gelesen. Für jede Bestellung entstehen unter anderem:

- eine Libri-Importdatei
- eine Lieferadressdatei
- ein lokaler Audit-Snapshot
- eine Zusammenfassung des Laufs

Der Workflow verarbeitet nur neue, noch nicht bekannte Bestellungen und speichert keine Kundendaten in öffentlichen GitHub-Issues.

## Schnellstart Produktimport

```powershell
python scripts\tiktok_libri_pipeline.py --workspace .
```

Weitere Produktseiten können über einen eigenen Ordner eingelesen werden:

```powershell
python scripts\tiktok_libri_pipeline.py `
  --workspace . `
  --detail-glob "libri_product_pages\*.html" `
  --limit 100
```

## Konfiguration

Zugangsdaten gehören ausschließlich in eine lokale `.env`-Datei oder in GitHub Actions Secrets. Sie dürfen nicht committed werden.

Je nach verwendetem Modul werden unter anderem benötigt:

- `LIBRI_CUSTOMER_NUMBER`
- `LIBRI_USERNAME`
- `LIBRI_PASSWORD`
- `TIKTOK_APP_KEY`
- `TIKTOK_APP_SECRET`
- `TIKTOK_ACCESS_TOKEN`
- optional `TIKTOK_SHOP_CIPHER`
- optional `TIKTOK_WAREHOUSE_ID`

## Sicherheits- und Prüfregeln

- Keine Zugangsdaten im Repository
- Dry-Run für Bestandsänderungen
- Manuelle Prüfliste für sensible oder unvollständige Produkte
- Keine automatische Veröffentlichung bei Validierungsfehlern
- Protokolle und Artefakte für jeden Automationslauf
- Zustandsdatei gegen doppelte Bestellverarbeitung

Die produktiven Abläufe sollten erst nach einem erfolgreichen Test mit wenigen Datensätzen aktiviert werden.