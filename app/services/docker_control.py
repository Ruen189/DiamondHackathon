import subprocess


def compose_ps() -> str:
    result = subprocess.run(
        ["docker", "compose", "ps", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def is_server_running() -> bool:
    output = compose_ps().lower()
    return "llama-server" in output and "running" in output


def start_server() -> tuple[bool, str]:
    if is_server_running():
        return False, "Сервер уже запущен."
    result = subprocess.run(
        ["docker", "compose", "up", "-d"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True, "Сервер успешно запущен через docker-compose."
    return False, f"Ошибка запуска: {result.stderr.strip() or result.stdout.strip()}"
