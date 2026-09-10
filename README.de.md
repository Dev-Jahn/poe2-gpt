# POE2 GPT

[English](README.md) · [한국어](README.ko.md) · [Deutsch](README.de.md) · [Русский](README.ru.md) · [Português (Brasil)](README.pt-BR.md)

Ein selbst gehostetes ChatGPT-Plugin und ein MCP-Server für **Path of Exile 2**: Währungspreise, Ausrüstungssuche auf der offiziellen Handelsseite, private Path-of-Building-Berechnungen und Ausrüstungsverbesserungen innerhalb eines Budgets.

**Status: 0.13.0, experimentell.** Bis zu 38 MCP-Werkzeuge sind implementiert. Homelab-Bereitstellung, Authentifizierung und Tests mit dem eigenen Charakter erfolgen bei der Installation. Dieses Repository stellt weder einen gehosteten Endpunkt noch einen veröffentlichten ChatGPT-Verzeichniseintrag bereit.

## Funktionen

| Bereich | Bereits verfügbar |
|---|---|
| Währungspreise | Scout-JSON-API, 17 Kategoriegruppen, Ligaauswahl, Suche, Sammelbewertung, Cache und Quellenzeitangaben |
| Ausrüstungssuche | Typisierte Filter und Stat-Suche über die experimentelle `trade2`-Web-API der offiziellen Handelsseite |
| Gespeicherte Builds | Kontotag/Charaktername oder ChatGPT-Dateianhang, undurchsichtige Build-IDs, begrenzte Zusammenfassungen und passive Knoten |
| PoB-Berechnung | Festgelegte PoE2-PoB-Version in einem privaten Worker; Ausrüstungsvergleich und Anforderungsprüfung |
| Verbesserungen | Explizite Charakterwerte maximieren oder Kosten unter Budget- und Mindestwertvorgaben minimieren |

Standardliga: **Forbidden Rites**. Standardpreise: **Exalted Orbs pro Gegenstand**. Andere Saisons zuerst mit `list_leagues` prüfen. Ein integrierter PoE2DB-Katalog unterstützt englische und verifizierte koreanische Namen für Währungen, Gegenstandsbasis, Klassen und ausgewählte Fertigkeiten. `search_game_terms` liefert Namen und Quellen; fehlende Übersetzungen werden nicht geraten. Der Server benötigt keinen OpenAI-API-Schlüssel.

Die Engine kombiniert eine feste PoB2-Entwicklungsversion mit hashgeprüften Daten für 0.5.5. Spieler-DPS, DPS des ausgewählten Begleiters und ausdrücklich konfigurierter FullDPS werden getrennt ausgewiesen. Unbekannte passive Knoten und nicht berechnete Effekte verhindern bestätigte Upgrade-Empfehlungen. [Engine-Kompatibilität](docs/pob-engine.md).

Version 0.10 ergänzt kopierte Spirit-Vessel-Angriffe, Eigenschaften gezähmter Bestien, Martial-Artist-Mechaniken, die PoE2-Regeln für Leech und Impale sowie begrenzte Kampfszenarien für Ladungen und Mountain’s Teachings. Explizite [Berechnungsannahmen](docs/calculation-assumptions.md) gelten für den Ausgangsbuild und alle Ausrüstungskandidaten. Die [Ligaübersicht](docs/league-coverage.md) beschreibt den geprüften Umfang und verbleibende Grenzen (Englisch).

**MCP gibt niemals PoB-Codes oder XML-Rohdaten zurück.** Der private Importdienst und Worker verarbeiten die Originaldaten; ChatGPT erhält begrenzte Zusammenfassungen, IDs, geprüfte Zahlen und Statuswerte. Kein Dateiimport auf dem Serverhost erforderlich. Niemals einen PoB-Code in den Chat einfügen. Die eigene Verarbeitung von Anhängen durch ChatGPT liegt außerhalb der Kontrolle des Plugins. [Datengrenze](docs/pob-boundary.md).

## Schnellstart

Python 3.11+ ist erforderlich. Der PoB-Worker benötigt Linux und die festgelegte Lua-Laufzeit.

```bash
git clone https://github.com/Dev-Jahn/poe2-gpt.git
cd poe2-gpt
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m poe2_companion.check
```

