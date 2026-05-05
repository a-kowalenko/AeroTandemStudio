# Release Command Cheat Sheet

## Grundlagen

- Build-Level:
  - `build` = erhoeht nur Build-Komponente
  - `patch` = Bugfix-Release
  - `minor` = Feature-Release
  - `major` = Breaking-Release
  - `none` = kein numerischer Bump
- `setup` = erstellt zusaetzlich Installer/Package
- Pre-Release setzen:
  - `--prerelease alpha|beta|rc|alpha.1|beta.3|rc.2`
- Pre-Release entfernen:
  - `--clear-prerelease`
- Metadata setzen/entfernen:
  - `--metadata build.42`
  - `--clear-metadata`

## Empfohlene Standardbefehle

- Lokaler Testbuild (nur App, kein Installer):
  - `python build.py`
- Release-Build mit Installer:
  - `python build.py build setup`
- Patch-Release (stabil):
  - `python build.py patch --clear-prerelease --clear-metadata setup`
- Minor-Release (stabil):
  - `python build.py minor --clear-prerelease --clear-metadata setup`
- Major-Release (stabil):
  - `python build.py major --clear-prerelease --clear-metadata setup`

## Pre-Release Workflows

### Alpha

- Neue Alpha nach Minor-Bump:
  - `python build.py minor --prerelease alpha setup`
- Naechste Alpha-Iteration (Build hochzaehlen):
  - `python build.py build --prerelease alpha setup`
- Gezielte Alpha-Nummer setzen:
  - `python build.py none --prerelease alpha.3 setup`

### Beta

- Von Alpha auf Beta wechseln (ohne numerischen Bump):
  - `python build.py none --prerelease beta setup`
- Beta-Iteration erhoehen (Build + prerelease setzen):
  - `python build.py build --prerelease beta.2 setup`
- Direkt auf beta.3 setzen:
  - `python build.py none --prerelease beta.3 setup`

### RC

- Von Beta auf RC wechseln:
  - `python build.py none --prerelease rc.1 setup`
- RC-Iteration:
  - `python build.py build --prerelease rc.2 setup`

### Stabilisieren (GA)

- Pre-Release entfernen, stabile Version erzeugen:
  - `python build.py none --clear-prerelease --clear-metadata setup`
- Oder mit neuem Patch direkt stabil:
  - `python build.py patch --clear-prerelease --clear-metadata setup`

## Nuetzliche Varianten

- Nur Pre-Release aendern, sonst nichts:
  - `python build.py none --prerelease beta.4`
- Nur Metadata aendern:
  - `python build.py none --metadata build.20260505`
- Metadata loeschen:
  - `python build.py none --clear-metadata`
- Pre-Release + Metadata zusammen:
  - `python build.py none --prerelease rc.1 --metadata build.88 setup`

## Legacy-Kompatibilitaet (weiterhin unterstuetzt)

- `python build.py major alpha setup`
- `python build.py major -alpha setup`

Empfehlung: kuenftig bevorzugt die Flag-Variante (`--prerelease ...`) nutzen, weil klarer und weniger fehleranfaellig.

## Tagging fuer GitHub Release

Da der Workflow auf `v*` reagiert, funktionieren zum Beispiel:

- `v0.2.0-alpha`
- `v5.9-beta.3`
- `v1.4.0`

Beispiel:

- `git tag v1.3.0-rc.1`
- `git push origin v1.3.0-rc.1`

Releases bleiben dabei normale Releases (nicht als GitHub "Pre-release" markiert).

## Praxisempfehlung

- Entwicklung: `alpha`
- Feature-Freeze/Test: `beta`
- Release-Kandidat: `rc`
- Final: `--clear-prerelease`
