# TikTok-Shop Buchupload über Libri-Listen

Diese Arbeitsmappe enthält eine lokale Pipeline, die aus gespeicherten Libri-Daten eine TikTok-Shop-Bulk-Upload-Datei für `Literatur und Kunst/Roman` erzeugt.

## Schnellstart

```powershell
& "C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\tiktok_libri_pipeline.py --workspace .
```

Die Ergebnisse landen unter `outputs/<timestamp>/`:

- `tiktok_upload_green.xlsx`: TikTok-Bulk-Upload-Datei mit nur freigegebenen Kandidaten.
- `candidate_report.csv`: Gesamtprüfung aller gefundenen Kandidaten.
- `review_hold.csv`: Titel, die vor Veröffentlichung manuell geprüft werden sollen.
- `rejects.csv`: Titel mit fehlenden Pflichtdaten, falschem Format oder nicht uploadfähigem Status.
- `upload_log.md`: kurze Upload-Zusammenfassung.

## Datenquellen

Die Pipeline liest aktuell:

- gespeicherte Mein.Libri-Produktdetailseiten als HTML, standardmäßig `*.html`
- den vorhandenen Libri-Bestseller-PDF-Export
- optional eine manuelle CSV per `--manual-csv <datei.csv>`

## Libri-Login und Bilder

Bitte keine Zugangsdaten in den Chat schreiben. Wenn ein Login gebraucht wird, kopiere `.env.example` nach `.env` und trage die Werte nur lokal ein.

Für das automatische Speichern von Libri-Produktdetailseiten werden benötigt:

- `LIBRI_CUSTOMER_NUMBER`
- `LIBRI_USERNAME`
- `LIBRI_PASSWORD`

Die Pipeline prüft Libri-Bildlinks zuerst anonym. Nur anonym erreichbare Bild-URLs können direkt in die TikTok-XLSX, weil TikTok beim Import keine Libri-Session-Cookies mitschicken kann.

Optional kann `LIBRI_COOKIE` in `.env` gesetzt werden. Das dient nur zur Diagnose: Wenn ein Bild mit Cookie erreichbar ist, aber anonym nicht, landet der Titel nicht im Green-Upload. Dann brauchen wir als Fallback TikTok-Mediencenter-Upload oder ein anderes öffentliches Bildhosting mit den erlaubten Libri-Bildern.

Produktdetailseiten nach ISBN/EAN aus einer CSV laden:

```powershell
& "C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\fetch_libri_product_pages.py `
  --isbn-csv inputs\first5_bestseller_manual.csv `
  --output-dir libri_product_pages `
  --limit 5
```

Danach die Upload-Datei mit den geladenen Libri-Seiten neu erzeugen:

```powershell
& "C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\tiktok_libri_pipeline.py `
  --workspace . `
  --detail-glob "libri_product_pages\*.html" `
  --bestseller-pdf none.pdf `
  --output-dir outputs\first5_from_libri
```

Für viele Titel am besten weitere Libri-Produktdetailseiten als HTML in einen Unterordner legen und so starten:

```powershell
& "C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\tiktok_libri_pipeline.py `
  --workspace . `
  --detail-glob "libri_product_pages\*.html" `
  --limit 100
