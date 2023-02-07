import os
import random
import shutil
import tempfile
import threading
from dataclasses import dataclass
from typing import Optional

from sshtunnel import SSHTunnelForwarder

from reconcile.utils import gql
from reconcile.utils.exceptions import FetchResourceError
from reconcile.utils.helpers import toggle_logger

# https://www.iana.org/assignments/service-names-port-numbers/service-names-port-numbers.xhtml
DYNAMIC_PORT_MIN = 49152
DYNAMIC_PORT_MAX = 65535


class HTTPStatusCodeError(Exception):
    def __init__(self, msg: str):
        super().__init__("HTTP status code error: " + msg)


@dataclass
class JumphostParameters:
    hostname: str
    known_hosts: str
    user: str
    port: Optional[int]
    remote_port: Optional[int]
    local_port: Optional[int]
    key: str


class JumpHostBase:
    def __init__(self, parameters: JumphostParameters):
        self._hostname = parameters.hostname
        self._user = parameters.user
        self._port = parameters.port if parameters.port else 22
        self._identity = parameters.key
        self._init_identity_file()

    def _init_identity_file(self) -> None:
        self._identity_dir = tempfile.mkdtemp()

        identity_file = self._identity_dir + "/id"
        with open(identity_file, "w") as f:
            f.write(self._identity)
        os.chmod(identity_file, 0o600)
        self._identity_file = identity_file

    def cleanup(self) -> None:
        shutil.rmtree(self._identity_dir)


class JumpHostSSH(JumpHostBase):
    bastion_tunnel: dict[int, SSHTunnelForwarder] = {}
    local_ports: list[int] = []
    tunnel_lock = threading.Lock()

    def __init__(
        self, parameters: JumphostParameters, gql_api: Optional[gql.GqlApi] = None
    ):
        JumpHostBase.__init__(self, parameters=parameters)

        self._gql_api = gql.get_api() if gql_api is None else gql_api
        self._known_hosts = self._get_known_hosts(parameters.known_hosts)
        self._init_known_hosts_file()
        self._local_port = (
            self.get_unique_random_port()
            if parameters.local_port is None
            else parameters.local_port
        )
        self._remote_port = parameters.remote_port

    @property
    def local_port(self) -> Optional[int]:
        return self._local_port

    @staticmethod
    def get_unique_random_port() -> int:
        with JumpHostSSH.tunnel_lock:
            port = random.randint(DYNAMIC_PORT_MIN, DYNAMIC_PORT_MAX)
            while port in JumpHostSSH.local_ports:
                port = random.randint(DYNAMIC_PORT_MIN, DYNAMIC_PORT_MAX)
            JumpHostSSH.local_ports.append(port)
            return port

    def _get_known_hosts(self, known_hosts_path: str) -> str:
        try:
            known_hosts = self._gql_api.get_resource(known_hosts_path)
        except gql.GqlGetResourceError as e:
            raise FetchResourceError(str(e))
        return known_hosts["content"]

    def _init_known_hosts_file(self) -> None:
        known_hosts_file = self._identity_dir + "/known_hosts"
        with open(known_hosts_file, "w") as f:
            f.write(self._known_hosts)
        os.chmod(known_hosts_file, 0o600)
        self.known_hosts_file = known_hosts_file

    def get_ssh_base_cmd(self) -> list[str]:
        user_host = "{}@{}".format(self._user, self._hostname)

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
            self._identity_file,
            "-p",
            str(self._port),
            user_host,
        ]

    def create_ssh_tunnel(self) -> None:
        with JumpHostSSH.tunnel_lock:
            if self._local_port not in JumpHostSSH.bastion_tunnel:
                # Hide connect messages from sshtunnel
                with toggle_logger():
                    tunnel = SSHTunnelForwarder(
                        ssh_address_or_host=self._hostname,
                        ssh_port=self._port,
                        ssh_username=self._user,
                        ssh_pkey=self._identity_file,
                        remote_bind_address=(self._hostname, self._remote_port),
                        local_bind_address=("localhost", self._local_port),
                    )
                    tunnel.start()
                JumpHostSSH.bastion_tunnel[self._local_port] = tunnel

    def cleanup(self) -> None:
        JumpHostBase.cleanup(self)
        with JumpHostSSH.tunnel_lock:
            tunnels = JumpHostSSH.bastion_tunnel
            if self._local_port in tunnels:
                tunnel = tunnels.pop(self._local_port)
                tunnel.close()
                JumpHostSSH.local_ports.remove(self._local_port)
