import string
from enum import IntFlag

NOT_ENOUGH_DIGITS_MSG = "Your password does not have at least one digit."
NOT_ENOUGH_SPECIAL_CHARS_MSG = (
    "Your password does not have at least one special character (non-alphanumeric)."
)
NOT_ENOUGH_LOWER_CASE_CHARS_MSG = (
    "Your password does not have at least one lower case character."
)
NOT_ENOUGH_UPPER_CASE_CHARS_MSG = (
    "Your password does not have at least one upper case character."
)


class PasswordPolicy(IntFlag):
    HAS_UPPER_CASE_CHAR = 1
    HAS_LOWER_CASE_CHAR = 2
    HAS_DIGIT = 4
    HAS_SPECIAL_CHAR = 8


class PasswordValidationError(Exception):
    pass


class PasswordValidator:
    def __init__(self, policy_flags: int = 0, minimum_length: int = 0):
        self._policy_flags = policy_flags
        self._mininum_length = minimum_length

    def validate(self, password: str):
        errors: list[str] = []

        if len(password) < self._mininum_length:
            errors.append(
                f"Your password does not have at least {self._mininum_length} characters."
            )

        password_set = set(password)
        if self._policy_flags & PasswordPolicy.HAS_UPPER_CASE_CHAR:
            if not any(password_set.intersection(set(string.ascii_uppercase))):
                errors.append(NOT_ENOUGH_UPPER_CASE_CHARS_MSG)

        if self._policy_flags & PasswordPolicy.HAS_LOWER_CASE_CHAR:
            if not any(password_set.intersection(set(string.ascii_lowercase))):
                errors.append(NOT_ENOUGH_LOWER_CASE_CHARS_MSG)

        if self._policy_flags & PasswordPolicy.HAS_DIGIT:
            if not any(password_set.intersection(set(string.digits))):
                errors.append(NOT_ENOUGH_DIGITS_MSG)

        if self._policy_flags & PasswordPolicy.HAS_SPECIAL_CHAR:
            has_special_char = False
            # TODO: maybe this could be done more efficient if we had a pre-defined set of alnums
            for c in password:
                has_special_char |= not str.isalnum(c)

            if not has_special_char:
                errors.append(NOT_ENOUGH_SPECIAL_CHARS_MSG)

        if errors:
            raise PasswordValidationError("\n".join(errors))
