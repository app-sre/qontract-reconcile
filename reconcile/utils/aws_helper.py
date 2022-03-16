def get_user_id_from_arn(assume_role):
    # arn:aws:iam::12345:user/id --> id
    return assume_role.split("/")[1]


def get_role_arn_from_role_link(role_link):
    # https://signin.aws.amazon.com/switchrole?
    # account=<uid>&roleName=<role_name> -->
    # arn:aws:iam::12345:role/role-1
    details = role_link.split("?")[1].split("&")
    uid = details[0].split("=")[1]
    role_name = details[1].split("=")[1]
    return f"arn:aws:iam::{uid}:role/{role_name}"


def get_alias_uid_from_assume_role(assume_role):
    # arn:aws:iam::12345:role/role-1 --> 12345
    return assume_role.split(":")[4]
