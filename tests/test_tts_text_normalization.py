"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed software:
- GNU Affero General Public License v3 (AGPL-3.0) for open-source use
- Commercial License for proprietary use

You should have received a copy of both licenses with this software.
For more information, see LICENSE and LICENSE-COMMERCIAL files.

IMPORTANT: This software cannot be rebranded or have attribution removed.
See NOTICE file for complete terms.

Repository: https://github.com/KR8MER/eas-station
"""

"""Tests for _normalize_text_for_tts() in app_utils/eas.py.

Covers:
  - Whitespace/punctuation normalization (ellipsis, newlines, multi-space)
  - NWS-specific normalizations (timezone slash, ST. expansion, state codes)
  - Indiana county+state-code disambiguation
  - Acronym expansion (NWS, NOAA, timezones, state codes)
  - Lowercase final pass
  - Fringe/edge cases
  - Various NWS product types: watch, tornado warning, winter storm,
    flash flood warning, special weather statement
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Stub heavy dependencies so only the normalization logic is exercised.
_STUBS = [
    'flask', 'flask_sqlalchemy',
    'sqlalchemy', 'sqlalchemy.orm',
    'pytz',
    'azure', 'azure.cognitiveservices', 'azure.cognitiveservices.speech',
    'pyttsx3', 'pydub',
    'RPi', 'RPi.GPIO', 'gpiozero',
    'psutil',
    'app_core', 'app_core.models', 'app_core.tts_settings',
]
for _mod in _STUBS:
    sys.modules.setdefault(_mod, MagicMock())


def _get_normalize():
    """Return _normalize_text_for_tts with the DB pronunciation layer stubbed."""
    with patch('app_utils.eas._load_pronunciation_rules', return_value=[]):
        from app_utils.eas import _normalize_text_for_tts
    return _normalize_text_for_tts


# ---------------------------------------------------------------------------
# Whitespace / punctuation normalization
# ---------------------------------------------------------------------------

class TestEllipsisNormalization(unittest.TestCase):
    """NWS uses '...' as a clause/sentence separator throughout products."""

    def setUp(self):
        self.n = _get_normalize()

    def test_ellipsis_becomes_sentence_break(self):
        result = self.n('TORNADO WARNING...IN EFFECT UNTIL 3 PM')
        self.assertNotIn('...', result)
        self.assertIn('. ', result)

    def test_leading_ellipsis_stripped(self):
        result = self.n('...TORNADO WARNING FOR JEFFERSON COUNTY...')
        self.assertNotIn('...', result)

    def test_four_dots_treated_as_ellipsis(self):
        result = self.n('WARNING....UNTIL 3 PM')
        self.assertNotIn('....', result)

    def test_ellipsis_in_time_context(self):
        # "...1100 PM EDT..." — time expansion runs first, then ellipsis
        result = self.n('...1100 PM EDT...')
        self.assertNotIn('...', result)
        self.assertIn('eleven', result)

    def test_regular_sentence_period_preserved(self):
        # A single period (end of sentence) must not be affected.
        result = self.n('THIS IS A SENTENCE. ANOTHER SENTENCE.')
        self.assertIn('. ', result)


class TestNewlineNormalization(unittest.TestCase):
    """Newlines become pauses so TTS does not run sections together."""

    def setUp(self):
        self.n = _get_normalize()

    def test_single_newline_becomes_comma(self):
        result = self.n('LINE ONE\nLINE TWO')
        self.assertNotIn('\n', result)
        self.assertIn(', ', result)

    def test_double_newline_becomes_period(self):
        result = self.n('PARAGRAPH ONE\n\nPARAGRAPH TWO')
        self.assertNotIn('\n', result)
        # double newline → ". " which is then lowercased
        self.assertIn('. ', result)

    def test_triple_newline_treated_as_double(self):
        result = self.n('A\n\n\nB')
        self.assertNotIn('\n', result)

    def test_mixed_newlines(self):
        result = self.n('SECTION ONE\n\nSECTION TWO\nLINE IN SECTION')
        self.assertNotIn('\n', result)

    def test_newline_between_county_names(self):
        # County names separated by newlines should get comma pauses.
        result = self.n('ALLEN\nBLACKFORD\nCASS')
        self.assertIn(',', result)
        self.assertNotIn('\n', result)


