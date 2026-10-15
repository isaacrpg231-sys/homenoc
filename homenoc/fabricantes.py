"""
Fabricante de cada aparelho pelo começo do MAC (OUI), usando a lista oficial do
IEEE. A lista é baixada uma vez (cerca de 5 MB) e renovada a cada 90 dias.
"""

from __future__ import annotations

import csv
import logging
import os
import re
import shutil
import threading
import time
import urllib.request
from pathlib import Path

from . import rede

log = logging.getLogger("homenoc")

_SUFIXOS = re.compile(
    r"[,.\s]+(co\.?,?\s*ltd\.?|corporation|corp\.?|inc\.?|incorporated|limited|ltd\.?|llc|gmbh|"
    r"s\.?a\.?|s\.?p\.?a\.?|b\.?v\.?|ag|plc|technologies|technology|electronics co\.?)$", re.I)


def limpar_nome(nome: str) -> str:
    """'TP-LINK TECHNOLOGIES CO.,LTD.' -> 'TP-LINK'. Tira sufixos jurídicos repetidamente."""
    nome = " ".join(nome.split())
    anterior = None
    while nome and nome != anterior:
        anterior = nome
        nome = _SUFIXOS.sub("", nome).strip(" ,.")
    return nome or anterior or ""


class Fabricantes:
    URL = "https://standards-oui.ieee.org/oui/oui.csv"
    VALIDADE_S = 90 * 86400

    def __init__(self, pasta: Path, baixar: bool = True) -> None:
        self.arquivo = Path(pasta) / "oui.csv"
        self.tabela: dict[str, str] = {}
        self.estado = "carregando"
        if baixar:
            threading.Thread(target=self._carregar, name="oui", daemon=True).start()
        else:
            self._ler()

    def _carregar(self) -> None:
        try:
            if not self.arquivo.exists() or time.time() - self.arquivo.stat().st_mtime > self.VALIDADE_S:
                self._baixar()
        except OSError as exc:
            log.info("Lista de fabricantes não baixada (%s); seguindo sem ela.", exc)
        self._ler()

    def _baixar(self) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.arquivo.with_suffix(".tmp")
        req = urllib.request.Request(self.URL, headers={"User-Agent": "HomeNOC/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resposta, tmp.open("wb") as destino:
            shutil.copyfileobj(resposta, destino)
        os.replace(tmp, self.arquivo)
        log.info("Lista de fabricantes (IEEE OUI) atualizada.")

    def _ler(self) -> None:
        tabela = {}
        try:
            with self.arquivo.open(encoding="utf-8", errors="replace", newline="") as f:
                for linha in csv.reader(f):
                    if len(linha) >= 3 and re.fullmatch(r"[0-9A-Fa-f]{6}", linha[1]):
                        tabela[linha[1].upper()] = limpar_nome(linha[2])
        except OSError:
            self.estado = "indisponivel"
            return
        self.tabela = tabela
        self.estado = "pronto"

    def nome(self, mac: str | None) -> str | None:
        if not mac:
            return None
        if rede.mac_aleatorio(mac):
            return "MAC aleatório (privacidade)"
        return self.tabela.get(mac.replace(":", "").replace("-", "")[:6].upper())
