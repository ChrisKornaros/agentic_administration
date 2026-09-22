"""The secrets boundary. No real `bw` is ever run: the runner is injected."""

import json

import pytest

from server.secrets import SecretUnavailable, get


def runner_returning(payload, code=0, err=""):
    calls = []

    def run(argv):
        calls.append(argv)
        return code, json.dumps(payload) if not isinstance(payload, str) else payload, err

    run.calls = calls
    return run


def test_environment_wins_and_bw_is_not_called():
    run = runner_returning({})
    assert get("PLANE_API_KEY", environ={"PLANE_API_KEY": " tok ", "PLANE_API_KEY_BW_ITEM": "x"}, runner=run) == "tok"
    assert run.calls == []


def test_missing_everything_names_the_variables_not_a_value():
    with pytest.raises(SecretUnavailable) as exc:
        get("PLANE_API_KEY", environ={}, runner=runner_returning({}))
    assert "PLANE_API_KEY_BW_ITEM" in str(exc.value)


def test_bitwarden_password_field_by_default():
    run = runner_returning({"login": {"password": "s3cret"}})
    env = {"PLANE_API_KEY_BW_ITEM": "Plane API", "BW_SESSION": "sess"}
    assert get("PLANE_API_KEY", environ=env, runner=run) == "s3cret"
    assert run.calls == [["bw", "get", "item", "Plane API", "--nointeraction", "--session", "sess"]]


def test_bitwarden_custom_field():
    run = runner_returning({"login": {"password": "no"}, "fields": [{"name": "plane_api_key", "value": "yes"}]})
    env = {"PLANE_API_KEY_BW_ITEM": "Plane API", "PLANE_API_KEY_BW_FIELD": "plane_api_key"}
    assert get("PLANE_API_KEY", environ=env, runner=run) == "yes"
    with pytest.raises(SecretUnavailable, match="no custom field 'other'"):
        get("PLANE_API_KEY", environ={**env, "PLANE_API_KEY_BW_FIELD": "other"}, runner=run)


def test_locked_vault_hints_at_unlock_without_echoing_anything():
    run = runner_returning("", code=1, err="Vault is locked.")
    with pytest.raises(SecretUnavailable) as exc:
        get("PLANE_API_KEY", environ={"PLANE_API_KEY_BW_ITEM": "Plane API"}, runner=run)
    assert "bw unlock --raw" in str(exc.value)
    run = runner_returning("not json")
    with pytest.raises(SecretUnavailable, match="non-JSON"):
        get("PLANE_API_KEY", environ={"PLANE_API_KEY_BW_ITEM": "Plane API"}, runner=run)