class TestMultipleSpaceNormalization(unittest.TestCase):
    """NWS uses multiple spaces for columnar county lists."""

    def setUp(self):
        self.n = _get_normalize()

    def test_two_spaces_become_comma(self):
        result = self.n('KOSCIUSKO  ST. JOSEPH')
        self.assertIn(',', result)

    def test_many_spaces_become_single_comma(self):
        # "KOSCIUSKO             ST. JOSEPH" → "kosciusko, saint joseph"
        result = self.n('KOSCIUSKO             ST. JOSEPH')
        self.assertIn('kosciusko, saint joseph', result)

    def test_single_space_not_affected(self):
        result = self.n('ALLEN BLACKFORD')
        self.assertNotIn(',', result)

    def test_tab_separator_becomes_comma(self):
        result = self.n('ALLEN\tBLACKFORD')
        self.assertIn(',', result)
        self.assertNotIn('\t', result)

    def test_county_state_code_single_space_preserved(self):
        # "CASS IN" has a single space — must not be collapsed to "CASS, IN"
        # before Indiana disambiguation fires.
        result = self.n('CASS IN DE KALB')
        self.assertIn('cass indiana', result)

    def test_columnar_county_with_state_code(self):
        # "CASS IN      DE KALB" — multi-space after state code is fine;
        # the single space between CASS and IN is preserved for disambiguation.
        result = self.n('CASS IN      DE KALB')
        self.assertIn('cass indiana', result)
        self.assertIn('de kalb', result)


# ---------------------------------------------------------------------------
# Lowercase final pass
# ---------------------------------------------------------------------------

class TestLowercasePass(unittest.TestCase):
    """All text must be lowercase after normalization."""

    def setUp(self):
        self.n = _get_normalize()

    def test_all_caps_lowercased(self):
        result = self.n('TORNADO WARNING')
        self.assertEqual(result, result.lower())

    def test_mixed_case_lowercased(self):
        result = self.n('Tornado Warning')
        self.assertEqual(result, result.lower())

    def test_expanded_acronyms_lowercased(self):
        result = self.n('NWS ISSUED A WARNING EDT')
        self.assertIn('national weather service', result)
        self.assertIn('eastern daylight time', result)
        self.assertEqual(result, result.lower())

    def test_saint_expansion_lowercased(self):
        result = self.n('ST. JOSEPH COUNTY')
        self.assertIn('saint joseph', result)
        self.assertNotIn('Saint', result)  # no mixed-case residue

    def test_state_code_expansion_lowercased(self):
        result = self.n('CASS MI ALLEN OH')
        self.assertIn('cass michigan', result)
        self.assertIn('allen ohio', result)

    def test_empty_string_unchanged(self):
        self.assertEqual(self.n(''), '')

    def test_whitespace_only(self):
        # Whitespace-only input should survive gracefully.
        result = self.n('   \n\n\t  ')
        self.assertEqual(result, result.lower())


# ---------------------------------------------------------------------------
# Timezone slash notation
# ---------------------------------------------------------------------------

class TestSlashAlternateTimezone(unittest.TestCase):
    """NWS alternate-timezone slash notation: /5 PM CDT/ → 5 PM CDT."""

    def setUp(self):
        self.n = _get_normalize()

    def test_slash_notation_stripped(self):
        result = self.n('UNTIL 6 PM EDT /5 PM CDT/ THIS EVENING')
        self.assertNotIn('/', result)

    def test_cdt_expanded(self):
        result = self.n('UNTIL 6 PM EDT /5 PM CDT/ THIS EVENING')
        self.assertIn('central daylight time', result)

    def test_edt_expanded(self):
        result = self.n('UNTIL 6 PM EDT /5 PM CDT/ THIS EVENING')
        self.assertIn('eastern daylight time', result)

    def test_slash_with_colon_time(self):
        result = self.n('UNTIL 6:00 PM EDT /5:00 PM CDT/ THIS EVENING')
        self.assertNotIn('/', result)
        self.assertIn('central daylight time', result)

    def test_slash_with_standard_time(self):
        result = self.n('UNTIL 11 PM EST /10 PM CST/')
        self.assertNotIn('/', result)
        self.assertIn('central standard time', result)
        self.assertIn('eastern standard time', result)


