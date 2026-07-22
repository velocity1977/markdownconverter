"""
Fixes math/Greek symbols that PDF text extraction garbles when a document
was typeset using the classic Adobe "Symbol" font.

THE PROBLEM
-----------
Many PDF producers (this affects a lot of NCERT-style math/science textbook
PDFs) render angle signs, Greek letters, radicals, etc. using the Symbol
font, and embed it with a common but PDF-viewer-only convention: shift every
character's normal Symbol-font byte value (0x00-0xFF) up by 0xF000 into the
Unicode Private Use Area. PDF viewers know to reverse this for on-screen
rendering, so the page looks correct -- but PyMuPDF (and any other text
extractor) just returns the raw PUA codepoint, which is meaningless outside
that font's private convention. That's why extracted text shows things like
"\\uf0d0" where the page visually shows "angle".

THE FIX
-------
This is NOT a per-document or guessed mapping. It's a fixed, two-step
translation through two industry-standard, publicly documented tables:

  1. PUA codepoint (0xF000 + byte) -> byte -> glyph name, via the
     "Adobe Symbol Encoding" -- the official, unchanging character layout of
     the Symbol font, standardized decades ago as one of the PDF spec's 14
     base fonts.
  2. Glyph name -> real Unicode character, via the "Adobe Glyph List" (AGL)
     -- the standard glyph-name-to-Unicode table used throughout the font
     and PDF tooling world.

The table below is the pre-computed result of chaining those two canonical
tables (cross-checked against reportlab's `_fontdata_enc_symbol` and
fontTools' `agl.AGL2UV` during development) -- not hand-typed guesses. A
handful of entries (the "parenlefttp/ex/bt" family etc.) are multi-piece
glyphs used to draw tall, multi-line brackets/parentheses/radicals around
stacked fractions; those have no single Unicode codepoint, so they're
manually collapsed to the plain single-line bracket character instead --
correct in meaning, just not the same tall-multi-line visual.

This file has NO new runtime dependencies (no reportlab/fontTools import) --
those were only used once, offline, to build the table below with
confidence rather than by hand-transcription, which risks silently
swapping one math symbol for a similar-looking wrong one (worse than
leaving it broken).
"""

import re

