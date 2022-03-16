def get_user_id_from_arn(arn):
    # arn:aws:iam::12345:user/id --> id
    return arn.split("/")[1]


def get_account_uid_from_arn(arn):
    # arn:aws:iam::12345:role/role-1 --> 12345
    return arn.split(":")[4]


def get_details_from_role_link(role_link):
    # https://signin.aws.amazon.com/switchrole?
    # account=<uid>&roleName=<role_name> -->
    # 12345, role-1
    details = role_link.split("?")[1].split("&")
    uid = details[0].split("=")[1]
    role_name = details[1].split("=")[1]
    return uid, role_name


def get_role_arn_from_role_link(role_link):
    # https://signin.aws.amazon.com/switchrole?
    # account=<uid>&roleName=<role_name> -->
    # arn:aws:iam::12345:role/role-1
    uid, role_name = get_details_from_role_link(role_link)
    return f"arn:aws:iam::{uid}:role/{role_name}"


def get_account_uid_from_role_link(role_link):
    uid, _ = get_details_from_role_link(role_link)
    return uid
