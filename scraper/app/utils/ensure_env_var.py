import os


def ensure_env_var(var_name: str) -> str:
    """
    Ensure that the environment variable is set.
    Raises ValueError if the variable is not set.
    """
    value = os.getenv(var_name)
    if not value:
        raise ValueError(f"'{var_name}' environment variable is not set.")
    return value
