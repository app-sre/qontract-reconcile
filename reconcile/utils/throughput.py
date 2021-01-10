import os


def change_files_ownership(directory):
    stat_info = os.stat(directory)
    uid = stat_info.st_uid
    gid = stat_info.st_gid
    for root, dirs, files in os.walk(directory):
        for d in dirs:
            os.chown(os.path.join(root, d), uid, gid)
        for f in files:
            os.chown(os.path.join(root, f), uid, gid)
