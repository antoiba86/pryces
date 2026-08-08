import logging
from logging.handlers import RotatingFileHandler
from unittest.mock import MagicMock, patch

import pytest

from pryces.infrastructure.logging import (
    LoggingSettings,
    PythonLogger,
    PythonLoggerFactory,
    setup_logging,
)


class TestPythonLogger:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.inner = MagicMock(spec=logging.Logger)
        self.logger = PythonLogger(self.inner)

    def test_debug_delegates_to_inner(self):
        self.logger.debug("debug msg")

        self.inner.debug.assert_called_once_with("debug msg")

    def test_info_delegates_to_inner(self):
        self.logger.info("info msg")

        self.inner.info.assert_called_once_with("info msg")

    def test_warning_delegates_to_inner(self):
        self.logger.warning("warning msg")

        self.inner.warning.assert_called_once_with("warning msg")

    def test_error_delegates_to_inner(self):
        self.logger.error("error msg")

        self.inner.error.assert_called_once_with("error msg")


class TestPythonLoggerFactory:
    def test_get_logger_returns_python_logger_instance(self):
        factory = PythonLoggerFactory()

        result = factory.get_logger("some.module")

        assert isinstance(result, PythonLogger)

    def test_get_logger_wraps_correct_logger(self):
        factory = PythonLoggerFactory()

        with patch("pryces.infrastructure.logging.logging.getLogger") as mock_get:
            mock_get.return_value = MagicMock(spec=logging.Logger)
            factory.get_logger("my.module")

        mock_get.assert_called_once_with("my.module")


class TestSetupLogging:
    @pytest.fixture(autouse=True)
    def restore_root_logger(self):
        root = logging.getLogger()
        original = list(root.handlers)
        root.handlers.clear()
        yield
        for handler in root.handlers:
            handler.close()
        root.handlers[:] = original

    def _file_handlers(self):
        return [h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler)]

    def test_log_filename_is_stable_across_runs(self, tmp_path):
        # The bug this pins: a timestamped filename opened a brand-new file on
        # every process start, so backup_count never bounded anything and old
        # logs accumulated forever.
        settings = LoggingSettings(entry_point="api", logs_directory=str(tmp_path))

        setup_logging(settings)
        first = self._file_handlers()[0].baseFilename
        logging.getLogger().handlers.clear()
        setup_logging(settings)
        second = self._file_handlers()[0].baseFilename

        assert first == second
        assert first.endswith("pryces_api.log")

    def test_a_restart_appends_rather_than_starting_a_new_file(self, tmp_path):
        settings = LoggingSettings(entry_point="api", logs_directory=str(tmp_path))

        for _ in range(3):
            setup_logging(settings)
            logging.getLogger().info("hello")
            for handler in self._file_handlers():
                handler.close()
            logging.getLogger().handlers.clear()

        assert [p.name for p in tmp_path.iterdir()] == ["pryces_api.log"]
        assert tmp_path.joinpath("pryces_api.log").read_text().count("hello") == 3

    def test_rotation_bounds_the_number_of_files(self, tmp_path):
        settings = LoggingSettings(
            entry_point="api", logs_directory=str(tmp_path), max_bytes=256, backup_count=2
        )
        setup_logging(settings)

        for index in range(200):
            logging.getLogger().info(f"line {index} " + "x" * 40)

        # The active file plus at most backup_count rolled copies — never more.
        assert len(list(tmp_path.iterdir())) == 3

    def test_entry_point_names_the_file(self, tmp_path):
        setup_logging(LoggingSettings(entry_point="monitor", logs_directory=str(tmp_path)))

        assert self._file_handlers()[0].baseFilename.endswith("pryces_monitor.log")

    def test_no_file_handler_without_a_logs_directory(self):
        setup_logging(LoggingSettings(entry_point="api"))

        assert self._file_handlers() == []

    def test_missing_logs_directory_is_ignored(self, tmp_path):
        setup_logging(LoggingSettings(entry_point="api", logs_directory=str(tmp_path / "nope")))

        assert self._file_handlers() == []
