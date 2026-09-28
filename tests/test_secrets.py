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


def test_bitwarden_login_username():
    run = runner_returning({"login": {"username": "me@example.com", "password": "tok"}})
    env = {"JIRA_USER_BW_ITEM": "jira", "JIRA_USER_BW_FIELD": "username"}
    assert get("JIRA_USER", environ=env, runner=run) == "me@example.com"
    with pytest.raises(SecretUnavailable, match="no login username"):
        get("JIRA_USER", environ=env, runner=runner_returning({"login": {"password": "tok"}}))


AMBIGUOUS = ("More than one result was found. Try getting a specific object by `id` instead. "
             "The following objects were found:\nid-1\nid-2")


def scripted(*answers):
    calls = []

    def run(argv):
        calls.append(argv)
        return answers[len(calls) - 1]

    run.calls = calls
    return run


def test_a_name_several_items_match_takes_the_one_named_exactly_that():
    listed = [{"name": "content_manager:plane:api_key", "login": {"password": "no"}},
              {"name": "Plane", "fields": [{"name": "API", "value": "yes"}]}]
    run = scripted((1, "", AMBIGUOUS), (0, json.dumps(listed), ""))
    env = {"PLANE_API_KEY_BW_ITEM": "Plane", "PLANE_API_KEY_BW_FIELD": "API", "BW_SESSION": "sess"}
    assert get("PLANE_API_KEY", environ=env, runner=run) == "yes"
    assert run.calls[1] == ["bw", "list", "items", "--search", "Plane", "--nointeraction", "--session", "sess"]
    # none named exactly that, or two: say so and ask for the id
    for names in (["Plane API", "plane"], ["Plane", "Plane"]):
        run = scripted((1, "", AMBIGUOUS), (0, json.dumps([{"name": n} for n in names]), ""))
        with pytest.raises(SecretUnavailable, match="by its id"):
            get("PLANE_API_KEY", environ=env, runner=run)


def test_locked_vault_hints_at_unlock_without_echoing_anything():
    run = runner_returning("", code=1, err="Vault is locked.")
    with pytest.raises(SecretUnavailable) as exc:
        get("PLANE_API_KEY", environ={"PLANE_API_KEY_BW_ITEM": "Plane API"}, runner=run)
    assert "bw unlock --raw" in str(exc.value)
    run = runner_returning("not json")
    with pytest.raises(SecretUnavailable, match="non-JSON"):
        get("PLANE_API_KEY", environ={"PLANE_API_KEY_BW_ITEM": "Plane API"}, runner=run)
