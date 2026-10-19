"""An optional PIN / password that is asked before anything is edited or deleted.

Only a salted hash of it is stored in the data file, never the PIN itself.  It guards the
screens of the program; it does not encrypt the data file.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

SETTING_SALT = "pin_salt"
SETTING_HASH = "pin_hash"
MIN_PIN_LENGTH = 4
_ROUNDS = 200_000


class PinError(ValueError):
    """The PIN is too short, was typed differently twice, or is not the current one."""


def _digest(pin: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, _ROUNDS)


class SecurityMixin:
    def pin_is_set(self) -> bool:
        return bool(self.get_setting(SETTING_HASH))

    def check_pin(self, pin: str) -> bool:
        """True when no PIN is set, or ``pin`` is the right one."""
        stored, salt = self.get_setting(SETTING_HASH), self.get_setting(SETTING_SALT)
        if not stored or not salt:
            return True
        try:
            expected = base64.b64decode(stored)
            return hmac.compare_digest(_digest(pin or "", base64.b64decode(salt)), expected)
        except ValueError:
            return False

    def set_pin(self, new_pin: str, current_pin: str | None = None) -> None:
        """Set or change the PIN.  Changing it needs the current one."""
        if self.pin_is_set() and not self.check_pin(current_pin or ""):
            raise PinError("The current PIN is not right.")
        new_pin = new_pin or ""
        if len(new_pin) < MIN_PIN_LENGTH:
            raise PinError(f"The PIN needs at least {MIN_PIN_LENGTH} characters.")
        salt = os.urandom(16)
        with self.tx():
            self.set_setting(SETTING_SALT, base64.b64encode(salt).decode())
            self.set_setting(SETTING_HASH, base64.b64encode(_digest(new_pin, salt)).decode())
            self.log("PIN changed" if current_pin is not None else "PIN set",
                     "Editing and deleting now ask for the PIN")

    def remove_pin(self, current_pin: str) -> None:
        if not self.check_pin(current_pin or ""):
            raise PinError("The PIN is not right.")
        self.clear_pin()

    def clear_pin(self) -> None:
        """Take the PIN away without asking (forgotten PIN: ``python main.py --reset-pin``)."""
        with self.tx():
            self.conn.execute("DELETE FROM settings WHERE key IN (?, ?)",
                              (SETTING_HASH, SETTING_SALT))
            self.log("PIN removed", "Editing and deleting no longer ask for a PIN")
