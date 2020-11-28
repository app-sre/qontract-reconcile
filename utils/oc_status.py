import logging

class OcStatus:

    def __init__(self, cluster=None, oc_msg=''):
        self.cluster = cluster
        self.oc_msg = oc_msg

    def set_oc_status(self, cluster, oc_msg):
        
        self.cluster = cluster
        self.oc_msg = oc_msg
    
        if self.oc_msg == 'NoAutomationToken':
            msg = f"[{cluster}] cluster has no automationToken."
            logging.error(msg)
            return False
        elif self.oc_msg == 'Unreachable':
            msg = f"[{cluster}] cluster is unreachable."
            logging.error(msg)
            return False
        else:
            return True