Unter Windows die Umgebung mit `py -3 -m venv .venv` erstellen und `.venv\Scripts\python.exe` verwenden. Das Modul `poe2_companion` und der bisherige Befehl `poe2-companion` bleiben kompatibel.

Homelab-Dienst starten:

```bash
docker compose up -d --build
```

Der lokale Endpunkt lautet `http://127.0.0.1:8000/mcp`. Für ChatGPT im Web und auf dem Desktop einen kontogebundenen Secure MCP Tunnel oder einen kompatibel authentifizierten HTTPS-Endpunkt verwenden. Cloudflare kann OAuth bereitstellen; jede MCP-Instanz akzeptiert genau eine konfigurierte Identität. [Installation](docs/installation.md) · [Bereitstellung](docs/deployment.md).

Für einen Mac mini hinter einer Firewall gibt es die [Mac-mini- und Cloudflare-Anleitung](docs/mac-mini-cloudflare.md): native ARM64/amd64-Linux-Container, Managed OAuth mit JWT-Prüfung am Server und überwachte Dienste nach der Anmeldung.

[Mit zwei Freunden teilen](docs/friends.md): getrennte authentifizierte MCP-Instanzen, Build-Speicher, Handelssuchen und PoB-Worker auf einem Mac. Domain, Tunnel und öffentlicher Preis-Cache werden gemeinsam genutzt.

Enthalten sind `.codex-plugin/plugin.json`, `.mcp.json` und ein Git-basierter Marketplace-Katalog für lokale Plugin-Hosts. Eine lokale STDIO-Installation verbindet den Server nicht mit ChatGPT im Web. Die Veröffentlichung im öffentlichen Verzeichnis erfordert eine separate Prüfung. [Offizielle Spezifikation](https://developers.openai.com/plugins/build/plugins).

## Beispiele

- „Prüfe den Divine-Orb-Preis in Forbidden Rites in Exalted Orbs. Zeige Aktualität und Quelle.“
- „Finde seltene Helme mit mindestens 100 Leben unter 100 Exalted Orbs.“
- „Maximiere mit meiner importierten Build-ID und diesen Angeboten das Leben für höchstens 20 Divine Orbs; Kältewiderstand mindestens 75.“

Das letzte Beispiel benötigt den privaten PoB-Worker. Aktivierungsbedingungen stehen in der [Werkzeugreferenz](docs/tools.md).

## Grenzen

Scout liefert aggregierte Schätzwerte. Abrufzeit und ursprünglicher Marktbeobachtungszeitpunkt sind verschieden; Angebote können bereits verkauft sein. Die Handels-Web-API ist nicht GGGs dokumentierte OAuth-Entwickler-API. Sie kann sich ändern oder den Zugriff verweigern. Der Adapter respektiert Ratenlimits und stoppt bei Authentifizierungs- oder Challenge-Antworten.

PoB berechnet die gespeicherte aktive Konfiguration, keinen Live-Charakter. Nur Kombinationen mit bestandenen unterstützten Ausrüstungsprüfungen werden empfohlen; unbekannte Mechaniken bleiben `indeterminate`. Optimiert wird über gespeicherte Kandidaten, nicht den gesamten Markt. Der separate Gegenstandswerte-Optimierer berechnet weder PoB noch Charakter-DPS.

Kontotag und Charaktername oder eine in ChatGPT angehängte `.txt`-Datei werden unterstützt. Automatische Käufe und Export geänderter Builds bleiben nicht verfügbar. Docker-Betrieb und Kompatibilität des eigenen PoB müssen auf dem Zielhost geprüft werden.

## Entwicklung und Lizenz

```bash
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_release.py
```

Tests mit der echten Engine werden ohne optionale Laufzeit ausdrücklich übersprungen. [Mitwirken](CONTRIBUTING.md) · [Architektur](docs/architecture.md) · [Engine](docs/pob-engine.md) · [CI/CD](docs/releases.md) · [Sicherheit](SECURITY.md) · [Datenschutz](docs/privacy.md).

[MIT-Lizenz](LICENSE); Drittkomponenten und Marken siehe [NOTICE](NOTICE). Englisch ist maßgeblich. Die fünf README-Sprachen wurden anhand eines öffentlichen Sprachgemeinschaftsindikators und der Vorgabe, Koreanisch einzuschließen, gewählt; sie sind keine Länderrangliste. [Lokalisierung](docs/localization.md).

[Character integration / file attachments](docs/characters.md)
