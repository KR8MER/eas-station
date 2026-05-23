# TTS Text Normalization & Pronunciation Guide

EAS Station™ converts raw CAP/SAME alert text into natural spoken language before
sending it to the TTS engine.  The pipeline is entirely automatic, but operators
can extend it with custom pronunciation rules for their coverage area.

---

## The Four-Layer Pipeline

Text passes through four layers in order every time an alert is narrated.

### Layer 1 — Time Expansion

Compact clock times are converted to fully-spoken equivalents so every TTS
backend gives the same natural result regardless of how it handles digits.

| Input | Output |
|-------|--------|
| `1100 PM` | eleven o'clock PM |
| `0930 AM` | nine thirty AM |
| `11:30 PM` | eleven thirty PM |
| `12:00 PM` | twelve o'clock PM |

Both four-digit compact format (`HHMM AM/PM`) and colon-separated format
(`H:MM AM/PM`) are handled.

---

### Layer 2 — NWS-Specific Cleanup

Three rules handle formatting conventions unique to NOAA/NWS alert text.

#### 2a. Alternate-Timezone Slash Notation

NWS watches express deadlines in two timezones using slashes around the second
one:

```
…UNTIL 6 PM EDT /5 PM CDT/ THIS EVENING…
```

The slashes are stripped so TTS reads `5 PM CDT` naturally.  The timezone
abbreviation (`CDT`) is then expanded to its full name by Layer 3.

**Result:** `…UNTIL 6 PM Eastern Daylight Time  5 PM Central Daylight Time  THIS EVENING…`

#### 2b. Saint Abbreviation

`ST.` is expanded to *Saint* before proper nouns so TTS does not say
"Street Joseph" or "St Joseph".

| Input | Output |
|-------|--------|
| `ST. JOSEPH` | Saint JOSEPH |
| `ST. LOUIS` | Saint LOUIS |
| `ST. CLAIR` | Saint CLAIR |

#### 2c. Indiana County-Name Disambiguation

NWS watches append the two-letter state code `IN` immediately after a county
name that appears in more than one watch state:

```
ADAMS ALLEN IN BLACKFORD CASS IN DE KALB ELKHART FULTON IN GRANT…
```

Here `ALLEN IN`, `CASS IN`, and `FULTON IN` identify Allen, Cass, and Fulton
counties in **Indiana**, distinguishing them from same-named counties in Ohio
(`ALLEN OH`) or Michigan (`CASS MI`).

TTS engines read bare `IN` as the English preposition "in", which is
ambiguous.  The pipeline expands it to *Indiana* using two guards:

1. **Positive match** — the word immediately before `IN` must be a recognised
   Indiana county name (all 92 counties, single-word NWS spellings).
2. **Negative lookahead** — the word after `IN` must **not** be a directional
   word (`NORTH`, `NORTHWEST`, …), a state name (`INDIANA`, `MICHIGAN`,
   `OHIO`, …), or a common English function word (`THE`, `A`, `EFFECT`,
   `COUNTIES`, `FOLLOWING`, …) that would indicate `IN` is a preposition.

| Input | Output | Reason |
|-------|--------|--------|
| `ALLEN IN BLACKFORD` | ALLEN Indiana BLACKFORD | ALLEN is an Indiana county; BLACKFORD is not excluded |
| `CASS IN DE KALB` | CASS Indiana DE KALB | CASS is an Indiana county |
| `FULTON IN GRANT` | FULTON Indiana GRANT | FULTON is an Indiana county |
| `GRANT IN NORTHERN INDIANA` | *(unchanged)* | NORTHERN is in the exclusion list |
| `WHITLEY IN MICHIGAN` | *(unchanged)* | MICHIGAN is in the exclusion list |
| `IN EFFECT` | *(unchanged)* | no preceding county name |
| `IN INDIANA` | *(unchanged)* | no preceding county name |

> **Multi-word county names** (La Porte, De Kalb, St. Joseph) are not in the
> single-word county list.  If a multi-word Indiana county needs a state-code
> expansion, add a custom rule in the Pronunciation Dictionary.

---