# ---------------------------------------------------------------------------
# ST. → Saint
# ---------------------------------------------------------------------------

class TestSaintAbbreviation(unittest.TestCase):

    def setUp(self):
        self.n = _get_normalize()

    def test_st_joseph_indiana(self):
        result = self.n('KOSCIUSKO ST. JOSEPH IN NORTHERN INDIANA')
        self.assertNotIn('st.', result)
        self.assertIn('saint joseph', result)

    def test_st_joseph_michigan(self):
        result = self.n('CASS MI HILLSDALE ST. JOSEPH MI')
        self.assertIn('saint joseph', result)

    def test_st_louis(self):
        result = self.n('CITIES OF ST. LOUIS AND CHICAGO')
        self.assertIn('saint louis', result)

    def test_lowercase_input(self):
        result = self.n('st. Joseph county')
        self.assertIn('saint joseph', result)

    def test_st_without_period_not_expanded(self):
        # "ST" without a period must be left alone (it may be a state code
        # or part of a place name like "STREET").
        result = self.n('ST CLAIR SHORES')
        self.assertNotIn('saint clair', result)


# ---------------------------------------------------------------------------
# State-code acronym expansion
# ---------------------------------------------------------------------------

class TestStateCodeExpansion(unittest.TestCase):
    """MI → michigan, OH → ohio (county disambiguation markers)."""

    def setUp(self):
        self.n = _get_normalize()

    def test_mi_expanded(self):
        result = self.n('BERRIEN BRANCH CASS MI HILLSDALE')
        self.assertIn('cass michigan', result)

    def test_oh_expanded(self):
        result = self.n('ALLEN OH DEFIANCE FULTON OH HENRY')
        self.assertIn('allen ohio', result)
        self.assertIn('fulton ohio', result)

    def test_miami_not_broken(self):
        """Word-boundary check: MI must not mangle MIAMI."""
        result = self.n('MIAMI NOBLE PULASKI')
        self.assertIn('miami', result)
        self.assertNotIn('miachigan', result)

    def test_ohio_word_not_double_expanded(self):
        """The full word OHIO must not be changed."""
        result = self.n('IN OHIO THIS WATCH INCLUDES 8 COUNTIES IN NORTHWEST OHIO')
        self.assertIn('in ohio', result)

    def test_michigan_word_not_double_expanded(self):
        """The full word MICHIGAN must not be changed."""
        result = self.n('IN MICHIGAN THIS WATCH INCLUDES 5 COUNTIES')
        self.assertIn('in michigan', result)

    def test_in_preposition_untouched(self):
        result = self.n('IN EFFECT IN INDIANA IN NORTH CENTRAL INDIANA')
        self.assertIn('in effect', result)
        self.assertIn('in indiana', result)


# ---------------------------------------------------------------------------
# Indiana county+state-code disambiguation
# ---------------------------------------------------------------------------

