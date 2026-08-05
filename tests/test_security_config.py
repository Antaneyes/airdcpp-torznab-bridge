import pytest
from pydantic import SecretStr

from app.config import Settings
from app.core.security import valid_login


def test_runtime_validation_and_login(tmp_path):
    with pytest.raises(ValueError, match="AIRDCPP_USER"):
        Settings(data_dir=tmp_path).validate_runtime()
    settings = Settings(
        data_dir=tmp_path,
        airdcpp_user="air",
        airdcpp_pass=SecretStr("pass"),
        bridge_api_key=SecretStr("api"),
        bridge_username="arr",
        bridge_password=SecretStr("secret"),
    )
    settings.validate_runtime()
    assert valid_login("arr", "secret", settings)
    assert not valid_login("arr", "wrong", settings)
    assert Settings(allow_insecure=True, airdcpp_user="air", airdcpp_pass=SecretStr("pass")).allow_insecure
