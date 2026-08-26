"""Extractors for mail.

A message is a document; its attachments are its children. Headers are rendered
into the extracted text rather than kept only as metadata, because chunks are
what search retrieves and what an agent reads — a sender held only in a column
is invisible to both.
"""

from __future__ import annotations

import email
import email.policy
from collections.abc import Iterator
from email.message import EmailMessage
from pathlib import Path

from .extractors import Child, Extraction, ExtractionError

_HEADERS = ("From", "To", "Cc", "Date", "Subject")


def _render(message: EmailMessage) -> str:
    """Headers an analyst reads, then the body."""
    lines = []
    for header in _HEADERS:
        value = message.get(header)
        if value:
            # Headers are attacker-controlled and may carry newlines through
            # encoded words; collapse so one header cannot forge another.
            lines.append(f"{header}: {' '.join(str(value).split())}")
    body = _body_text(message)
    if body:
        lines.append("")
        lines.append(body)
    return "\n".join(lines)


def _body_text(message: EmailMessage) -> str:
    try:
        part = message.get_body(preferencelist=("plain", "html"))
    except Exception:  # pragma: no cover - malformed structure
        part = None
    if part is None:
        return ""
    try:
        content = part.get_content()
    except Exception:  # pragma: no cover - undecodable payload
        return ""
    return content if isinstance(content, str) else ""


def _attachments(message: EmailMessage) -> Iterator[Child]:
    for index, part in enumerate(message.iter_attachments()):
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        name = part.get_filename() or f"attachment-{index + 1}"
        yield Child(name=name, data=payload)


def _parse(data: bytes, label: str) -> EmailMessage:
    try:
        return email.message_from_bytes(data, policy=email.policy.default)
    except Exception as exc:
        raise ExtractionError(f"could not parse {label} as mail: {exc}") from exc


class EmlExtractor:
    """RFC 822 messages."""

    name = "eml"
    suffixes = {".eml": "message/rfc822"}

    def accepts(self, path: Path) -> bool:
        return path.suffix.lower() in self.suffixes

    def extract(self, path: Path) -> Extraction:
        message = _parse(path.read_bytes(), path.name)
        text = _render(message)
        has_attachments = any(True for _ in message.iter_attachments())
        return Extraction(
            text=text,
            media_type="message/rfc822",
            extractor=self.name,
            metadata={
                key.lower(): " ".join(str(message.get(key)).split())
                for key in _HEADERS
                if message.get(key)
            },
            is_container=has_attachments,
        )

    def iter_children(self, path: Path) -> Iterator[Child]:
        yield from _attachments(_parse(path.read_bytes(), path.name))


class MboxExtractor:
    """Unix mailboxes: a container whose children are its messages."""

    name = "mbox"
    suffixes = {".mbox": "application/mbox"}

    def accepts(self, path: Path) -> bool:
        return path.suffix.lower() in self.suffixes

    def extract(self, path: Path) -> Extraction:
        subjects = []
        for index, raw in enumerate(_split_mbox(path)):
            try:
                message = _parse(raw, f"{path.name} message {index + 1}")
            except ExtractionError:
                continue
            subject = message.get("Subject")
            subjects.append(" ".join(str(subject).split()) if subject else "(no subject)")
        return Extraction(
            text="\n".join(subjects),
            media_type="application/mbox",
            extractor=self.name,
            metadata={"messages": str(len(subjects))},
            is_container=True,
        )

    def iter_children(self, path: Path) -> Iterator[Child]:
        for index, raw in enumerate(_split_mbox(path)):
            # Each message becomes an .eml child, so it is routed back through
            # the registry to the message extractor rather than parsed here.
            yield Child(name=f"message-{index + 1:05d}.eml", data=raw)


def _split_mbox(path: Path) -> Iterator[bytes]:
    """Split on `From ` lines, streaming rather than loading the mailbox.

    `mailbox.mbox` would parse each message eagerly and raise on the first
    malformed one, taking the whole mailbox with it. Splitting keeps a corrupt
    message to itself: it becomes one child that fails to extract.
    """
    buffer: list[bytes] = []
    with path.open("rb") as handle:
        for line in handle:
            if line.startswith(b"From ") and buffer:
                yield b"".join(buffer)
                buffer = []
            buffer.append(line)
    if buffer:
        joined = b"".join(buffer)
        if joined.strip():
            yield joined


class MsgExtractor:
    """Outlook .msg messages.

    The one mail format here without a standard-library reader; `extract-msg`
    is GPLv3, admitted by this project's AGPL-3.0-or-later licence.
    """

    name = "msg"
    suffixes = {".msg": "application/vnd.ms-outlook"}

    def accepts(self, path: Path) -> bool:
        return path.suffix.lower() in self.suffixes

    def _open(self, path: Path):
        try:
            import extract_msg
        except ImportError as exc:  # pragma: no cover - packaging failure
            raise ExtractionError("the extract-msg reader is not installed") from exc
        try:
            return extract_msg.Message(str(path))
        except Exception as exc:
            raise ExtractionError(
                f"could not read {path.name} as an Outlook message: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def extract(self, path: Path) -> Extraction:
        message = self._open(path)
        try:
            fields = {
                "From": message.sender,
                "To": message.to,
                "Cc": message.cc,
                "Date": message.date,
                "Subject": message.subject,
            }
            lines = [
                f"{key}: {' '.join(str(value).split())}"
                for key, value in fields.items()
                if value
            ]
            body = message.body or ""
            if body:
                lines.extend(["", body])
            has_attachments = bool(message.attachments)
            metadata = {
                key.lower(): " ".join(str(value).split())
                for key, value in fields.items()
                if value
            }
        finally:
            message.close()
        return Extraction(
            text="\n".join(lines),
            media_type="application/vnd.ms-outlook",
            extractor=self.name,
            metadata=metadata,
            is_container=has_attachments,
        )

    def iter_children(self, path: Path) -> Iterator[Child]:
        message = self._open(path)
        try:
            for index, attachment in enumerate(message.attachments):
                data = attachment.data
                if not isinstance(data, bytes) or not data:
                    continue
                name = (
                    getattr(attachment, "longFilename", None)
                    or getattr(attachment, "shortFilename", None)
                    or f"attachment-{index + 1}"
                )
                yield Child(name=str(name), data=data)
        finally:
            message.close()
