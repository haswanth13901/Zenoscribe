"""Language options for the translator UI.

A curated subset of Soniox's 60+ supported languages - the common ones for
dropdowns. Codes are ISO 639-1 as Soniox expects them. Extend freely; the
full list is at soniox.com/docs/translation/supported-languages.
"""

LANGUAGES = [
    ("en", "English"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("it", "Italian"),
    ("pt", "Portuguese"),
    ("nl", "Dutch"),
    ("ru", "Russian"),
    ("zh", "Chinese"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("hi", "Hindi"),
    ("ar", "Arabic"),
    ("tr", "Turkish"),
    ("pl", "Polish"),
    ("uk", "Ukrainian"),
    ("vi", "Vietnamese"),
    ("th", "Thai"),
    ("id", "Indonesian"),
    ("sv", "Swedish"),
    ("da", "Danish"),
    ("fi", "Finnish"),
    ("no", "Norwegian"),
    ("cs", "Czech"),
    ("el", "Greek"),
    ("he", "Hebrew"),
    ("ro", "Romanian"),
    ("hu", "Hungarian"),
    ("ta", "Tamil"),
    ("te", "Telugu"),
    ("bn", "Bengali"),
    ("ml", "Malayalam"),
    ("kn", "Kannada"),
]

CODES = {code for code, _ in LANGUAGES}


def is_valid(code) -> bool:
    return code in CODES
