# Translating NodeRC

NodeRC's interface is localized with **GNU gettext**, the standard format
supported by every major translation platform (Crowdin, Weblate, Transifex,
Lokalise, Pontoon) and desktop tool (Poedit, GNOME Translation Editor, Lokalize).

You do **not** need to touch Python to translate the app.

## Layout

```
locale/
├── nodeRC.pot                     # template: every translatable string, empty
├── en/LC_MESSAGES/nodeRC.po       # English (source language)
└── ru/LC_MESSAGES/nodeRC.po       # Russian
```

Each entry looks like this:

```po
#. Rename Group                ← English source, for context (do not translate)
msgid "ctx_rename_group"        ← stable key the code uses (never change)
msgstr "Переименовать группу"   ← your translation goes here
```

- **`msgid`** is a stable symbolic key. **Never edit it** — the code looks strings
  up by this key.
- The **`#.` comment** shows the English source so you know what to write.
- **`msgstr`** is the translation. Leave it empty to fall back to English.

Multi-line strings (the keyboard manual, the controls dialog) keep their HTML
markup — translate the visible text, keep the `<b>`, `<br/>`, `<li>` tags intact.

## Add a new language

1. Copy the template to a new locale folder, e.g. German (`de`):

   ```
   locale/de/LC_MESSAGES/nodeRC.po   ← copy of nodeRC.pot
   ```

2. Fill in the PO header (`Language: de`, `Last-Translator`, plural forms) and
   translate each `msgstr`. Poedit does all of this for you: *File → New from POT*,
   pick the language, point it at `nodeRC.pot`.

3. Run the app in that language (no build step needed):

   ```
   NODERC_LANG=de python nodeRC.py        # macOS/Linux
   $env:NODERC_LANG="de"; python nodeRC.py # Windows PowerShell
   ```

That's it — the editor compiles the catalog in memory on startup.

## Which language the app uses

`localization.py` picks the language in this order:

1. the `NODERC_LANG` environment variable, if it names an available locale;
2. otherwise the operating-system locale (e.g. `ru_RU` → `ru`), if available;
3. otherwise English.

Missing or empty translations always fall back to English, so a partial catalog
is perfectly fine to ship.

## Using a translation service

Point Crowdin / Weblate / Transifex at this folder:

- **Source file:** `locale/nodeRC.pot`
- **Translations:** `locale/<lang>/LC_MESSAGES/nodeRC.po`

The service handles the rest — translators work in a web UI and open pull
requests with updated `.po` files.

## Keeping the template in sync (maintainers)

When UI strings change, regenerate the template and merge it into each catalog
with standard gettext tools:

```bash
# refresh nodeRC.pot from the catalogs, then merge into each language
msgmerge --update locale/ru/LC_MESSAGES/nodeRC.po locale/nodeRC.pot
```

Pre-compiled `.mo` binaries are **not** committed — the app builds them in memory.
To emit `.mo` files for other gettext consumers:

```bash
python tools/compile_translations.py        # all languages
python tools/compile_translations.py ru     # one language
```
