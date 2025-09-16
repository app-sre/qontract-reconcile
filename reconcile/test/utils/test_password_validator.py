import pytest

from reconcile.utils.password_validator import (
    NOT_ENOUGH_DIGITS_MSG,
    NOT_ENOUGH_LOWER_CASE_CHARS_MSG,
    NOT_ENOUGH_SPECIAL_CHARS_MSG,
    NOT_ENOUGH_UPPER_CASE_CHARS_MSG,
    PasswordPolicy,
    PasswordValidationError,
    PasswordValidator,
)


def test_password_policy_default() -> None:
    """By default any password is fine -> also empty ones"""
    validator = PasswordValidator()
    password = ""
    validator.validate(password)


def test_password_policy_missing_upper() -> None:
    """Password misses one upper case letter"""
    validator = PasswordValidator(policy_flags=PasswordPolicy.HAS_UPPER_CASE_CHAR)
    password = "abc123"
    with pytest.raises(PasswordValidationError) as e:
        validator.validate(password)

    assert NOT_ENOUGH_UPPER_CASE_CHARS_MSG in str(e.value)


def test_password_policy_has_upper() -> None:
    """Password has at least one upper case letter"""
    validator = PasswordValidator(policy_flags=PasswordPolicy.HAS_UPPER_CASE_CHAR)
    password = "Abc123"
    validator.validate(password)


def test_password_policy_missing_lower() -> None:
    """Password misses one lower case letter"""
    validator = PasswordValidator(policy_flags=PasswordPolicy.HAS_LOWER_CASE_CHAR)
    password = "ABC123"
    with pytest.raises(PasswordValidationError) as e:
        validator.validate(password)

    assert NOT_ENOUGH_LOWER_CASE_CHARS_MSG in str(e.value)


def test_password_policy_has_lower() -> None:
    """Password has at least one lower case letter"""
    validator = PasswordValidator(policy_flags=PasswordPolicy.HAS_UPPER_CASE_CHAR)
    password = "Abc123"
    validator.validate(password)


def test_password_policy_missing_digit() -> None:
    """Password misses one digit"""
    validator = PasswordValidator(policy_flags=PasswordPolicy.HAS_DIGIT)
    password = "ABC@a"
    with pytest.raises(PasswordValidationError) as e:
        validator.validate(password)

    assert NOT_ENOUGH_DIGITS_MSG in str(e.value)


def test_password_policy_has_digit() -> None:
    """Password has at least one lower case letter"""
    validator = PasswordValidator(policy_flags=PasswordPolicy.HAS_DIGIT)
    password = "Abc123"
    validator.validate(password)


def test_password_policy_missing_special_char() -> None:
    """Password misses one special letter"""
    validator = PasswordValidator(policy_flags=PasswordPolicy.HAS_SPECIAL_CHAR)
    password = "ABC12a"
    with pytest.raises(PasswordValidationError) as e:
        validator.validate(password)

    assert NOT_ENOUGH_SPECIAL_CHARS_MSG in str(e.value)


def test_password_policy_has_special_char() -> None:
    """Password has at least one special letter"""
    validator = PasswordValidator(policy_flags=PasswordPolicy.HAS_SPECIAL_CHAR)
    password = "Abc123@"
    validator.validate(password)


def test_password_policy_not_enough_letters() -> None:
    """Password does not have enough letters"""
    validator = PasswordValidator(minimum_length=5)
    password = "Ab1@"
    with pytest.raises(PasswordValidationError) as e:
        validator.validate(password)

    assert "Your password does not have at least 5 characters." in str(e.value)


def test_password_policy_has_enough_letters() -> None:
    """Password has enough letters"""
    validator = PasswordValidator(minimum_length=5)
    password = "aaaaa"
    validator.validate(password)


def test_password_policy_all_flags_valid() -> None:
    """Password has upper, lower, digit, special and at least 8 chars"""
    validator = PasswordValidator(
        policy_flags=(
            PasswordPolicy.HAS_UPPER_CASE_CHAR
            | PasswordPolicy.HAS_LOWER_CASE_CHAR
            | PasswordPolicy.HAS_DIGIT
            | PasswordPolicy.HAS_SPECIAL_CHAR
        ),
        minimum_length=8,
    )
    password = "Abc123@!gh"
    validator.validate(password)


def test_password_policy_all_flags_invalid() -> None:
    """Password has upper, lower, special and at least 8 chars, but misses digit."""
    validator = PasswordValidator(
        policy_flags=(
            PasswordPolicy.HAS_UPPER_CASE_CHAR
            | PasswordPolicy.HAS_LOWER_CASE_CHAR
            | PasswordPolicy.HAS_DIGIT
            | PasswordPolicy.HAS_SPECIAL_CHAR
        ),
        minimum_length=8,
    )
    password = "AbcXYZ@!gh"
    with pytest.raises(PasswordValidationError) as e:
        validator.validate(password)

    assert NOT_ENOUGH_DIGITS_MSG in str(e.value)


def test_password_policy_multiple_failing() -> None:
    """Password misses digits and special letters."""
    validator = PasswordValidator(
        policy_flags=(
            PasswordPolicy.HAS_UPPER_CASE_CHAR
            | PasswordPolicy.HAS_LOWER_CASE_CHAR
            | PasswordPolicy.HAS_DIGIT
            | PasswordPolicy.HAS_SPECIAL_CHAR
        ),
        minimum_length=8,
    )
    password = "AbcXYZsgh"
    with pytest.raises(PasswordValidationError) as e:
        validator.validate(password)

    assert NOT_ENOUGH_DIGITS_MSG in str(e.value)
    assert NOT_ENOUGH_SPECIAL_CHARS_MSG in str(e.value)
