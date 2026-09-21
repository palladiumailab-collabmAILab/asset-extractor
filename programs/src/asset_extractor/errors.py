class ExtractionError(Exception):
    """A user-actionable, expected extraction failure."""


class PipelineError(ExtractionError):
    """A configuration or stage error in the unified pipeline."""
