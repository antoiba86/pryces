import pytest

from pryces.infrastructure.exceptions import ConfigurationError
from pryces.infrastructure.factories import SettingsFactory


class TestCreateYahooFinanceSettings:
    def test_happy_path(self, monkeypatch):
        monkeypatch.setenv("MAX_FETCH_WORKERS", "4")
        settings = SettingsFactory.create_yahoo_finance_settings()
        assert settings.max_workers == 4
        assert settings.extra_delay_in_minutes == 0

    def test_passes_extra_delay_through(self, monkeypatch):
        monkeypatch.setenv("MAX_FETCH_WORKERS", "2")
        settings = SettingsFactory.create_yahoo_finance_settings(extra_delay_in_minutes=5)
        assert settings.extra_delay_in_minutes == 5

    def test_missing_env_var_raises_configuration_error(self, monkeypatch):
        monkeypatch.delenv("MAX_FETCH_WORKERS", raising=False)
        with pytest.raises(ConfigurationError):
            SettingsFactory.create_yahoo_finance_settings()

    def test_non_integer_env_var_raises_configuration_error(self, monkeypatch):
        monkeypatch.setenv("MAX_FETCH_WORKERS", "not-a-number")
        with pytest.raises(ConfigurationError):
            SettingsFactory.create_yahoo_finance_settings()

    def test_empty_string_env_var_raises_configuration_error(self, monkeypatch):
        monkeypatch.setenv("MAX_FETCH_WORKERS", "")
        with pytest.raises(ConfigurationError):
            SettingsFactory.create_yahoo_finance_settings()

    def test_negative_env_var_is_accepted(self, monkeypatch):
        monkeypatch.setenv("MAX_FETCH_WORKERS", "-1")
        settings = SettingsFactory.create_yahoo_finance_settings()
        assert settings.max_workers == -1

    def test_zero_env_var_is_accepted(self, monkeypatch):
        monkeypatch.setenv("MAX_FETCH_WORKERS", "0")
        settings = SettingsFactory.create_yahoo_finance_settings()
        assert settings.max_workers == 0


class TestCreateCacheSettings:
    def test_defaults_to_five_minutes_when_unset(self, monkeypatch):
        monkeypatch.delenv("CACHE_TTL_SECONDS", raising=False)
        assert SettingsFactory.create_cache_settings().ttl_seconds == 300

    def test_defaults_when_empty_string(self, monkeypatch):
        monkeypatch.setenv("CACHE_TTL_SECONDS", "")
        assert SettingsFactory.create_cache_settings().ttl_seconds == 300

    def test_reads_override(self, monkeypatch):
        monkeypatch.setenv("CACHE_TTL_SECONDS", "60")
        assert SettingsFactory.create_cache_settings().ttl_seconds == 60

    def test_zero_disables_caching(self, monkeypatch):
        monkeypatch.setenv("CACHE_TTL_SECONDS", "0")
        assert SettingsFactory.create_cache_settings().ttl_seconds == 0

    def test_non_integer_raises(self, monkeypatch):
        monkeypatch.setenv("CACHE_TTL_SECONDS", "abc")
        with pytest.raises(ConfigurationError):
            SettingsFactory.create_cache_settings()

    def test_negative_raises(self, monkeypatch):
        monkeypatch.setenv("CACHE_TTL_SECONDS", "-5")
        with pytest.raises(ConfigurationError):
            SettingsFactory.create_cache_settings()


class TestCreateClosedMarketCacheSettings:
    def test_defaults_to_one_hour_when_unset(self, monkeypatch):
        monkeypatch.delenv("CACHE_CLOSED_TTL_SECONDS", raising=False)
        assert SettingsFactory.create_closed_market_cache_settings().ttl_seconds == 3600

    def test_reads_override(self, monkeypatch):
        monkeypatch.setenv("CACHE_CLOSED_TTL_SECONDS", "86400")
        assert SettingsFactory.create_closed_market_cache_settings().ttl_seconds == 86400

    def test_non_integer_raises(self, monkeypatch):
        monkeypatch.setenv("CACHE_CLOSED_TTL_SECONDS", "abc")
        with pytest.raises(ConfigurationError):
            SettingsFactory.create_closed_market_cache_settings()


class TestCreateFxCacheSettings:
    def test_defaults_to_one_hour_when_unset(self, monkeypatch):
        monkeypatch.delenv("CACHE_FX_TTL_SECONDS", raising=False)
        assert SettingsFactory.create_fx_cache_settings().ttl_seconds == 3600

    def test_reads_override(self, monkeypatch):
        monkeypatch.setenv("CACHE_FX_TTL_SECONDS", "120")
        assert SettingsFactory.create_fx_cache_settings().ttl_seconds == 120

    def test_zero_disables_caching(self, monkeypatch):
        monkeypatch.setenv("CACHE_FX_TTL_SECONDS", "0")
        assert SettingsFactory.create_fx_cache_settings().ttl_seconds == 0

    def test_non_integer_raises(self, monkeypatch):
        monkeypatch.setenv("CACHE_FX_TTL_SECONDS", "abc")
        with pytest.raises(ConfigurationError):
            SettingsFactory.create_fx_cache_settings()

    def test_negative_raises(self, monkeypatch):
        monkeypatch.setenv("CACHE_FX_TTL_SECONDS", "-5")
        with pytest.raises(ConfigurationError):
            SettingsFactory.create_fx_cache_settings()


class TestCreateTelegramSettings:
    def test_happy_path(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token123")
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "group456")
        settings = SettingsFactory.create_telegram_settings()
        assert settings.bot_token == "token123"
        assert settings.group_id == "group456"

    def test_missing_bot_token_raises_configuration_error(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.setenv("TELEGRAM_GROUP_ID", "group456")
        with pytest.raises(ConfigurationError):
            SettingsFactory.create_telegram_settings()

    def test_missing_group_id_raises_configuration_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token123")
        monkeypatch.delenv("TELEGRAM_GROUP_ID", raising=False)
        with pytest.raises(ConfigurationError):
            SettingsFactory.create_telegram_settings()
