"""Safe, dependency-free EPUB reading and optional FFmpeg M4B export.

No network access, TTS import, ZIP extraction, or model download. See
``docs/document_features_integration.md`` for server integration contracts.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import math
import os
from pathlib import Path
import posixpath
import re
import shutil
import stat
import struct
import subprocess
import tempfile
from typing import Mapping, Sequence
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile
import zlib


class DocumentFeatureError(ValueError):
    """Invalid or unsupported input; suitable for translation to HTTP 422."""


class EpubError(DocumentFeatureError):
    pass


class M4BError(DocumentFeatureError):
    pass


class M4BTimeoutError(M4BError):
    pass


@dataclass(frozen=True)
class EpubLimits:
    max_archive_bytes: int = 64 * 1024 * 1024
    max_entries: int = 2048
    max_entry_bytes: int = 8 * 1024 * 1024
    max_total_bytes: int = 128 * 1024 * 1024
    max_compression_ratio: float = 200.0
    max_text_chars: int = 4_000_000
    max_chapters: int = 1024

    def __post_init__(self):
        for name, value in vars(self).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
            if name != "max_compression_ratio" and not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")


@dataclass(frozen=True)
class EpubChapter:
    title: str
    text: str
    href: str
    start_char: int
    end_char: int


@dataclass(frozen=True)
class EpubDocument:
    title: str
    author: str
    chapters: tuple[EpubChapter, ...]

    @property
    def text(self) -> str:
        return "\n\n".join(chapter.text for chapter in self.chapters)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _xml(data: bytes, name: str) -> ET.Element:
    # Removing NULs also catches UTF-16/32 declarations; Expat does not support
    # arbitrary encodings such as UTF-7. DTDs/entities are unnecessary in EPUB.
    inspect = data.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in inspect or b"<!ENTITY" in inspect:
        raise EpubError(f"DTD/entities are not allowed: {name}")
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, LookupError, ValueError) as exc:
        raise EpubError(f"Invalid XML: {name}") from exc
    if sum(1 for _ in root.iter()) > 100_000:
        raise EpubError(f"Too many XML elements: {name}")
    return root


def _preflight_zip(data: bytes, limits: EpubLimits) -> None:
    """Bound central-directory work before ZipFile allocates one object/entry.

    EPUBs within our small limits do not need ZIP64 or multi-disk archives.
    Check actual directory records, not only attacker-controlled entry counts.
    """
    start = max(0, len(data) - 65_557)
    end = data.rfind(b"PK\x05\x06", start)
    while end >= start:
        if end + 22 <= len(data):
            fields = struct.unpack_from("<4s4H2LH", data, end)
            if end + 22 + fields[-1] == len(data):
                break
        end = data.rfind(b"PK\x05\x06", start, end)
    else:
        raise EpubError("Missing ZIP end directory")
    _, disk, central_disk, disk_count, count, size, offset, _ = fields
    if disk or central_disk or disk_count != count or count == 0xFFFF or size == 0xFFFFFFFF or offset == 0xFFFFFFFF:
        raise EpubError("Multi-disk/ZIP64 EPUB is not supported")
    if count > limits.max_entries:
        raise EpubError("EPUB contains too many ZIP entries")
    if offset + size != end:
        raise EpubError("Invalid ZIP central directory bounds")
    cursor = offset
    actual_count = 0
    while cursor < end:
        if cursor + 46 > end or data[cursor:cursor + 4] != b"PK\x01\x02":
            raise EpubError("Invalid ZIP central directory entry")
        name_len, extra_len, comment_len = struct.unpack_from("<3H", data, cursor + 28)
        cursor += 46 + name_len + extra_len + comment_len
        actual_count += 1
        if cursor > end or actual_count > limits.max_entries:
            raise EpubError("ZIP central directory exceeds entry limits")
    if actual_count != count:
        raise EpubError("ZIP central directory entry count mismatch")


def _archive_name(name: str) -> str:
    if not name or "\\" in name or "\x00" in name or name.startswith("/"):
        raise EpubError("Unsafe ZIP entry path")
    if any(part in {".", ".."} for part in name.split("/")) or ":" in name:
        raise EpubError("Unsafe ZIP entry path")
    normalized = posixpath.normpath(name)
    if normalized in {"", "."}:
        raise EpubError("Empty ZIP entry path")
    return normalized


def _resolve(base: str, href: str) -> str:
    if not href or "\\" in href or any(ord(c) < 32 for c in href):
        raise EpubError("Unsafe EPUB reference")
    try:
        parts = urlsplit(href)
    except ValueError as exc:
        raise EpubError("Invalid EPUB reference") from exc
    if parts.scheme or parts.netloc or parts.query:
        raise EpubError("External EPUB references are not supported")
    path = unquote(parts.path, errors="strict")
    if not path or path.startswith("/") or "\\" in path or ":" in path or any(ord(c) < 32 for c in path):
        raise EpubError("Unsafe EPUB reference")
    path = posixpath.normpath(posixpath.join(base, path))
    if path in {".", ".."} or path.startswith("../"):
        raise EpubError("EPUB reference escapes archive")
    return path


def _text(element: ET.Element) -> str:
    """Visible XHTML text, preserving paragraph boundaries and inline spacing."""
    ignored = {"head", "script", "style", "noscript", "nav"}
    blocks = {"p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "blockquote", "pre", "br"}
    pieces: list[str] = []
    # Iterative traversal prevents recursion overflow on maliciously deep XHTML.
    stack = [(element, False)]
    while stack:
        node, closing = stack.pop()
        tag = _local(node.tag)
        if closing:
            if tag in blocks:
                pieces.append("\n\n")
            elif tag in {"td", "th"}:
                pieces.append(" ")
            if node is not element and node.tail:
                pieces.append(re.sub(r"\s+", " ", node.tail))
            continue
        if tag in ignored or "hidden" in node.attrib or node.get("aria-hidden", "").lower() == "true":
            if node is not element and node.tail:
                pieces.append(re.sub(r"\s+", " ", node.tail))
            continue
        if tag in blocks:
            pieces.append("\n\n")
        if node.text:
            pieces.append(re.sub(r"\s+", " ", node.text))
        stack.append((node, True))
        stack.extend((child, False) for child in reversed(list(node)))
    text = "".join(pieces)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _first_heading(body: ET.Element) -> str:
    stack = [body]
    while stack:
        node = stack.pop()
        if _local(node.tag) in {"head", "script", "style", "noscript", "nav"} or "hidden" in node.attrib or node.get("aria-hidden", "").lower() == "true":
            continue
        if _local(node.tag) in {"h1", "h2", "h3"}:
            title = _text(node)
            if title:
                return title
            # Empty heading subtrees need not be rescanned for nested headings.
            continue
        stack.extend(reversed(list(node)))
    return ""


def read_epub(data: bytes, *, limits: EpubLimits | None = None) -> EpubDocument:
    """Read EPUB 2/3 XHTML in OPF spine order without extracting any file.

    A chapter is one nonempty, linear XHTML spine item (not a heading). Nav,
    non-linear items and unsupported non-text spine items are omitted. This is
    intentionally strict: malformed XML, DTDs, encrypted content and remote
    manifest references are rejected. CSS is not evaluated and DRM unsupported.
    """
    limits = limits or EpubLimits()
    if not isinstance(data, bytes):
        raise TypeError("EPUB input must be bytes")
    if len(data) > limits.max_archive_bytes:
        raise EpubError("EPUB archive exceeds size limit")
    _preflight_zip(data, limits)
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > limits.max_entries:
                raise EpubError("EPUB contains too many ZIP entries")
            members: dict[str, zipfile.ZipInfo] = {}
            total = 0
            for item in entries:
                name = _archive_name(item.filename)
                if name in members:
                    raise EpubError("Duplicate ZIP entry path")
                members[name] = item
                if stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                    raise EpubError("Symlink/encrypted ZIP entry is not supported")
                if item.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise EpubError("Unsupported ZIP compression")
                if item.file_size > limits.max_entry_bytes:
                    raise EpubError("EPUB entry exceeds size limit")
                total += item.file_size
                if total > limits.max_total_bytes:
                    raise EpubError("EPUB uncompressed size exceeds limit")
                if item.file_size / max(1, item.compress_size) > limits.max_compression_ratio:
                    raise EpubError("EPUB compression ratio exceeds limit")
            if "META-INF/encryption.xml" in members:
                raise EpubError("Encrypted/obfuscated EPUB is not supported")

            def read(name: str) -> bytes:
                info = members.get(name)
                if info is None or info.is_dir():
                    raise EpubError(f"Missing EPUB member: {name}")
                with archive.open(info) as stream:
                    content = stream.read(limits.max_entry_bytes + 1)
                if len(content) > limits.max_entry_bytes or len(content) != info.file_size:
                    raise EpubError("EPUB member size mismatch/limit exceeded")
                return content

            if read("mimetype").strip() != b"application/epub+zip":
                raise EpubError("Invalid EPUB mimetype")
            container = _xml(read("META-INF/container.xml"), "container.xml")
            rootfiles = [e for e in container.iter() if _local(e.tag) == "rootfile" and e.get("media-type") == "application/oebps-package+xml"]
            if not rootfiles:
                raise EpubError("EPUB package is missing")
            opf_path = _resolve("", rootfiles[0].get("full-path", ""))
            package = _xml(read(opf_path), opf_path)
            base = posixpath.dirname(opf_path)
            metadata = next((e for e in package if _local(e.tag) == "metadata"), None)
            def meta(tag: str) -> str:
                if metadata is None:
                    return ""
                return "; ".join(" ".join("".join(e.itertext()).split()) for e in metadata if _local(e.tag) == tag).strip()
            manifest_element = next((e for e in package if _local(e.tag) == "manifest"), None)
            spine = next((e for e in package if _local(e.tag) == "spine"), None)
            if manifest_element is None or spine is None:
                raise EpubError("EPUB manifest/spine is missing")
            manifest = {}
            for item in manifest_element:
                if _local(item.tag) != "item":
                    continue
                item_id = item.get("id", "")
                if not item_id or item_id in manifest:
                    raise EpubError("Missing/duplicate EPUB manifest ID")
                manifest[item_id] = (_resolve(base, item.get("href", "")), item.get("media-type", ""), item.get("properties", "").split())
            if len(manifest) > limits.max_entries:
                raise EpubError("Too many EPUB manifest items")
            if sum(_local(e.tag) == "itemref" for e in spine) > limits.max_chapters:
                raise EpubError("Too many EPUB spine references")
            chapters = []
            seen_hrefs = set()
            position = 0
            for item in spine:
                if _local(item.tag) != "itemref":
                    continue
                entry = manifest.get(item.get("idref", ""))
                if entry is None:
                    raise EpubError("EPUB spine references missing manifest ID")
                if item.get("linear", "yes").lower() == "no":
                    continue
                href, media_type, properties = entry
                if "nav" in properties or media_type not in {"application/xhtml+xml", "text/html"}:
                    continue
                if href in seen_hrefs:
                    raise EpubError("Duplicate EPUB spine document")
                seen_hrefs.add(href)
                root = _xml(read(href), href)
                body = next((e for e in root.iter() if _local(e.tag) == "body"), None)
                if body is None:
                    raise EpubError(f"EPUB chapter has no body: {href}")
                text = _text(body)
                if not text:
                    continue
                title = _first_heading(body)
                if not title:
                    title = next((" ".join("".join(e.itertext()).split()) for e in root.iter() if _local(e.tag) == "title"), "")
                start = position + (2 if chapters else 0)
                position = start + len(text)
                if position > limits.max_text_chars or len(chapters) >= limits.max_chapters:
                    raise EpubError("EPUB text/chapter limit exceeded")
                chapters.append(EpubChapter(title or f"Capítulo {len(chapters) + 1}", text, href, start, position))
            if not chapters:
                raise EpubError("EPUB has no readable linear chapters")
            return EpubDocument(meta("title"), meta("creator"), tuple(chapters))
    except EpubError:
        raise
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, RuntimeError, UnicodeError, NotImplementedError, EOFError, zlib.error) as exc:
        raise EpubError("Invalid/unreadable EPUB archive") from exc


def extract_epub(data: bytes, *, limits: EpubLimits | None = None) -> str:
    """Compatibility adapter for extractors that return plain text."""
    return read_epub(data, limits=limits).text


@dataclass(frozen=True)
class AudioChapter:
    title: str
    start_ms: int
    end_ms: int


def _metadata_escape(value: str) -> str:
    if not isinstance(value, str) or "\x00" in value or len(value) > 16_384:
        raise M4BError("Metadata must be a bounded string without NUL")
    # FFmetadata line continuation permits newlines, but flattening them avoids
    # untrusted text injecting metadata sections while preserving readable text.
    value = value.replace("\r", " ").replace("\n", " ")
    return re.sub(r"([\\\\=;#])", r"\\\1", value)


def export_m4b(
    audio_path: str | os.PathLike,
    output_path: str | os.PathLike,
    *,
    title: str = "",
    author: str = "",
    chapters: Sequence[AudioChapter] = (),
    cover_path: str | os.PathLike | None = None,
    timeout: float = 120,
    ffmpeg: str = "ffmpeg",
    metadata: Mapping[str, str] | None = None,
) -> Path:
    """Encode a local audio file to AAC/M4B atomically, with metadata/chapters.

    Chapter times MUST come from actual synthesized audio, not text offsets.
    ``output_path`` must not already exist. FFmpeg is optional and failures are
    explicit; no fallback changes the requested file format. Input paths should
    be server-controlled job files, never arbitrary client-supplied paths.
    """
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise M4BError("timeout must be positive and finite")
    source = Path(audio_path).resolve()
    output = Path(output_path).absolute()
    if not source.is_file():
        raise M4BError("Audio input is not a file")
    if output.suffix.lower() != ".m4b":
        raise M4BError("Output extension must be .m4b")
    if output.exists() or output.is_symlink():
        raise M4BError("Output already exists")
    if not output.parent.is_dir():
        raise M4BError("Output parent directory does not exist")
    cover = Path(cover_path).resolve() if cover_path is not None else None
    if cover is not None:
        if not cover.is_file() or cover.stat().st_size > 10 * 1024 * 1024:
            raise M4BError("Cover must be a local file of at most 10 MiB")
        with cover.open("rb") as stream:
            header = stream.read(16)
        if not (header.startswith(b"\xff\xd8\xff") or header.startswith(b"\x89PNG\r\n\x1a\n")):
            raise M4BError("Cover must be JPEG or PNG")
    if len(chapters) > 10_000:
        raise M4BError("Too many audio chapters")
    tags = dict(metadata or {})
    if not set(tags) <= {"album", "artist", "title", "genre", "date", "comment", "copyright", "description", "language"}:
        raise M4BError("Unsupported metadata key")
    tags.update(title=title, artist=author, album=title, genre="Audiobook")
    lines = [";FFMETADATA1"] + [f"{key}={_metadata_escape(value)}" for key, value in tags.items()]
    last_end = 0
    for chapter in chapters:
        if not isinstance(chapter, AudioChapter):
            raise M4BError("chapters must contain AudioChapter instances")
        start, end = chapter.start_ms, chapter.end_ms
        if type(start) is not int or type(end) is not int or start < last_end or end <= start or end > 2**53:
            raise M4BError("Chapter times must be ordered, nonoverlapping positive millisecond intervals")
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}", f"title={_metadata_escape(chapter.title)}"]
        last_end = end
    executable = shutil.which(ffmpeg)
    if executable is None:
        raise M4BError("FFmpeg is unavailable; install it to export M4B")
    try:
        # Keep staging on the same filesystem. Nothing is published until success.
        with tempfile.TemporaryDirectory(prefix="m4b-", dir=output.parent) as tmp:
            tmp = Path(tmp)
            meta_file = tmp / "metadata.txt"
            meta_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            staged = tmp / "audio.m4b"
            cmd = [executable, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                   "-protocol_whitelist", "file,pipe", "-i", str(source),
                   "-f", "ffmetadata", "-i", str(meta_file)]
            if cover is not None:
                cmd += ["-protocol_whitelist", "file,pipe", "-i", str(cover)]
            cmd += ["-map", "0:a:0", "-map_metadata", "1", "-map_chapters", "1", "-c:a", "aac", "-b:a", "128k"]
            if cover is not None:
                cmd += ["-map", "2:v:0", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
            else:
                cmd += ["-vn"]
            cmd += ["-movflags", "+faststart", "-f", "mp4", str(staged)]
            # stderr to a temp file avoids unbounded captured output in memory.
            with (tmp / "ffmpeg.stderr").open("w+b") as error_stream:
                try:
                    subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=error_stream, timeout=timeout, check=True)
                except subprocess.TimeoutExpired as exc:
                    raise M4BTimeoutError("FFmpeg M4B export timed out") from exc
                except subprocess.CalledProcessError as exc:
                    # Do not expose paths or arbitrary ffmpeg stderr to API clients.
                    raise M4BError(f"FFmpeg M4B export failed (exit {exc.returncode})") from exc
            if not staged.is_file() or staged.stat().st_size < 12:
                raise M4BError("FFmpeg produced no valid output")
            with staged.open("rb") as stream:
                if stream.read(12)[4:8] != b"ftyp":
                    raise M4BError("FFmpeg output is not an MP4/M4B container")
            # Atomic, no-overwrite publication (even if another worker wins a race).
            os.link(staged, output)
        return output
    except M4BError:
        raise
    except OSError as exc:
        raise M4BError("Could not export M4B to the requested local path") from exc