# PUA codepoint (0xF000 + Symbol-font byte) -> correct Unicode character.
SYMBOL_FONT_PUA_MAP = {
    0xF020: ' ',
    0xF021: '!',
    0xF022: '\u2200',
    0xF023: '#',
    0xF024: '\u2203',
    0xF025: '%',
    0xF026: '&',
    0xF027: '\u220B',
    0xF028: '(',
    0xF029: ')',
    0xF02A: '\u2217',
    0xF02B: '+',
    0xF02C: ',',
    0xF02D: '\u2212',
    0xF02E: '.',
    0xF02F: '/',
    0xF030: '0',
    0xF031: '1',
    0xF032: '2',
    0xF033: '3',
    0xF034: '4',
    0xF035: '5',
    0xF036: '6',
    0xF037: '7',
    0xF038: '8',
    0xF039: '9',
    0xF03A: ':',
    0xF03B: ';',
    0xF03C: '<',
    0xF03D: '=',
    0xF03E: '>',
    0xF03F: '?',
    0xF040: '\u2245',
    0xF041: '\u0391',
    0xF042: '\u0392',
    0xF043: '\u03A7',
    0xF044: '\u2206',
    0xF045: '\u0395',
    0xF046: '\u03A6',
    0xF047: '\u0393',
    0xF048: '\u0397',
    0xF049: '\u0399',
    0xF04A: '\u03D1',
    0xF04B: '\u039A',
    0xF04C: '\u039B',
    0xF04D: '\u039C',
    0xF04E: '\u039D',
    0xF04F: '\u039F',
    0xF050: '\u03A0',
    0xF051: '\u0398',
    0xF052: '\u03A1',
    0xF053: '\u03A3',
    0xF054: '\u03A4',
    0xF055: '\u03A5',
    0xF056: '\u03C2',
    0xF057: '\u03A9',
    0xF058: '\u039E',
    0xF059: '\u03A8',
    0xF05A: '\u0396',
    0xF05B: '[',
    0xF05C: '\u2234',
    0xF05D: ']',
    0xF05E: '\u22A5',
    0xF05F: '_',
    0xF060: '',
    0xF061: '\u03B1',
    0xF062: '\u03B2',
    0xF063: '\u03C7',
    0xF064: '\u03B4',
    0xF065: '\u03B5',
    0xF066: '\u03C6',
    0xF067: '\u03B3',
    0xF068: '\u03B7',
    0xF069: '\u03B9',
    0xF06A: '\u03D5',
    0xF06B: '\u03BA',
    0xF06C: '\u03BB',
    0xF06D: '\u00B5',
    0xF06E: '\u03BD',
    0xF06F: '\u03BF',
    0xF070: '\u03C0',
    0xF071: '\u03B8',
    0xF072: '\u03C1',
    0xF073: '\u03C3',
    0xF074: '\u03C4',
    0xF075: '\u03C5',
    0xF076: '\u03D6',
    0xF077: '\u03C9',
    0xF078: '\u03BE',
    0xF079: '\u03C8',
    0xF07A: '\u03B6',
    0xF07B: '{',
    0xF07C: '|',
    0xF07D: '}',
    0xF07E: '\u223C',
    0xF0A0: '\u20AC',
    0xF0A1: '\u03D2',
    0xF0A2: '\u2032',
    0xF0A3: '\u2264',
    0xF0A4: '\u2044',
    0xF0A5: '\u221E',
    0xF0A6: '\u0192',
    0xF0A7: '\u2663',
    0xF0A8: '\u2666',
    0xF0A9: '\u2665',
    0xF0AA: '\u2660',
    0xF0AB: '\u2194',
    0xF0AC: '\u2190',
    0xF0AD: '\u2191',
    0xF0AE: '\u2192',
    0xF0AF: '\u2193',
    0xF0B0: '\u00B0',
    0xF0B1: '\u00B1',
    0xF0B2: '\u2033',
    0xF0B3: '\u2265',
    0xF0B4: '\u00D7',
    0xF0B5: '\u221D',
    0xF0B6: '\u2202',
    0xF0B7: '\u2022',
    0xF0B8: '\u00F7',
    0xF0B9: '\u2260',
    0xF0BA: '\u2261',
    0xF0BB: '\u2248',
    0xF0BC: '\u2026',
    0xF0BF: '\u21B5',
    0xF0C0: '\u2135',
    0xF0C1: '\u2111',
    0xF0C2: '\u211C',
    0xF0C3: '\u2118',
    0xF0C4: '\u2297',
    0xF0C5: '\u2295',
    0xF0C6: '\u2205',
    0xF0C7: '\u2229',
    0xF0C8: '\u222A',
    0xF0C9: '\u2283',
    0xF0CA: '\u2287',
    0xF0CB: '\u2284',
    0xF0CC: '\u2282',
    0xF0CD: '\u2286',
    0xF0CE: '\u2208',
    0xF0CF: '\u2209',
    0xF0D0: '\u2220',
    0xF0D1: '\u2207',
    0xF0D5: '\u220F',
    0xF0D6: '\u221A',
    0xF0D7: '\u22C5',
    0xF0D8: '\u00AC',
    0xF0D9: '\u2227',
    0xF0DA: '\u2228',
    0xF0DB: '\u21D4',
    0xF0DC: '\u21D0',
    0xF0DD: '\u21D1',
    0xF0DE: '\u21D2',
    0xF0DF: '\u21D3',
    0xF0E0: '\u25CA',
    0xF0E1: '\u2329',
    0xF0E5: '\u2211',
    0xF0E6: '(',
    0xF0E7: '(',
    0xF0E8: '(',
    0xF0E9: '[',
    0xF0EA: '[',
    0xF0EB: '[',
    0xF0EC: '{',
    0xF0ED: '{',
    0xF0EE: '{',
    0xF0F1: '\u232A',
    0xF0F2: '\u222B',
    0xF0F3: '\u2320',
    0xF0F5: '\u2321',
    0xF0F6: ')',
    0xF0F7: ')',
    0xF0F8: ')',
    0xF0F9: ']',
    0xF0FA: ']',
    0xF0FB: ']',
    0xF0FC: '}',
    0xF0FD: '}',
    0xF0FE: '}',
}

# Matches any character in the specific PUA sub-range this convention uses.
# Codepoints in this range never legitimately mean anything else, so it's
# safe to scan for them directly in already-assembled markdown text without
# needing to track which font produced each character.
_PUA_PATTERN = re.compile('[\uf020-\uf0fe]')


def _replace_one(match):
    cp = ord(match.group(0))
    # Codepoints we haven't mapped (rare, decorative glyphs like suit
    # symbols used as bullets) are dropped rather than left as a raw PUA
    # character -- an unrenderable placeholder box in the output is strictly
    # worse than a small gap, since the reader can't do anything with either.
    return SYMBOL_FONT_PUA_MAP.get(cp, '')


def remap_symbol_chars(text: str) -> str:
    """
    Replace Adobe-Symbol-font Private-Use-Area characters in `text` with
    their correct Unicode equivalents (math operators, relations, Greek
    letters). Safe to call on any markdown text -- text with no such
    characters passes through unchanged.
    """
    if not text:
        return text
    return _PUA_PATTERN.sub(_replace_one, text)
