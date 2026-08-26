"""The bound on how far one ingest may expand.

Three limits held as one object because they are not three attacks. A deeply
nested archive, a very wide one, and a highly compressed one are the same
attack with different shapes, and an ingest that stops needs to say which shape
it met — "incomplete" is not something an analyst can act on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Deep enough for an archive holding an archive holding a mailbox holding
# attachments, which is what a real dump looks like.
MAX_DEPTH = 8
# Wide enough for a large mailbox export.
MAX_DESCENDANTS = 50_000
# Far above any honest corpus, far below what a zip bomb produces. Counted on
# bytes *produced by extraction*, never bytes read: the whole point of the
# attack is that the bytes read are small.
MAX_EXTRACTED_BYTES = 20 * 1024 * 1024 * 1024

# Deliberately generous. Hitting a bound stops an ingest, and a false stop costs
# an analyst more than a permissive ceiling costs the machine.


@dataclass
class ExpansionBudget:
    """What one ingest may still spend."""

    max_depth: int = MAX_DEPTH
    max_descendants: int = MAX_DESCENDANTS
    max_extracted_bytes: int = MAX_EXTRACTED_BYTES

    descendants: int = 0
    extracted_bytes: int = 0
    exhausted_by: str | None = field(default=None)

    @property
    def spent(self) -> bool:
        return self.exhausted_by is not None

    def allows_depth(self, depth: int) -> bool:
        """Whether expansion may descend to this depth."""
        if depth > self.max_depth:
            self._exhaust(f"nesting deeper than {self.max_depth} levels")
            return False
        return True

    def take_child(self, size: int) -> bool:
        """Charge one expanded document of `size` bytes, or refuse it.

        Both counters are charged together because a caller that took a slot
        without charging the bytes would leave the byte ceiling unreachable —
        the failure mode this object exists to make impossible.
        """
        if self.descendants + 1 > self.max_descendants:
            self._exhaust(f"more than {self.max_descendants} expanded documents")
            return False
        if self.extracted_bytes + size > self.max_extracted_bytes:
            self._exhaust(f"more than {self.max_extracted_bytes} extracted bytes")
            return False
        self.descendants += 1
        self.extracted_bytes += size
        return True

    def _exhaust(self, reason: str) -> None:
        # First bound to be hit is the one reported: it is the one that actually
        # stopped the ingest, and later refusals are its consequence.
        if self.exhausted_by is None:
            self.exhausted_by = reason
