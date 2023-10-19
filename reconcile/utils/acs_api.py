class AcsApi:  
    def __init__(
        self,
        instance,
        timeout=30,
    ):
        self.url = instance["url"]
        self.token = instance["token"]
        