```

## Manuelle CSV

Eine CSV kann diese Spalten enthalten:

```csv
title,author,subtitle,publisher,language,binding,release_date,pages,weight_g,stock,price,ean,product_group,blurb,author_bio,images
```

Mehrere Bild-URLs in `images` werden mit `|` getrennt.

## Upload-Regeln

- Das originale TikTok-Template wird nicht verändert; die Pipeline kopiert es in den Output.
- Daten werden ab Zeile 7 geschrieben, ohne Spalten oder Pflichtzeilen zu verändern.
- Als SKU wird `LIBRI-{EAN}` verwendet.
- Verbotene Template-Spalten wie `JAHR`, `Herausgeber`, `ISBN/ISSN`, `Übersetzer`, `Editor` und `Anzahl der Seiten` bleiben leer; diese Angaben stehen stattdessen in der Beschreibung.
- Risikotitel mit 18+, explizitem oder stark sexualisiertem Wording, Selbstverletzungs-/Suizidbezug oder fraglichen Bildern landen in `review_hold.csv` und nicht in der Upload-Datei.

## Seller-Center-Schritt

Die erzeugte Datei wird anschließend im Seller Center über `Products > Bulk listing` hochgeladen. Nach dem TikTok-Pre-Check nur veröffentlichen, wenn keine Fehler angezeigt werden; Fehlerberichte wieder in die Pipeline bzw. manuelle Datenkorrektur zurückführen.

## Bestellautomation TikTok -> Libri

Neue TikTok-Bestellungen werden mit `scripts/tiktok_order_automation.py` vorbereitet. Das Script liest entweder die TikTok Shop Open API oder testweise den neuesten Seller-Center-CSV-Export `Versandbereit Bestellung*.csv` aus Downloads.

Sicherer Test ohne API:

```powershell
.\scripts\prepare_order_from_latest_tiktok_csv.ps1
```

API-Einmalabruf:

```powershell
.\scripts\run_order_automation_once.ps1
```

Dauerlauf, der jeden Tag um 17:00 Uhr Berliner Zeit abruft:

```powershell
.\scripts\watch_order_automation_17uhr.ps1
```

Optional kann ein Windows-Task angelegt werden:

```powershell
.\scripts\install_order_automation_task.ps1
```

Dauerlauf fuer neue Bestellungen: prueft regelmaessig TikTok und bereitet nur neue, noch nicht verarbeitete Orders vor. Wenn nichts Neues da ist, wird kein leerer Output-Ordner erzeugt.

```powershell
.\scripts\watch_order_automation_new_orders.ps1 -PollMinutes 5
```

Optional als Windows-Task beim Login starten:

```powershell
.\scripts\install_order_automation_new_orders_task.ps1 -PollMinutes 5
```

Laptop-unabhaengiger Lauf ueber GitHub Actions: `.github/workflows/tiktok-order-automation.yml` prueft alle 15 Minuten und kann auch manuell ueber den Actions-Tab gestartet werden. Dafuer muessen in GitHub unter `Settings > Secrets and variables > Actions` diese Repository-Secrets gesetzt sein:

- `LIBRI_CUSTOMER_NUMBER`
- `TIKTOK_APP_KEY`
- `TIKTOK_APP_SECRET`
- `TIKTOK_ACCESS_TOKEN`
- `TIKTOK_SHOP_CIPHER` falls TikTok mehrere Shops fuer den Token zurueckgibt

Wenn neue Bestellungen vorbereitet werden, liegen die Dateien als Actions-Artifact `libri-order-packages-<run-id>` im jeweiligen Workflow-Lauf. Der Workflow commitet nur `.automation/order_state.json`, damit dieselbe Bestellung nicht bei jedem Poll erneut vorbereitet wird.

Die Ergebnisse liegen in `outputs/order_automation/<timestamp>/<order-id>/`:

- `libri_kundenbestellung_import.xlsx`: Libri-Import fuer die Artikel dieser einen TikTok-Bestellung.
- `kundenadresse.csv`: Lieferadresse fuer Libri Schritt 2 `Kundenbestellung > Direktversand zum Kunden`.
- `tiktok_order.json`: lokaler Audit-Snapshot.
- `orders_summary.csv`: Zusammenfassung des Laufs.

Wichtig: Diese Version schickt bei Libri noch keine finale Bestellung ab. Sie bereitet die Kundenbestellung pro TikTok-Order getrennt vor, damit nicht versehentlich mehrere Kunden in einem Libri-Warenkorb landen. Fuer Vollautomatik muessen wir einmal den Libri-Schritt `Kundenbestellung > Direktversand zum Kunden` im Browser mitschneiden und die Formularfelder verifizieren.

Probe fuer Libri Schritt 2, nur wenn der Libri-Warenkorb leer ist:

```powershell
& "C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" `
  scripts\libri_customer_checkout_probe.py `
  --order-dir "outputs\order_automation\<timestamp>\<order-id>"
```

Der Probe-Helfer legt Artikel in den Libri-Warenkorb, geht bis `Kundenbestellung`, speichert `libri_customer_step2.html` und stoppt vor dem finalen Absenden.
