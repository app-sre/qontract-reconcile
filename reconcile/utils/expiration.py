import datetime


def has_valid_expiration_date(role: str) -> bool:
    date_bool = True
    if role is None:
        return date_bool
    else:
        date_format = "%Y-%m-%d"
        try:
            date_bool = \
                bool(datetime.datetime.strptime(role, date_format))
        except ValueError:
            date_bool = False
        return date_bool


def role_still_valid(role: str) -> bool:
    if role is None:
        return True
    else:
        exp_date = datetime.datetime \
            .strptime(role, '%Y-%m-%d').date()
        current_date = datetime.datetime.utcnow().date()
        if current_date < exp_date:
            return True
        return False
