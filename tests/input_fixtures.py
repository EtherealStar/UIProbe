def case():
    return {
        "id": "login",
        "name": "Login",
        "checkpoints": [
            {
                "id": "home",
                "execution": {"goal": "Login", "instructions": []},
                "assertions": [{"id": "home", "expected": "Home visible"}],
            }
        ],
    }


def config(directory: str) -> dict[str, object]:
    return dict(
        entry_url="http://127.0.0.1/login",
        data_values={"password": "secret-value"},
        max_actions=10,
        execution_request_limit=20,
        verification_request_limit=3,
        tool_call_limit=30,
        tool_retry_limit=2,
        verification_retry_limit=2,
        timeout_seconds=60,
        output_dir=directory,
    )


def prepared_case(defaults):
    import json

    from uiprobe.case_input import prepare_suite

    suite = prepare_suite(json.dumps(case()), {"defaults": defaults})
    prepared = suite.entries[0].prepared
    assert prepared is not None, suite
    return prepared
