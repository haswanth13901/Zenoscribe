"""Unit tests for soniox_client's pure token-merging helpers - no network."""
from voice_transcriber.soniox_client import merge_tokens, merge_translated_turns


def _tok(text, speaker, start_ms, end_ms, translation_status=None):
    return {
        "text": text,
        "speaker": speaker,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "translation_status": translation_status,
    }


def test_merge_tokens_collapses_consecutive_same_speaker():
    tokens = [
        _tok("Hello ", 1, 0, 500),
        _tok("world.", 1, 500, 1000),
        _tok("Hi", 2, 1000, 1500),
    ]
    turns = merge_tokens(tokens)
    assert turns == [
        {"speaker": "user-1", "text": "Hello world.", "start": 0.0, "end": 1.0},
        {"speaker": "user-2", "text": "Hi", "start": 1.0, "end": 1.5},
    ]


def test_merge_translated_turns_pairs_original_and_translation_by_speaker_turn():
    original_tokens = [
        _tok("Hola ", 1, 0, 500, "original"),
        _tok("mundo.", 1, 500, 1000, "original"),
        _tok("Adios", 2, 1000, 1500, "original"),
    ]
    trans_tokens = [
        _tok("Hello ", 1, 0, 500, "translation"),
        _tok("world.", 1, 500, 1000, "translation"),
        _tok("Bye", 2, 1000, 1500, "translation"),
    ]
    turns = merge_translated_turns(original_tokens, trans_tokens)
    assert turns == [
        {"speaker": "user-1", "text": "Hola mundo.", "translation": "Hello world.", "start": 0.0, "end": 1.0},
        {"speaker": "user-2", "text": "Adios", "translation": "Bye", "start": 1.0, "end": 1.5},
    ]


def test_merge_translated_turns_tolerates_mismatched_turn_counts():
    original_tokens = [_tok("Hola", 1, 0, 500, "original")]
    trans_tokens = [
        _tok("Hello", 1, 0, 500, "translation"),
        _tok("Bye", 2, 500, 1000, "translation"),
    ]
    turns = merge_translated_turns(original_tokens, trans_tokens)
    assert turns == [
        {"speaker": "user-1", "text": "Hola", "translation": "Hello", "start": 0.0, "end": 0.5},
        {"speaker": "user-2", "text": "", "translation": "Bye", "start": 0.5, "end": 1.0},
    ]
