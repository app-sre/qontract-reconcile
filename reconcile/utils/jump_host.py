import tempfile
import shutil
import os
import threading
import logging
import random
from typing import Dict, List

from sshtunnel import SSHTunnelForwarder

from reconcile.utils import gql
from reconcile.utils.secret_reader import SecretReader

from reconcile.utils.exceptions import FetchResourceError

# https://www.iana.org/assignments/service-names-port-numbers/service-names-port-numbers.xhtml
DYNAMIC_PORT_MIN = 49152
DYNAMIC_PORT_MAX = 65535


class HTTPStatusCodeError(Exception):
    def __init__(self, msg):
        super().__init__("HTTP status code error: " + str(msg))


class JumpHostBase:
    def __init__(self, jh, settings=None):
        self.hostname = jh["hostname"]
        self.user = jh["user"]
        self.port = 22 if jh["port"] is None else jh["port"]
        secret_reader = SecretReader(settings=settings)
        self.identity = secret_reader.read(jh["identity"])
        self.init_identity_file()

    def init_identity_file(self):
        self._identity_dir = tempfile.mkdtemp()

        identity_file = self._identity_dir + "/id"
        with open(identity_file, "w") as f:
            f.write(self.identity.decode("utf-8"))
        os.chmod(identity_file, 0o600)
        self.identity_file = identity_file

    def cleanup(self):
        shutil.rmtree(self._identity_dir)


class JumpHostSSH(JumpHostBase):
    bastion_tunnel: Dict[int, SSHTunnelForwarder] = {}
    local_ports: List[int] = []
    tunnel_lock = threading.Lock()

    def __init__(self, jh, settings=None):
        JumpHostBase.__init__(self, jh, settings=settings)

        self.known_hosts = self.get_known_hosts(jh)
        self.init_known_hosts_file()
        self.local_port = (
            self.get_random_port()
            if jh.get("localPort") is None
            else jh.get("localPort")
        )
        self.remote_port = jh["remotePort"]

    @staticmethod
    def get_unique_random_port():
        with JumpHostSSH.tunnel_lock:
            port = random.randint(DYNAMIC_PORT_MIN, DYNAMIC_PORT_MAX)
            while port in JumpHostSSH.local_ports:
                port = random.randint(DYNAMIC_PORT_MIN, DYNAMIC_PORT_MAX)
            JumpHostSSH.local_ports.append(port)
            return port

    @staticmethod
    def get_known_hosts(jh):
        known_hosts_path = jh["knownHosts"]
        gqlapi = gql.get_api()

        try:
            known_hosts = gqlapi.get_resource(known_hosts_path)
        except gql.GqlGetResourceError as e:
            raise FetchResourceError(str(e))
        return known_hosts["content"]

    def init_known_hosts_file(self):
        known_hosts_file = self._identity_dir + "/known_hosts"
        with open(known_hosts_file, "w") as f:
            f.write(self.known_hosts)
        os.chmod(known_hosts_file, 0o600)
        self.known_hosts_file = known_hosts_file

    def get_ssh_base_cmd(self):
        user_host = "{}@{}".format(self.user, self.hostname)

        return [
            "ssh",
            "-o",
            "ControlMaster=auto",
            "-o",
            "ControlPath=/tmp/controlmaster-%r@%h:%p",
            "-o",
            "ControlPersist=600",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "UserKnownHostsFile={}".format(self.known_hosts_file),
            "-i",
            self.identity_file,
            "-p",
            str(self.port),
            user_host,
        ]

    def create_ssh_tunnel(self):
        with JumpHostSSH.tunnel_lock:
            if self.local_port not in JumpHostSSH.bastion_tunnel:
                # Hide connect messages from sshtunnel
                logger = logging.getLogger()
                default_log_level = logger.level
                logger.setLevel(logging.ERROR)

                tunnel = SSHTunnelForwarder(
                    ssh_address_or_host=self.hostname,
                    ssh_port=self.port,
                    ssh_username=self.user,
                    ssh_pkey=self.identity_file,
                    remote_bind_address=(self.hostname, self.remote_port),
                    local_bind_address=("localhost", self.local_port),
                )
                tunnel.start()
                logger.setLevel(default_log_level)
                JumpHostSSH.bastion_tunnel[self.local_port] = tunnel

    def cleanup(self):
        JumpHostBase.cleanup(self)
        with JumpHostSSH.tunnel_lock:
            tunnels = JumpHostSSH.bastion_tunnel
            if self.local_port in tunnels:
                tunnel = tunnels.pop(self.local_port)
                tunnel.close()
                JumpHostSSH.local_ports.remove(self.local_port)
