"""Exceptions raised by the HGU client library."""


class HguError(Exception):
    """Base class for every library error."""


class HguConnectionError(HguError):
    """The router could not be reached or the transport failed."""


class HguAuthError(HguError):
    """The router rejected the admin password."""


class HguSessionExpired(HguError):
    """The web session is no longer valid; a new login is needed."""


class HguResponseError(HguError):
    """The router answered with something the parser cannot use."""


class HguForbiddenCommand(HguError):
    """A caller asked for a request the library refuses to send."""