class TestIndianaCountyDisambiguation(unittest.TestCase):
    """IN → Indiana only when preceded by a recognised Indiana county name."""

    def setUp(self):
        self.n = _get_normalize()

    def test_allen_in_expanded(self):
        result = self.n('ADAMS ALLEN IN BLACKFORD CASS IN DE KALB')
        self.assertIn('allen indiana', result)

    def test_cass_in_expanded(self):
        result = self.n('CASS IN DE KALB')
        self.assertIn('cass indiana', result)

    def test_fulton_in_expanded(self):
        result = self.n('ELKHART FULTON IN GRANT HUNTINGTON')
        self.assertIn('fulton indiana', result)

    def test_whitley_in_michigan_not_expanded(self):
        """'WHITLEY IN MICHIGAN' — IN is a section preposition, not state code."""
        result = self.n('WABASH WELLS WHITE WHITLEY IN MICHIGAN')
        self.assertNotIn('whitley indiana', result)
        self.assertIn('in michigan', result)

    def test_in_before_northern_not_expanded(self):
        result = self.n('KOSCIUSKO ST. JOSEPH IN NORTHERN INDIANA')
        self.assertNotIn('indiana northern', result)

    def test_in_before_north_not_expanded(self):
        result = self.n('24 COUNTIES IN NORTH CENTRAL INDIANA')
        self.assertIn('in north', result)

    def test_in_effect_not_expanded(self):
        result = self.n('WATCH IN EFFECT UNTIL 6 PM EDT')
        self.assertIn('in effect', result)

    def test_ohio_county_indiana(self):
        """OHIO is both a state and an Indiana county — test the county form."""
        # "OHIO IN DEARBORN" — OHIO county in Indiana followed by another county
        result = self.n('OHIO IN DEARBORN')
        self.assertIn('ohio indiana', result)

    def test_ohio_county_state_not_confused(self):
        """'OHIO IN NORTHWEST' — should not expand (NORTHWEST in blocklist)."""
        result = self.n('OHIO IN NORTHWEST OHIO')
        self.assertNotIn('ohio indiana', result)

    def test_multiple_disambiguations(self):
        result = self.n('ADAMS ALLEN IN BLACKFORD CASS IN DE KALB FULTON IN GRANT')
        self.assertIn('allen indiana', result)
        self.assertIn('cass indiana', result)
        self.assertIn('fulton indiana', result)

    def test_jefferson_in_kentucky_not_expanded(self):
        """JEFFERSON IN KENTUCKY — KENTUCKY is in the preposition-after blocklist."""
        result = self.n('JEFFERSON COUNTY IN KENTUCKY')
        self.assertNotIn('jefferson indiana', result)

    def test_grant_in_northern_not_expanded(self):
        """'GRANT IN NORTHERN' — classic false-positive from NWS text."""
        result = self.n('GRANT IN NORTHERN INDIANA')
        self.assertNotIn('grant indiana', result)


# ---------------------------------------------------------------------------
# AFD / AFB / ARB expansion
# ---------------------------------------------------------------------------

class TestFacilityAbbreviations(unittest.TestCase):

    def setUp(self):
        self.n = _get_normalize()

    def test_afd_expanded_to_air_force_base(self):
        result = self.n('CITIES OF GRISSOM AFD, AKRON')
        self.assertIn('air force base', result)
        self.assertNotIn('air force depot', result)

    def test_afb_expanded(self):
        result = self.n('NEAR SCOTT AFB')
        self.assertIn('air force base', result)

    def test_arb_expanded(self):
        result = self.n('NEAR GRISSOM ARB')
        self.assertIn('air reserve base', result)


# ---------------------------------------------------------------------------
# Time expansion
# ---------------------------------------------------------------------------

class TestTimeExpansion(unittest.TestCase):

    def setUp(self):
        self.n = _get_normalize()

    def test_compact_1100_pm(self):
        result = self.n('UNTIL 1100 PM EDT')
        self.assertIn('eleven', result)
        self.assertNotIn('1100', result)

    def test_compact_0930_am(self):
        result = self.n('ISSUED 0930 AM CDT')
        self.assertIn('nine', result)
        self.assertIn('thirty', result)

    def test_colon_time_1130_am(self):
        result = self.n('AT 11:30 AM CST')
        self.assertIn('eleven', result)
        self.assertIn('thirty', result)

    def test_midnight_1200_am(self):
        result = self.n('EXPIRES 1200 AM EST')
        self.assertIn('twelve', result)

    def test_noon_1200_pm(self):
        result = self.n('UNTIL 1200 PM EDT')
        self.assertIn('twelve', result)

    def test_bare_hour_passes_through(self):
        # "6 PM" (no minutes) is not expanded — TTS reads it naturally.
        result = self.n('UNTIL 6 PM EDT')
        self.assertIn('6', result)
        self.assertIn('eastern daylight time', result)


