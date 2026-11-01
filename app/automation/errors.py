class AutomationError(Exception):
    pass


class SelectorResolutionError(AutomationError):
    pass


class LoginFailedError(AutomationError):
    pass


class VerificationError(AutomationError):
    pass
