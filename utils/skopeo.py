import subprocess


class Skopeo():
    """Wrapper around the skopeo utility"""
    debug = ""

    def __init__(self, debug="false"):
        self.debug = debug

    def inspect(self, image_name, transport="docker"):
        """Runs the scopeo inspect command"""
        cmd = ['jb', 'install']
        subprocess.call(cmd, cwd=self.temp_dir_path)

    def get_tags(self, image_name, transport="docker"):
        """Runs skopeo inspect and returns a list of image tags"""
        return self.inspect(image_name, transport)['RepoTags']

    def copy(self, source_image, target_image, transport="docker"):
        """
        Runs skopeo copy from source to target
        """
        source_image = transport + "://" + source_image
        target_image = transport + "://" + target_image
        cmd = ['skopeo', 'copy', source_image, target_image]
        try:
            subprocess.call(cmd)
        except Exception:
            raise Exception

    def delete(self, image_name, image_tag, transport="docker"):
        """Removes an image+tag from the repo"""
        image_name = transport + "://" + image_name + ":" + image_tag
        cmd = ['skopeo', 'delete', image_name]
        try:
            subprocess.call(cmd)
        except Exception:
            raise Exception
