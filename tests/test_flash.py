# Tests of scripts/snapmaker_j1_flash.py: python -m unittest discover tests
import importlib.util
import os
import struct
import sys
import types
import unittest

try:
    import serial  # noqa: F401
except ImportError:
    # The image and frame checks do not use the port
    sys.modules["serial"] = types.ModuleType("serial")

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                       "scripts")
_spec = importlib.util.spec_from_file_location(
    "snapmaker_j1_flash", os.path.join(SCRIPTS, "snapmaker_j1_flash.py"))
flash = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(flash)
_spec = importlib.util.spec_from_file_location(
    "snapmaker_j1_package", os.path.join(SCRIPTS, "snapmaker_j1_package.py"))
package = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(package)

APP_START = 0x08002800


def make_app(app_start=APP_START):
    # Vector table: stack pointer in RAM, reset handler (thumb) in the app
    return struct.pack("<II", 0x20018000, app_start + 9) + bytes(range(200))


def make_image(app_start=APP_START):
    app = make_app(app_start)
    fields = [flash.FILE_FLAG, 1, flash.IMAGE_TYPE_MC, 0, 0, 0, b"V1.2.3",
              b"", 0, len(app), flash.checksum32(app), app_start, 0, 0]
    hdr = struct.pack(flash.HEADER_FORMAT, *(fields + [0]))
    hdr = struct.pack(flash.HEADER_FORMAT,
                      *(fields + [flash.checksum32(hdr[:-4])]))
    return hdr.ljust(flash.HEADER_SIZE, b"\0") + app


class ImageTest(unittest.TestCase):
    def test_valid_image(self):
        image = flash.check_image(make_image())
        self.assertEqual(image["start"], APP_START)
        self.assertEqual(image["version"], "V1.2.3")
        self.assertEqual(len(image["app"]), 208)

    def test_damaged_images(self):
        data = make_image()
        cases = {
            "Application checksum": data[:-1] + b"\xff",
            "truncated": data[:-10],
            "header checksum": data[:30] + b"X" + data[31:],
            "overlap the bootloader": make_image(0x08000000),
        }
        for message, image in cases.items():
            with self.subTest(message):
                with self.assertRaisesRegex(flash.FlashError, message):
                    flash.check_image(image)

    def test_update_package(self):
        image = make_image()
        toc = bytearray(100)
        toc[flash.UPDATE_TOC_COUNT_OFFSET] = 1
        struct.pack_into(">BII", toc, flash.UPDATE_TOC_COUNT_OFFSET + 1,
                         flash.UPDATE_ENTRY_MC, len(toc), len(image))
        update_bin = bytes(toc) + image + b"display files"
        self.assertEqual(flash.extract_mc_bin(update_bin), image)
        with self.assertRaises(flash.FlashError):
            flash.extract_mc_bin(bytes(100))

    def test_build_passes_the_flash_checks(self):
        # snapmaker_j1_package.py (firmware/build.sh) and the flash tool
        # have their own copies of the header format and checksum
        app = make_app(package.APP_START)
        update_bin = package.build_update_bin(
            package.build_mc_bin(app, "Klipper v1"), "Klipper v1")
        image = flash.check_image(flash.extract_mc_bin(update_bin))
        self.assertEqual(image["app"], app)
        self.assertEqual(image["start"], package.APP_START)
        self.assertEqual(image["version"], "Klipper v1")


class FrameTest(unittest.TestCase):
    def test_frame_between_log_text(self):
        frame = flash.build_frame(flash.ID_CONTROLLER, flash.ATTR_ACK, 7,
                                  flash.CMD_SET_UPDATE, flash.CMD_PACKAGE,
                                  b"\x00payload")
        data = b"bootloader start\r\n" + frame + b"done\n"
        parser = flash.FrameParser()
        self.assertEqual(parser.feed(data[:25]), [])
        frames = parser.feed(data[25:])
        self.assertEqual(len(frames), 1)
        f = frames[0]
        self.assertEqual((f.sequence, f.command_set, f.command_id, f.payload),
                         (7, flash.CMD_SET_UPDATE, flash.CMD_PACKAGE,
                          b"\x00payload"))
        self.assertEqual(parser.lines(), ["bootloader start", "done"])

    def test_corrupt_frame_is_dropped(self):
        frame = bytearray(flash.build_frame(
            flash.ID_CONTROLLER, flash.ATTR_REQ, 1, flash.CMD_SET_UPDATE,
            flash.CMD_START, b"\x00"))
        frame[-3] ^= 0xff
        self.assertEqual(flash.FrameParser().feed(bytes(frame)), [])


if __name__ == "__main__":
    unittest.main()
