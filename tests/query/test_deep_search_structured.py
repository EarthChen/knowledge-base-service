import pytest

from query.deep_search import _extract_business_flows, _extract_code_locations


def test_extract_code_locations_from_draft():
    draft = "The authentication is handled in `src/auth/service.py` (line 45). See also `api/routes/auth.py`."
    locs = _extract_code_locations(draft)
    assert len(locs) >= 2
    assert any("auth/service.py" in loc["path"] for loc in locs)


def test_extract_code_locations_empty_draft():
    assert _extract_code_locations("") == []


def test_extract_business_flows_from_draft():
    draft = (
        "The login flow works as: User → AuthService → JWTProvider → Database. "
        "The registration flow is: User → RegistrationService → EmailService."
    )
    flows = _extract_business_flows(draft)
    assert len(flows) >= 1


def test_extract_business_flows_no_arrows():
    assert _extract_business_flows("Simple text with no flows.") == []
