import bcrypt


class PasswordHasher:
    """bcrypt password hashing (async-safe: bcrypt releases the GIL).

    Cost factor comes from settings.password_hash_rounds, read at call time
    so tests can monkeypatch it without reimporting this module."""

    @staticmethod
    def hash(password: str) -> str:
        from src.settings import settings

        return bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt(rounds=settings.password_hash_rounds)
        ).decode("utf-8")

    @staticmethod
    def verify(password: str, password_hash: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        except ValueError:
            return False
