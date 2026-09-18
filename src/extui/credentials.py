from __future__ import annotations

import os

KEYCHAIN_SERVICE = "dev.extui.exaroton"
KEYCHAIN_ACCOUNT = "api-token"
ENV_VAR = "EXAROTON_TOKEN"

NO_KEYRING_HELP = (
    f"No system keyring is available, which is normal on a headless server or in a "
    f"container. Set the {ENV_VAR} environment variable to your exaroton API token "
    f"instead, for example: export {ENV_VAR}=your-token"
)


class CredentialError(RuntimeError):
    pass


class NoKeyringAvailable(CredentialError):
    def __init__(self) -> None:
        super().__init__(NO_KEYRING_HELP)


def _keyring():
    import keyring
    from keyring.backends.fail import Keyring as FailKeyring

    if isinstance(keyring.get_keyring(), FailKeyring):
        raise NoKeyringAvailable
    return keyring


class CredentialStore:
    def __init__(self, service: str = KEYCHAIN_SERVICE, account: str = KEYCHAIN_ACCOUNT) -> None:
        self.service = service
        self.account = account

    def read_token(self) -> str | None:
        env = os.environ.get(ENV_VAR)
        if env and env.strip():
            return env.strip()
        try:
            value = _keyring().get_password(self.service, self.account)
        except NoKeyringAvailable:
            return None
        except Exception:
            return None
        return value.strip() if value else None

    def save_token(self, token: str) -> None:
        token = token.strip()
        if not token:
            raise CredentialError("Token cannot be empty.")
        try:
            _keyring().set_password(self.service, self.account, token)
        except NoKeyringAvailable:
            raise
        except Exception as error:
            raise CredentialError(f"Could not write to the system keyring: {error}") from error

    def delete_token(self) -> None:
        try:
            from keyring.errors import PasswordDeleteError

            try:
                _keyring().delete_password(self.service, self.account)
            except PasswordDeleteError:
                pass
        except NoKeyringAvailable:
            pass
        except Exception as error:
            raise CredentialError(f"Could not remove the token from the system keyring: {error}") from error
