from reconcile.gql_definitions.fragments.saas_slo_document import SLODocument
from reconcile.utils.secret_reader import SecretReaderBase
from reconcile.utils.slo_document_manager import SLODetails, SLODocumentManager


class SLOGateKeeper:
    """
    Evaluate the SLO Documents using SLODOcumentManager and identifies breached SLOs
    """

    def __init__(
        self,
        slo_documents: list[SLODocument],
        secret_reader: SecretReaderBase,
        thread_pool_size: int = 1,
    ):
        self.slo_manager = SLODocumentManager(
            slo_documents=slo_documents,
            secret_reader=secret_reader,
            thread_pool_size=thread_pool_size,
        )

    def get_breached_slos(self) -> list[SLODetails]:
        """
        Returns a list of SLOs whose current value is below their defined target.
        Raises an error if any SLOs could not be evaluated.
        """
        current_slos: list[SLODetails | None] = self.slo_manager.get_current_slo_list()

        missing_slos = [slo for slo in current_slos if not slo]
        if missing_slos:
            raise RuntimeError("slo validation failed due to retrival errors")

        breached_slos = [
            slo
            for slo in current_slos
            if slo and slo.current_slo_value < slo.slo.slo_target
        ]
        return breached_slos