### Layer 3 — Built-In Acronym Table

Hard-coded, case-sensitive whole-word substitutions for uppercase tokens that
TTS engines consistently mispronounce.

#### Agency & System Names

| Token | Expansion |
|-------|-----------|
| `NWS` | National Weather Service |
| `EAS` | Emergency Alert System |
| `EBS` | Emergency Broadcast System |
| `FEMA` | F.E.M.A. |
| `NOAA` | N.O.A.A. |
| `IPAWS` | I.P.A.W.S. |

#### Event Codes

| Token | Expansion |
|-------|-----------|
| `RWT` | Required Weekly Test |
| `RMT` | Required Monthly Test |
| `EOM` | end of message |

#### US Timezone Abbreviations

| Token | Expansion |
|-------|-----------|
| `EDT` | Eastern Daylight Time |
| `CDT` | Central Daylight Time |
| `MDT` | Mountain Daylight Time |
| `PDT` | Pacific Daylight Time |
| `EST` | Eastern Standard Time |
| `CST` | Central Standard Time |
| `MST` | Mountain Standard Time |
| `PST` | Pacific Standard Time |
| `AKDT` | Alaska Daylight Time |
| `AKST` | Alaska Standard Time |
| `HST` | Hawaii Standard Time |
| `HAST` | Hawaii-Aleutian Standard Time |
| `HADT` | Hawaii-Aleutian Daylight Time |
| `UTC` | Coordinated Universal Time |
| `GMT` | Greenwich Mean Time |

#### NWS County-Disambiguation State Codes

| Token | Expansion | Notes |
|-------|-----------|-------|
| `MI` | Michigan | TTS reads bare `MI` as "my" |
| `OH` | Ohio | TTS reads bare `OH` as the interjection "oh" |

`IN` (Indiana) is handled by the smarter county-list logic in Layer 2 rather
than a simple replacement, because `IN` also appears as a very common English
preposition throughout the text.

#### Facility Abbreviations

| Token | Expansion |
|-------|-----------|
| `AFD` | Air Force Depot |

---

### Layer 4 — Custom Pronunciation Dictionary

User-managed word substitutions stored in the database.  Rules are applied
**longest-first** so multi-word entries (e.g. *Bellefontaine*) are never
accidentally masked by shorter ones (e.g. *Bell*).

Each rule has:

| Field | Description |
|-------|-------------|
| **Original text** | Matched as a whole word (regex `\b` boundary) |
| **Replacement (phonetic)** | What the TTS engine will say instead |
| **Note** | Optional documentation (not spoken) |
| **Case-sensitive** | Toggle exact-case matching (default: off) |
| **Enabled** | Disable a rule without deleting it |

---

## Pronunciation Preview Tool

The quickest way to verify normalization is the **Pronunciation Preview** panel
on the TTS Settings page (`/admin/tts`):

1. Paste any alert text — including full NWS watch descriptions — into the
   *Input Text* box.
2. Click **Normalize Text** to see the transformed output immediately.
3. Click **Normalize & Speak** to synthesize audio through your configured TTS
   provider and hear the result in the browser.

The output box shows exactly what the TTS engine will receive after all four
layers have been applied.

---

## Custom Pronunciation Rules

Navigate to **Admin → TTS Settings → Pronunciation Dictionary**
(`/admin/tts/pronunciation`) to manage custom rules.

### Common Use Cases

- **Local place names** that TTS mispronounces
  (e.g. `Versailles` → `Ver-SALES`, `Cairo` → `KAY-ro`)
- **Street or area abbreviations** used in alert text
- **Callsign or station IDs** that appear in generated text
- **Multi-word Indiana county names** that need state-code expansion
  (e.g. `LA PORTE IN` — add `LA PORTE IN` → `La Porte Indiana` as a custom rule)

### Tips

- Use the **Pronunciation Preview** to test a rule before saving it.
- Keep replacements phonetic rather than spelled-out where the TTS engine
  handles phonetics better than spelling (varies by provider).
- The case-sensitive option is rarely needed; leave it off unless a word has
  two meanings that differ only by capitalisation.