# ---------------------------------------------------------------------------
# Full NWS product excerpts
# ---------------------------------------------------------------------------

class TestFullWatchText(unittest.TestCase):
    """Severe Thunderstorm Watch — the original sample text."""

    def setUp(self):
        self.n = _get_normalize()

    def test_full_watch_excerpt(self):
        text = (
            'THE NATIONAL WEATHER SERVICE HAS ISSUED SEVERE THUNDERSTORM WATCH 78 '
            'IN EFFECT UNTIL 6 PM EDT /5 PM CDT/ THIS EVENING FOR THE FOLLOWING AREAS '
            'IN INDIANA THIS WATCH INCLUDES 24 COUNTIES IN NORTH CENTRAL INDIANA '
            'KOSCIUSKO ST. JOSEPH IN NORTHERN INDIANA ADAMS ALLEN IN BLACKFORD CASS IN '
            'DE KALB ELKHART FULTON IN GRANT HUNTINGTON JAY LA PORTE LAGRANGE MARSHALL '
            'MIAMI NOBLE PULASKI STARKE STEUBEN WABASH WELLS WHITE WHITLEY '
            'IN MICHIGAN THIS WATCH INCLUDES 5 COUNTIES IN SOUTHWEST MICHIGAN '
            'BERRIEN BRANCH CASS MI HILLSDALE ST. JOSEPH MI '
            'IN OHIO THIS WATCH INCLUDES 8 COUNTIES IN NORTHWEST OHIO '
            'ALLEN OH DEFIANCE FULTON OH HENRY PAULDING PUTNAM VAN WERT WILLIAMS '
            'THIS INCLUDES THE CITIES OF GRISSOM AFD, AKRON, MIAMI'
        )
        result = self.n(text)

        self.assertEqual(result, result.lower())
        self.assertIn('eastern daylight time', result)
        self.assertIn('central daylight time', result)
        self.assertNotIn('/5 pm cdt/', result)
        self.assertIn('saint joseph', result)
        self.assertIn('cass michigan', result)
        self.assertIn('allen ohio', result)
        self.assertIn('fulton ohio', result)
        self.assertIn('air force base', result)
        self.assertIn('allen indiana', result)
        self.assertIn('cass indiana', result)
        self.assertIn('fulton indiana', result)
        self.assertIn('miami', result)        # not corrupted by MI→michigan
        self.assertIn('in effect', result)
        self.assertIn('in indiana', result)
        self.assertIn('in michigan', result)
        self.assertIn('in ohio', result)


