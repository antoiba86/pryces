import pytest

from pryces.infrastructure.importers.ibkr import IbkrFlexImporter

_SAMPLE_FLEX = (
    "<FlexQueryResponse><FlexStatements><FlexStatement>"
    '<Trades><Trade symbol="AAPL" quantity="5" tradePrice="185.00" '
    'currency="USD" ibCommission="-1.0" tradeDate="20240110" /></Trades>'
    "</FlexStatement></FlexStatements></FlexQueryResponse>"
)


def test_broker_id():
    assert IbkrFlexImporter().broker_id == "ibkr"


def test_never_auto_detects_until_implemented():
    assert IbkrFlexImporter().can_parse(_SAMPLE_FLEX) is False


@pytest.mark.xfail(reason="IBKR Flex importer not yet implemented", strict=True)
def test_parses_ibkr_flex_statement():
    result = IbkrFlexImporter().parse(_SAMPLE_FLEX)

    assert len(result.transactions) == 1
    assert result.transactions[0].symbol == "AAPL"
