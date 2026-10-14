#!/usr/bin/env python3
"""Démarre l'API et l'interface Kronos, puis ouvre le navigateur.

Premier lancement : crée un environnement Python local et installe les dépendances.
Les lancements suivants réutilisent cet environnement.
"""
from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIREMENTS = ROOT / "datafeed_tester" / "requirements.txt"
VENV = ROOT / ".venv"
PORT = int(os.environ.get("PORT", "5002"))
URL = f"http://127.0.0.1:{PORT}/"
HEALTH = f"http://127.0.0.1:{PORT}/health"


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def python_ok(executable: str) -> bool:
    try:
        out = subprocess.check_output(
            [executable, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return False
    major, minor = (int(part) for part in out.split(".")[:2])
    return (major, minor) >= (3, 11)


def find_base_python() -> str:
    if python_ok(sys.executable) and Path(sys.executable).resolve() != venv_python().resolve():
        return sys.executable
    names = ["python3.12", "python3.13", "python3.11", "python3", "python"]
    for name in names:
        if python_ok(name):
            return name
    print("Python 3.11 ou plus récent est introuvable.")
    print("Sur le Mac : installe Python depuis https://www.python.org/downloads/ puis relance Kronos.")
    raise SystemExit(1)


def requirements_stamp() -> str:
    digest = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    return digest


def ensure_venv() -> Path:
    python = venv_python()
    stamp = VENV / ".kronos-deps"
    expected = requirements_stamp()
    if not python.exists():
        base = find_base_python()
        print("Création de l'environnement local…")
        subprocess.check_call([base, "-m", "venv", str(VENV)])
    if not stamp.exists() or stamp.read_text(encoding="utf-8").strip() != expected:
        print("Installation des dépendances. Le premier lancement peut prendre plusieurs minutes.")
        subprocess.check_call([str(python), "-m", "pip", "install", "--upgrade", "pip"])
        subprocess.check_call([str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS)])
        stamp.write_text(expected, encoding="utf-8")
    return python


def health_ok() -> bool:
    try:
        with urllib.request.urlopen(HEALTH, timeout=1) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def port_busy() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", PORT)) == 0


def main() -> None:
    if health_ok():
        print(f"Kronos tourne déjà. Ouverture de {URL}")
        webbrowser.open(URL)
        return

    if port_busy():
        print(f"Le port {PORT} est déjà utilisé par un autre programme.")
        raise SystemExit(1)

    python = ensure_venv()
    env = os.environ.copy()
    env["PORT"] = str(PORT)
    env["KRONOS_HOST"] = "127.0.0.1"
    env["PYTHONUNBUFFERED"] = "1"
    print("Démarrage de Kronos…")
    process = subprocess.Popen(
        [str(python), str(ROOT / "datafeed_tester" / "app.py")],
        cwd=str(ROOT),
        env=env,
    )
    try:
        for _ in range(360):
            if process.poll() is not None:
                print("Le serveur s'est arrêté pendant le démarrage.")
                raise SystemExit(process.returncode or 1)
            if health_ok():
                print(f"Interface prête : {URL}")
                print("Laisse cette fenêtre ouverte. La fermer arrête Kronos.")
                webbrowser.open(URL)
                process.wait()
                return
            time.sleep(0.5)
        print("Le serveur n'a pas répondu à temps.")
        raise SystemExit(1)
    except KeyboardInterrupt:
        pass
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