class TestTornadoWarning(unittest.TestCase):
    """Tornado Warning product — bullet format, VTEC-style text, lat/lon coords."""

    def setUp(self):
        self.n = _get_normalize()

    # Realistic NWS Tornado Warning description (abridged)
    _PRODUCT = (
        'BULLETIN - IMMEDIATE BROADCAST REQUESTED\n'
        'TORNADO WARNING\n'
        'NATIONAL WEATHER SERVICE LOUISVILLE KY\n'
        '200 PM EDT MON MAR 31 2026\n'
        '\n'
        'THE NATIONAL WEATHER SERVICE IN LOUISVILLE HAS ISSUED A\n'
        '\n'
        '* TORNADO WARNING FOR...\n'
        '  JEFFERSON COUNTY IN KENTUCKY...\n'
        '  UNTIL 215 PM EDT\n'
        '\n'
        '* AT 157 PM EDT...NATIONAL WEATHER SERVICE METEOROLOGISTS DETECTED A\n'
        '  TORNADO ON RADAR NEAR PLEASURE RIDGE PARK...MOVING NORTHEAST AT\n'
        '  30 MPH.\n'
        '\n'
        '  HAZARD...TORNADO.\n'
        '  SOURCE...RADAR INDICATED ROTATION.\n'
        '  IMPACT...FLYING DEBRIS WILL BE DANGEROUS TO THOSE CAUGHT WITHOUT\n'
        '  SHELTER.\n'
        '\n'
        'TAKE COVER NOW!\n'
    )

    def test_no_raw_newlines_remain(self):
        result = self.n(self._PRODUCT)
        self.assertNotIn('\n', result)

    def test_no_raw_ellipsis_remain(self):
        result = self.n(self._PRODUCT)
        self.assertNotIn('...', result)

    def test_all_lowercase(self):
        result = self.n(self._PRODUCT)
        self.assertEqual(result, result.lower())

    def test_edt_expanded(self):
        result = self.n(self._PRODUCT)
        self.assertIn('eastern daylight time', result)

    def test_nws_expanded(self):
        result = self.n(self._PRODUCT)
        self.assertIn('national weather service', result)

    def test_jefferson_county_in_kentucky_not_disambiguated(self):
        """JEFFERSON IN KENTUCKY must not produce 'jefferson indiana'."""
        result = self.n(self._PRODUCT)
        self.assertNotIn('jefferson indiana', result)

    def test_time_expanded(self):
        result = self.n(self._PRODUCT)
        # "200 PM" → "two o'clock PM" (compact time expansion)
        self.assertIn("two o'clock", result)


class TestWinterStormWarning(unittest.TestCase):
    """Winter Storm Warning — bullet format, standard/daylight time mix."""

    def setUp(self):
        self.n = _get_normalize()

    _PRODUCT = (
        'WINTER STORM WARNING IN EFFECT FROM 6 PM THIS EVENING TO\n'
        '6 PM EST THURSDAY\n'
        '\n'
        '* WHAT...HEAVY SNOW EXPECTED. TOTAL SNOW ACCUMULATIONS OF 8 TO 12\n'
        '  INCHES.\n'
        '\n'
        '* WHERE...PORTIONS OF NORTHERN INDIANA AND SOUTHWEST MICHIGAN.\n'
        '\n'
        '* WHEN...FROM 6 PM THIS EVENING TO 6 PM EST THURSDAY.\n'
        '\n'
        '* IMPACTS...TRAVEL COULD BE VERY DIFFICULT TO IMPOSSIBLE.\n'
        '\n'
        'PRECAUTIONARY/PREPAREDNESS ACTIONS...\n'
        '\n'
        'A WINTER STORM WARNING MEANS SEVERE WINTER WEATHER CONDITIONS ARE\n'
        'EXPECTED OR OCCURRING. SIGNIFICANT AMOUNTS OF SNOW...SLEET AND ICE\n'
        'ARE EXPECTED THAT WILL MAKE TRAVEL VERY HAZARDOUS OR IMPOSSIBLE.\n'
    )

    def test_no_raw_newlines(self):
        result = self.n(self._PRODUCT)
        self.assertNotIn('\n', result)

    def test_no_ellipsis(self):
        result = self.n(self._PRODUCT)
        self.assertNotIn('...', result)

    def test_all_lowercase(self):
        result = self.n(self._PRODUCT)
        self.assertEqual(result, result.lower())

    def test_est_expanded(self):
        result = self.n(self._PRODUCT)
        self.assertIn('eastern standard time', result)

    def test_precautionary_slash_not_treated_as_timezone(self):
        """PRECAUTIONARY/PREPAREDNESS contains a slash but is not a timezone."""
        result = self.n(self._PRODUCT)
        self.assertIn('precautionary', result)
        self.assertIn('preparedness', result)


