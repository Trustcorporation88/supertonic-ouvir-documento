"""Synthetic fixtures only. All tests run without server, TTS or network."""
from dataclasses import replace
from io import BytesIO
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import warnings
import wave
import zipfile

from document_features import (
    AudioChapter, EpubError, EpubLimits, M4BError, M4BTimeoutError,
    _metadata_escape, export_m4b, extract_epub, read_epub,
)


CONTAINER = b'''<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'''
PACKAGE = '''<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Livro de teste</dc:title><dc:creator>Ana</dc:creator></metadata><manifest><item id="one" href="one.xhtml" media-type="application/xhtml+xml"/><item id="two" href="two.xhtml" media-type="application/xhtml+xml"/><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="skip" href="skip.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="two"/><itemref idref="nav"/><itemref idref="skip" linear="no"/><itemref idref="one"/></spine></package>'''
ONE = '''<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Capítulo primeiro</title><style>ignore style</style></head><body><h1>Primeiro</h1><p>Texto <em>com ênfase</em> e ação &amp; justiça.</p></body></html>'''
TWO = '''<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Segundo</title></head><body><h1>Segundo</h1><p>Antes <script>ignore script</script>depois.</p><nav>ignore nav</nav><p>Mais conteúdo.</p></body></html>'''


def epub(overrides=None, *, compression=zipfile.ZIP_STORED, extras=()):
    entries = {
        "mimetype": b"application/epub+zip",
        "META-INF/container.xml": CONTAINER,
        "OEBPS/book.opf": PACKAGE.encode(),
        "OEBPS/one.xhtml": ONE.encode(),
        "OEBPS/two.xhtml": TWO.encode(),
        "OEBPS/nav.xhtml": b"not read",
        "OEBPS/skip.xhtml": b"not read",
    }
    for name, content in (overrides or {}).items():
        if content is None:
            entries.pop(name, None)
        else:
            entries[name] = content.encode() if isinstance(content, str) else content
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as z:
        for name, content in entries.items():
            z.writestr(name, content)
        for name, content in extras:
            z.writestr(name, content)
    return output.getvalue()


