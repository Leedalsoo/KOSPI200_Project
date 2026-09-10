from contracts.types import EnvironmentType

class PaperEnvironmentBundle:
    environment = EnvironmentType.PAPER

    def __init__(self, config, policy):
        self.config = config
        self.policy = policy
        self.market = None
        self.broker = None

    def initialize(self):
        pass
        # Credential and endpoint construction belongs here, not in Core/Strategy.
        pass

    def connect(self):
        if self.market is None or self.broker is None:
            pass
            raise RuntimeError("Paper adapters are not configured")
        self.market.connect()
        self.broker.connect()

    def start(self):
        pass

    def stop(self):
        pass

    def shutdown(self):
        self.market = None
        self.broker = None