class TestFlashFloodWarning(unittest.TestCase):
    """Flash Flood Warning — county in state notation, bulletin header."""

    def setUp(self):
        self.n = _get_normalize()

    _PRODUCT = (
        'FLASH FLOOD WARNING\n'
        'NATIONAL WEATHER SERVICE INDIANAPOLIS IN\n'
        '815 PM EDT MON MAR 31 2026\n'
        '\n'
        'THE NATIONAL WEATHER SERVICE IN INDIANAPOLIS HAS ISSUED A\n'
        '\n'
        '* FLASH FLOOD WARNING FOR...\n'
        '  SOUTHERN MARION COUNTY IN CENTRAL INDIANA...\n'
        '  UNTIL 1015 PM EDT.\n'
        '\n'
        '* AT 810 PM EDT...EMERGENCY MANAGEMENT REPORTED WIDESPREAD FLOODING\n'
        '  OF ROADS AND LOW LYING AREAS NEAR INDIANAPOLIS.\n'
        '\n'
        'TURN AROUND...DONT DROWN!\n'
    )

    def test_no_raw_newlines(self):
        result = self.n(self._PRODUCT)
        self.assertNotIn('\n', result)

    def test_all_lowercase(self):
        result = self.n(self._PRODUCT)
        self.assertEqual(result, result.lower())

    def test_nws_expanded(self):
        result = self.n(self._PRODUCT)
        self.assertIn('national weather service', result)

    def test_indianapolis_in_not_disambiguated(self):
        """'INDIANAPOLIS IN' — IN here is a preposition, not Indiana state code."""
        # INDIANAPOLIS is not in the Indiana county list so it cannot fire.
        result = self.n(self._PRODUCT)
        self.assertNotIn('indianapolis indiana', result)

    def test_times_expanded(self):
        result = self.n(self._PRODUCT)
        # "815 PM" → "eight fifteen PM"
        self.assertIn('eight', result)
        # "1015 PM" → "ten fifteen PM"
        self.assertIn('ten', result)

    def test_edt_expanded(self):
        result = self.n(self._PRODUCT)
        self.assertIn('eastern daylight time', result)


class TestSpecialWeatherStatement(unittest.TestCase):
    """Special Weather Statement — shorter product, mixed county listing."""

    def setUp(self):
        self.n = _get_normalize()

    _PRODUCT = (
        'SPECIAL WEATHER STATEMENT\n'
        'NATIONAL WEATHER SERVICE CHICAGO IL\n'
        '1045 AM CDT SAT APR 1 2026\n'
        '\n'
        'AREAS AFFECTED...LAKE IN NORTHERN ILLINOIS...COOK...DUPAGE...\n'
        'KANE...KENDALL...WILL\n'
        '\n'
        'A STRONG THUNDERSTORM WILL AFFECT PORTIONS OF NORTHEASTERN\n'
        'ILLINOIS INCLUDING THE CITIES OF CHICAGO AND JOLIET.\n'
        '\n'
        'AT 1042 AM CDT...A STRONG THUNDERSTORM WAS LOCATED NEAR AURORA\n'
        'MOVING NORTHEAST AT 35 MPH.\n'
        '\n'
        'WIND GUSTS UP TO 50 MPH ARE POSSIBLE.\n'
    )

    def test_no_raw_newlines(self):
        result = self.n(self._PRODUCT)
        self.assertNotIn('\n', result)

    def test_cdt_expanded(self):
        result = self.n(self._PRODUCT)
        self.assertIn('central daylight time', result)

    def test_all_lowercase(self):
        result = self.n(self._PRODUCT)
        self.assertEqual(result, result.lower())

    def test_lake_in_northern_illinois_not_disambiguated(self):
        """'LAKE IN NORTHERN' — NORTHERN is in the preposition-after blocklist."""
        # LAKE is also an Indiana county, but IN is followed by NORTHERN.
        result = self.n(self._PRODUCT)
        self.assertNotIn('lake indiana', result)

    def test_time_1045_expanded(self):
        result = self.n(self._PRODUCT)
        self.assertIn('ten', result)
        self.assertIn('forty', result)