class EpubTests(unittest.TestCase):
    def test_spine_order_chapters_metadata_and_offsets(self):
        document = read_epub(epub())
        self.assertEqual(document.title, "Livro de teste")
        self.assertEqual(document.author, "Ana")
        self.assertEqual([c.title for c in document.chapters], ["Segundo", "Primeiro"])
        self.assertEqual([c.href for c in document.chapters], ["OEBPS/two.xhtml", "OEBPS/one.xhtml"])
        for chapter in document.chapters:
            self.assertEqual(document.text[chapter.start_char:chapter.end_char], chapter.text)
        self.assertEqual(extract_epub(epub()), document.text)
        self.assertIn("com ênfase e ação & justiça.", document.text)
        self.assertIn("Antes depois.", document.text)
        self.assertNotIn("ignore", document.text)
        self.assertIn("\n\n", document.text)

    def test_nothing_is_extracted_to_disk(self):
        with patch.object(zipfile.ZipFile, "extract", side_effect=AssertionError("extract")), \
             patch.object(zipfile.ZipFile, "extractall", side_effect=AssertionError("extractall")):
            self.assertTrue(extract_epub(epub()))

    def test_limits_cover_archive_entries_member_total_ratio_text_spine(self):
        cases = [
            {"max_archive_bytes": 32}, {"max_entries": 2},
            {"max_entry_bytes": 40}, {"max_total_bytes": 60},
            {"max_text_chars": 10}, {"max_chapters": 1},
        ]
        for config in cases:
            with self.subTest(config=config), self.assertRaises(EpubError):
                read_epub(epub(), limits=replace(EpubLimits(), **config))
        compressed = epub({"large.txt": "A" * 100_000}, compression=zipfile.ZIP_DEFLATED)
        with self.assertRaisesRegex(EpubError, "compression ratio"):
            read_epub(compressed)

    def test_invalid_limits_rejected(self):
        for value in (0, -1, float("inf"), float("nan"), True, "large"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                EpubLimits(max_compression_ratio=value)
        with self.assertRaises(ValueError):
            EpubLimits(max_entries=2.5)

    def test_zip_traversal_absolute_backslash_and_symlink_rejected(self):
        for name in ("../escape", "/tmp/escape", "a/../../escape", "a\\escape", "C:/escape", "a/./file"):
            with self.subTest(name=name), self.assertRaises(EpubError):
                read_epub(epub({name: b"unsafe"}))
        symlink = zipfile.ZipInfo("link")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaisesRegex(EpubError, "Symlink"):
            read_epub(epub(extras=[(symlink, b"/etc/passwd")]))

    def test_excess_entries_rejected_before_zipfile_allocates_objects(self):
        data = epub()
        with patch("document_features.zipfile.ZipFile", side_effect=AssertionError("must not open")):
            with self.assertRaisesRegex(EpubError, "too many"):
                read_epub(data, limits=replace(EpubLimits(), max_entries=2))

    def test_forged_entry_count_rejected_before_zipfile_allocates_objects(self):
        import struct
        data = bytearray(epub())
        end = data.rfind(b"PK\x05\x06")
        struct.pack_into("<HH", data, end + 8, 1, 1)
        with patch("document_features.zipfile.ZipFile", side_effect=AssertionError("must not open")):
            with self.assertRaisesRegex(EpubError, "count mismatch"):
                read_epub(bytes(data))

    def test_duplicate_members_rejected(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            data = epub(extras=[("OEBPS/one.xhtml", ONE)])
        with self.assertRaisesRegex(EpubError, "Duplicate"):
            read_epub(data)

    def test_references_cannot_escape_or_use_network(self):
        for href in ("../../evil.xhtml", "%2e%2e/%2e%2e/evil.xhtml", "https://evil.example/chapter", "//evil/chapter", "/etc/passwd", "%2fetc/passwd", "file:///etc/passwd", "one.xhtml?query=1", "%00oops", "one%5cxhtml"):
            altered = PACKAGE.replace('href="one.xhtml"', f'href="{href}"')
            with self.subTest(href=href), self.assertRaises(EpubError):
                read_epub(epub({"OEBPS/book.opf": altered}))

    def test_nested_and_percent_encoded_safe_paths(self):
        altered = PACKAGE.replace('href="one.xhtml"', 'href="Text/../one%20chapter.xhtml#heading"')
        document = read_epub(epub({"OEBPS/book.opf": altered, "OEBPS/one chapter.xhtml": ONE}))
        self.assertEqual(document.chapters[1].href, "OEBPS/one chapter.xhtml")

    def test_dtd_and_entities_rejected_in_every_xml_layer(self):
        malicious = '<!DOCTYPE x [<!ENTITY a "attack">]><x>&a;</x>'
        for member in ("META-INF/container.xml", "OEBPS/book.opf", "OEBPS/two.xhtml"):
            for data in (malicious.encode(), malicious.encode("utf-16"), malicious.encode("utf-32")):
                with self.subTest(member=member), self.assertRaisesRegex(EpubError, "DTD/entities"):
                    read_epub(epub({member: data}))

    def test_malformed_zip_mimetype_xml_members_and_spine(self):
        bad = [b"not a zip", epub({"mimetype": "text/plain"}), epub({"mimetype": None}),
               epub({"OEBPS/two.xhtml": "<broken"}), epub({"OEBPS/two.xhtml": None}),
               epub({"META-INF/encryption.xml": "<encryption/>"}),
               epub({"OEBPS/book.opf": PACKAGE.replace('idref="two"', 'idref="missing"')}),
               epub({"OEBPS/book.opf": PACKAGE.replace('idref="one"', 'idref="two"')}),
               epub({"OEBPS/book.opf": PACKAGE.replace('id="one"', 'id="two"')}),
               epub({"OEBPS/two.xhtml": "<html/>"})]
        for i, data in enumerate(bad):
            with self.subTest(case=i), self.assertRaises(EpubError):
                read_epub(data)

    def test_empty_epub_rejected(self):
        no_text = "<html><body><script>bad</script></body></html>"
        with self.assertRaisesRegex(EpubError, "no readable"):
            read_epub(epub({"OEBPS/one.xhtml": no_text, "OEBPS/two.xhtml": no_text}))

    def test_crc_corruption_is_rejected(self):
        data = epub()
        # Stored ZIP contains literal document bytes; mutate payload, not CRC.
        data = data.replace(b"Antes ", b"Outro ", 1)
        with self.assertRaises(EpubError):
            read_epub(data)

    def test_encryption_flag_and_unsupported_compression_rejected(self):
        data = bytearray(epub())
        # Set the encryption bit on first central directory entry.
        index = data.index(b"PK\x01\x02")
        data[index + 8] |= 1
        with self.assertRaisesRegex(EpubError, "encrypted"):
            read_epub(bytes(data))
        with self.assertRaisesRegex(EpubError, "compression"):
            read_epub(epub(compression=zipfile.ZIP_BZIP2))

    def test_nested_hidden_headings_and_tail_do_not_become_title(self):
        chapter = '<html><body><div hidden="hidden"><h1>oculto</h1></div><h1>Correto</h1>Cauda<p>Corpo</p></body></html>'
        doc = read_epub(epub({"OEBPS/two.xhtml": chapter}))
        self.assertEqual(doc.chapters[0].title, "Correto")
        self.assertIn("Cauda", doc.text)
        self.assertNotIn("oculto", doc.text)

    def test_deep_xhtml_does_not_recurse(self):
        deep = "<html><body>" + "<span>" * 2000 + "conteúdo" + "</span>" * 2000 + "</body></html>"
        self.assertIn("conteúdo", extract_epub(epub({"OEBPS/two.xhtml": deep})))

    def test_heading_fallback_and_hidden_content(self):
        text = '<html><head><title>Do título</title></head><body><p>Texto</p><p hidden="hidden">oculto</p><p aria-hidden="true">oculto</p></body></html>'
        chapter = read_epub(epub({"OEBPS/two.xhtml": text})).chapters[0]
        self.assertEqual(chapter.title, "Do título")
        self.assertEqual(chapter.text, "Texto")


class M4BTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "input.wav"
        with wave.open(str(self.source), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00\x00" * 16000)
        self.target = self.root / "livro.m4b"

    def fake_success(self, cmd, **kwargs):
        self.command = cmd
        self.run_kwargs = kwargs
        metadata_path = Path(cmd[cmd.index("-f") + 3])
        self.metadata = metadata_path.read_text()
        Path(cmd[-1]).write_bytes(b"\x00\x00\x00\x18ftypM4B " + b"\x00" * 20)
        return subprocess.CompletedProcess(cmd, 0)

    @patch("document_features.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_builds_safe_argv_and_chapter_metadata(self, _):
        with patch("document_features.subprocess.run", side_effect=self.fake_success):
            result = export_m4b(self.source, self.target, title="Livro; #1=ação", author="Ana",
                                chapters=[AudioChapter("Primeiro\n[CHAPTER]", 0, 1000)], timeout=42)
        self.assertEqual(result, self.target)
        self.assertIn("-map_chapters", self.command)
        self.assertIn("-nostdin", self.command)
        self.assertEqual(self.run_kwargs["timeout"], 42)
        self.assertNotIn("shell", self.run_kwargs)
        self.assertIn(r"title=Livro\; \#1\=ação", self.metadata)
        self.assertIn("title=Primeiro [CHAPTER]", self.metadata)
        self.assertIn("TIMEBASE=1/1000\nSTART=0\nEND=1000", self.metadata)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["input.wav", "livro.m4b"])

    @patch("document_features.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_timeout_and_process_failure_leave_no_artifacts(self, _):
        for failure, expected in ((subprocess.TimeoutExpired("ffmpeg", 1), M4BTimeoutError),
                                  (subprocess.CalledProcessError(1, "ffmpeg"), M4BError),
                                  (OSError("missing"), M4BError)):
            with self.subTest(failure=failure), patch("document_features.subprocess.run", side_effect=failure):
                with self.assertRaises(expected):
                    export_m4b(self.source, self.target)
            self.assertEqual(list(self.root.iterdir()), [self.source])

    @patch("document_features.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_fake_success_without_valid_container_is_rejected(self, _):
        with patch("document_features.subprocess.run", return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaisesRegex(M4BError, "valid output"):
                export_m4b(self.source, self.target)
        self.assertFalse(self.target.exists())

    def test_ffmpeg_unavailable(self):
        with patch("document_features.shutil.which", return_value=None), self.assertRaisesRegex(M4BError, "unavailable"):
            export_m4b(self.source, self.target)

    def test_existing_target_never_overwritten(self):
        self.target.write_bytes(b"keep me")
        with self.assertRaisesRegex(M4BError, "already exists"):
            export_m4b(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), b"keep me")

    def test_output_symlink_not_followed(self):
        self.target.symlink_to(self.root / "missing")
        with self.assertRaisesRegex(M4BError, "already exists"):
            export_m4b(self.source, self.target)
        self.assertTrue(self.target.is_symlink())

    def test_metadata_escaping_and_validation(self):
        self.assertEqual(_metadata_escape("a\\b=c;d#e\nf\rg"), r"a\\b\=c\;d\#e f g")
        for metadata in ({"unsupported": "x"}, {"comment": "\x00"}, {"comment": 1}):
            with self.subTest(metadata=metadata), self.assertRaises(M4BError):
                export_m4b(self.source, self.target, metadata=metadata)

    def test_input_timeout_chapters_and_cover_validation(self):
        for timeout in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(timeout=timeout), self.assertRaises(M4BError):
                export_m4b(self.source, self.target, timeout=timeout)
        for chapters in ([AudioChapter("bad", -1, 20)], [AudioChapter("bad", 20, 20)],
                         [AudioChapter("bad", 0.5, 20)], [AudioChapter("bad", True, 20)],
                         [AudioChapter("a", 0, 10), AudioChapter("b", 9, 20)], ["not a chapter"]):
            with self.subTest(chapters=chapters), self.assertRaises(M4BError):
                export_m4b(self.source, self.target, chapters=chapters)
        with self.assertRaisesRegex(M4BError, "JPEG or PNG"):
            export_m4b(self.source, self.target, cover_path=self.source)
        with self.assertRaises(M4BError):
            export_m4b(self.root / "missing.wav", self.target)
        with self.assertRaises(M4BError):
            export_m4b(self.source, self.root / "output.mp3")

    @patch("document_features.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_optional_cover_mapping(self, _):
        cover = self.root / "cover.png"
        cover.write_bytes(b"\x89PNG\r\n\x1a\nheader")
        with patch("document_features.subprocess.run", side_effect=self.fake_success):
            export_m4b(self.source, self.target, cover_path=cover)
        self.assertIn("2:v:0", self.command)
        self.assertIn("attached_pic", self.command)
        self.assertIn(str(cover), self.command)

    @patch("document_features.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_racing_writer_is_not_overwritten(self, _):
        def race(cmd, **kwargs):
            self.fake_success(cmd, **kwargs)
            self.target.write_bytes(b"other writer")
        with patch("document_features.subprocess.run", side_effect=race), self.assertRaises(M4BError):
            export_m4b(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), b"other writer")


def ffmpeg_for_tests():
    binary = shutil.which("ffmpeg")
    if binary:
        return binary
    # Use only an already-installed imageio binary; never call a downloader.
    try:
        import imageio_ffmpeg
        candidates = sorted((Path(imageio_ffmpeg.__file__).parent / "binaries").glob("ffmpeg-linux*"))
        return str(candidates[0]) if candidates else None
    except ImportError:
        return None


class RealFFmpegTests(unittest.TestCase):
    """Optional real binary tests; no synthesized speech or model dependency."""
    setUp = M4BTests.setUp

    def test_real_m4b_without_cover_or_chapters(self):
        binary = ffmpeg_for_tests()
        if binary is None:
            self.skipTest("No preinstalled FFmpeg binary")
        output = export_m4b(self.source, self.target, title="Sem capa", ffmpeg=binary, timeout=30)
        inspection = subprocess.run([binary, "-hide_banner", "-i", str(output), "-f", "ffmetadata", "-"],
                                    capture_output=True, text=True, check=True, timeout=30)
        self.assertIn("title=Sem capa", inspection.stdout)
        self.assertIn("Audio: aac", inspection.stderr)
        self.assertNotIn("attached pic", inspection.stderr)
        self.assertNotIn("[CHAPTER]", inspection.stdout)

    def test_real_m4b_encodes_audio_metadata_chapters_and_cover(self):
        binary = ffmpeg_for_tests()
        if binary is None:
            self.skipTest("No preinstalled FFmpeg binary")
        # Tiny built-in PNG avoids depending on Pillow.
        import base64
        cover = self.root / "cover.png"
        cover.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aKxQAAAAASUVORK5CYII="))
        output = export_m4b(self.source, self.target, title="Livro de ação", author="Ana",
                            chapters=[AudioChapter("Primeiro", 0, 500), AudioChapter("Segundo", 500, 1000)],
                            cover_path=cover, ffmpeg=binary, timeout=30)
        self.assertGreater(output.stat().st_size, 100)
        inspection = subprocess.run([binary, "-hide_banner", "-i", str(output), "-f", "ffmetadata", "-"],
                                    capture_output=True, text=True, check=True, timeout=30)
        self.assertIn("title=Livro de ação", inspection.stdout)
        self.assertIn("artist=Ana", inspection.stdout)
        self.assertIn("title=Primeiro", inspection.stdout)
        self.assertIn("title=Segundo", inspection.stdout)
        self.assertIn("START=500", inspection.stdout)
        self.assertIn("END=1000", inspection.stdout)
        self.assertIn("attached pic", inspection.stderr)
        self.assertIn("Audio: aac", inspection.stderr)
        decode = subprocess.run([binary, "-v", "error", "-i", str(output), "-map", "0:a:0", "-f", "null", "-"],
                                capture_output=True, timeout=30)
        self.assertEqual(decode.returncode, 0, decode.stderr)

    def test_real_timeout_kills_process_and_cleans_up(self):
        # A fake local executable exercises subprocess.run's actual kill/wait path.
        fake = self.root / "sleeping-ffmpeg"
        fake.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(10)\n")
        fake.chmod(0o700)
        with self.assertRaises(M4BTimeoutError):
            export_m4b(self.source, self.target, ffmpeg=str(fake), timeout=0.1)
        self.assertFalse(self.target.exists())
        self.assertFalse(list(self.root.glob("m4b-*")))


if __name__ == "__main__":
    unittest.main()
