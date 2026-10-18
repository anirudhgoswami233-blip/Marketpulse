import logging

from app.core.logging import RedactSecretsFilter


def make_record(msg: str, *args: object) -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)


def test_redacts_known_secrets_in_formatted_message() -> None:
    record = make_record("calling with key %s", "super-secret-key")
    RedactSecretsFilter(["super-secret-key"]).filter(record)
    assert "super-secret-key" not in record.getMessage()
    assert "***" in record.getMessage()


def test_redacts_query_string_credentials_even_for_unknown_keys() -> None:
    record = make_record("GET https://api.example.com/x?series_id=A&api_key=abc123&token=zzz")
    RedactSecretsFilter([]).filter(record)
    message = record.getMessage()
    assert "abc123" not in message and "zzz" not in message
    assert "api_key=***" in message and "token=***" in message


def test_leaves_clean_messages_untouched() -> None:
    record = make_record("quote for %s", "AAPL")
    RedactSecretsFilter(["secret"]).filter(record)
    assert record.getMessage() == "quote for AAPL"
