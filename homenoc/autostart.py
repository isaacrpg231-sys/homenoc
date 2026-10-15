"""
"Iniciar com o Windows": cria um atalho na pasta Inicializar do usuário que
abre o HomeNOC em segundo plano (sem janela) quando o Windows liga.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .rede import WINDOWS

NOME_ATALHO = "HomeNOC.lnk"
RAIZ = Path(__file__).resolve().parent.parent      # pasta que contém HomeNOC.pyw


def suportado() -> bool:
    return WINDOWS and bool(os.environ.get("APPDATA"))


def _pasta_inicializar() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _atalho() -> Path:
    return _pasta_inicializar() / NOME_ATALHO


def ativo() -> bool:
    return suportado() and _atalho().exists()


def _pythonw() -> str:
    exe = Path(sys.executable)
    candidato = exe.with_name("pythonw.exe")
    return str(candidato if candidato.exists() else exe)


def _aspas_ps(texto: str) -> str:
    """Texto entre aspas simples do PowerShell (aspas simples internas são dobradas)."""
    return "'" + texto.replace("'", "''") + "'"


def script_atalho(destino: Path, alvo: str, argumentos: str, pasta: Path) -> str:
    return "; ".join([
        "$w = New-Object -ComObject WScript.Shell",
        f"$s = $w.CreateShortcut({_aspas_ps(str(destino))})",
        f"$s.TargetPath = {_aspas_ps(alvo)}",
        f"$s.Arguments = {_aspas_ps(argumentos)}",
        f"$s.WorkingDirectory = {_aspas_ps(str(pasta))}",
        "$s.WindowStyle = 7",
        "$s.Description = 'HomeNOC - monitor da rede de casa'",
        "$s.Save()",
    ])


def ativar() -> tuple[bool, str]:
    if not suportado():
        return False, "Disponível só no Windows."
    lancador = RAIZ / "HomeNOC.pyw"
    script = script_atalho(_atalho(), _pythonw(), f'"{lancador}" --sem-navegador', RAIZ)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Não consegui criar o atalho: {exc}"
    if r.returncode != 0 or not _atalho().exists():
        erro = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        return False, "Não consegui criar o atalho" + (f": {erro[-1]}" if erro else ".")
    return True, "O HomeNOC vai abrir sozinho, em segundo plano, quando o Windows ligar."


def desativar() -> tuple[bool, str]:
    if not suportado():
        return False, "Disponível só no Windows."
    try:
        _atalho().unlink(missing_ok=True)
    except OSError as exc:
        return False, f"Não consegui remover o atalho: {exc}"
    return True, "O HomeNOC não vai mais abrir com o Windows."