# ---------------------------------------------------------------------------
# Edge / fringe cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.n = _get_normalize()

    def test_empty_string(self):
        self.assertEqual(self.n(''), '')

    def test_only_ellipsis(self):
        result = self.n('...')
        self.assertNotIn('...', result)

    def test_only_newlines(self):
        result = self.n('\n\n\n')
        self.assertNotIn('\n', result)

    def test_only_spaces(self):
        result = self.n('   ')
        # Multiple spaces → ", " then lowercased — should not crash.
        self.assertIsInstance(result, str)

    def test_cass_appears_in_both_indiana_and_michigan_context(self):
        # One CASS IN (Indiana) and one CASS MI (Michigan) in the same text.
        result = self.n('CASS IN DE KALB ELKHART CASS MI HILLSDALE')
        self.assertIn('cass indiana', result)
        self.assertIn('cass michigan', result)

    def test_no_double_space_in_output(self):
        result = self.n('ALLEN  BLACKFORD  CASS')
        self.assertNotIn('  ', result)

    def test_noaa_acronym(self):
        result = self.n('ISSUED BY NOAA')
        self.assertIn('n.o.a.a.', result)

    def test_fema_acronym(self):
        result = self.n('COORDINATED WITH FEMA')
        self.assertIn('f.e.m.a.', result)

    def test_eas_acronym(self):
        result = self.n('EAS BROADCAST')
        self.assertIn('emergency alert system', result)

    def test_alaska_timezone(self):
        result = self.n('UNTIL 8 PM AKDT')
        self.assertIn('alaska daylight time', result)

    def test_hawaii_timezone(self):
        result = self.n('EXPIRES 10 PM HST')
        self.assertIn('hawaii standard time', result)

    def test_utc_timezone(self):
        result = self.n('VALID UNTIL 0000 UTC')
        self.assertIn('coordinated universal time', result)

    def test_precautionary_slash_preserved(self):
        # The slash in PRECAUTIONARY/PREPAREDNESS is NOT a timezone slash.
        result = self.n('PRECAUTIONARY/PREPAREDNESS ACTIONS')
        self.assertIn('precautionary', result)
        self.assertIn('preparedness', result)

    def test_rwt_expanded(self):
        result = self.n('THIS IS A RWT')
        self.assertIn('required weekly test', result)

    def test_rmt_expanded(self):
        result = self.n('THIS IS A RMT')
        self.assertIn('required monthly test', result)


# ---------------------------------------------------------------------------
# Database pronunciation dictionary (layer 4) outside a Flask app context
# ---------------------------------------------------------------------------

class TestPronunciationDictionaryRawSession(unittest.TestCase):
    """The CAP poller and OTA monitor generate broadcast audio without a Flask
    app context.  Layer 4 must load rules through the raw SQLAlchemy session
    those processes pass in, instead of silently skipping the dictionary
    (regression: rules applied in the web preview but never on-air).
    """

    @staticmethod
    def _fake_session(rules):
        session = MagicMock()
        (session.query.return_value
         .filter_by.return_value
         .order_by.return_value
         .all.return_value) = rules
        return session

    def test_rules_applied_from_raw_session(self):
        from app_utils.eas import _normalize_text_for_tts
        rule = MagicMock(
            original_text='Findlay', replacement_text='Find-lee', match_case=False
        )
        session = self._fake_session([rule])
        result = _normalize_text_for_tts('FINDLAY OH', db_session=session)
        self.assertIn('find-lee', result)
        self.assertNotIn('findlay', result)

    def test_session_forwarded_to_loader(self):
        import app_utils.eas as eas_mod
        sentinel = object()
        with patch.object(
            eas_mod, '_load_pronunciation_rules', return_value=[]
        ) as loader:
            eas_mod._normalize_text_for_tts('TEST TEXT', db_session=sentinel)
        loader.assert_called_once_with(sentinel)

    def test_loader_queries_provided_session(self):
        from app_utils.eas import _load_pronunciation_rules
        rule = MagicMock(
            original_text='Kalida', replacement_text='Ka-lye-da', match_case=False
        )
        session = self._fake_session([rule])
        rules = _load_pronunciation_rules(session)
        self.assertEqual(rules, [('Kalida', 'Ka-lye-da', False)])
        session.query.return_value.filter_by.assert_called_once_with(enabled=True)


if __name__ == '__main__':
    unittest.main()
