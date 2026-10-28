"""Exception types. Every error raised by spritewright is a PixelError subclass."""


class PixelError(Exception):
    """Base class for all spritewright errors."""


class ColorError(PixelError, ValueError):
    """Unknown / off-palette / malformed color."""


class GridError(PixelError, ValueError):
    """Malformed text-grid sprite (wrong row length, unknown char, ...)."""


class SourceError(PixelError):
    """Sprite source file could not be found or loaded."""
