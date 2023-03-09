from __future__ import annotations

from enum import Enum

from pydantic import (
    BaseModel,
    Field,
)


class SSHHostKeyVerificationStrategy(Enum):
    MANUALLY_TRUSTED_KEY_VERIFICATION_STRATEGY = (
        "manuallyTrustedKeyVerificationStrategy"
    )
    MANUALLY_PROVIDED_KEY_VERIFICATION_STRATEGY = (
        "manuallyProvidedKeyVerificationStrategy"
    )
    NON_VERIFYING_KEY_VERIFICATION_STRATEGY = "nonVerifyingKeyVerificationStrategy"
    KNOWN_HOSTS_FILE_KEY_VERIFICATION_STRATEGY = "knownHostsFileKeyVerificationStrategy"


class SSHConnector(BaseModel):
    credentials_id: str = Field(..., alias="credentialsId")
    port: int = 22
    ssh_host_key_verification_strategy: SSHHostKeyVerificationStrategy = Field(
        SSHHostKeyVerificationStrategy.NON_VERIFYING_KEY_VERIFICATION_STRATEGY,
        alias="sshHostKeyVerificationStrategy",
    )

    class Config:
        use_enum_values = True


class ComputerConnector(BaseModel):
    # alias name is defined by jcasc schema
    ssh_connector: SSHConnector = Field(..., alias="sSHConnector")


class JenkinsWorkerFleet(BaseModel):
    # following options comes form https://github.com/jenkinsci/ec2-fleet-plugin/blob/master/docs/
    name: str
    fleet: str
    region: str
    min_size: int = Field(..., alias="minSize")
    max_size: int = Field(..., alias="maxSize")
    computer_connector: ComputerConnector = Field(..., alias="computerConnector")
    fs_root: str = Field(..., alias="fsRoot")
    label_string: str = Field(..., alias="labelString")
    num_executors: int = Field(2, alias="numExecutors")
    idle_minutes: int = Field(30, alias="idleMinutes")
    min_spare_size: int = Field(0, alias="minSpareSize")
    max_total_uses: int = Field(-1, alias="maxTotalUses")
    no_delay_provision: bool = Field(False, alias="noDelayProvision")
    add_node_only_if_running: bool = Field(True, alias="addNodeOnlyIfRunning")
    always_reconnect: bool = Field(True, alias="alwaysReconnect")
    private_ip_used: bool = Field(True, alias="privateIpUsed")
    restrict_usage: bool = Field(True, alias="restrictUsage")

    def __lt__(self, other: JenkinsWorkerFleet) -> bool:
        return self.fleet < other.fleet

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, JenkinsWorkerFleet):
            raise NotImplementedError(
                "Cannot compare to non JenkinsWorkerFleet objects."
            )
        return self.fleet == other.fleet and self.region == other.region

    def __hash__(self) -> int:
        return hash(self.fleet + self.region)

    def differ(self, other: JenkinsWorkerFleet) -> bool:
        return self.dict() != other.dict()
