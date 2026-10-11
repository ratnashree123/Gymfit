import jwt
import pytest

from app.config import get_settings
from app.security import create_access_token, decode_access_token, hash_password, verify_password


def test_password_is_hashed_and_verifiable():
    hashed = hash_password("MyPassword1")
    assert hashed != "MyPassword1"
    assert hashed.startswith("$2")  # bcrypt format
    assert verify_password("MyPassword1", hashed)
    assert not verify_password("WrongPassword1", hashed)


def test_same_password_gives_different_hashes():
    assert hash_password("MyPassword1") != hash_password("MyPassword1")


def test_overlong_password_is_rejected():
    with pytest.raises(ValueError):
        hash_password("a1" * 40)
    assert verify_password("a1" * 40, hash_password("MyPassword1")) is False


def test_token_round_trip():
    token, expires_in = create_access_token(7, "Admin")
    payload = decode_access_token(token)
    assert payload["sub"] == "7"
    assert payload["role"] == "Admin"
    assert expires_in == get_settings().access_token_expire_minutes * 60


def test_tampered_token_is_rejected():
    token, _ = create_access_token(7, "Admin")
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(token[:-3] + "abc")


def test_token_signed_with_other_key_is_rejected():
    forged = jwt.encode({"sub": "1", "exp": 9999999999}, "x" * 40, algorithm="HS256")
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(forged)
