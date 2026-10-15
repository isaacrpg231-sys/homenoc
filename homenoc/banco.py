"""
Banco de dados SQLite do HomeNOC: inventário de aparelhos, histórico de
latência e tráfego, eventos e a fila de alertas.

Um único arquivo (dados/homenoc.db), sem servidor. Todas as operações passam por
uma trava, então as rotinas em paralelo (descoberta, monitor, tráfego, web)
podem usar o mesmo objeto.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS dispositivos (
    id            TEXT PRIMARY KEY,      -- 'mac:aa:bb:..' ou 'ip:192.168.0.5'
    ip            TEXT,
    mac           TEXT,
    apelido       TEXT,                  -- nome dado pelo usuário
    nome_dns      TEXT,
    fabricante    TEXT,
    tipo          TEXT,
    motivos       TEXT,                  -- JSON: por que esse tipo
    portas        TEXT,                  -- JSON: portas abertas
    portas_em     REAL,                  -- quando as portas foram testadas
    upnp          TEXT,                  -- JSON: nome, fabricante, modelo, tipo
    ttl           INTEGER,
    so            TEXT,
    mac_aleatorio INTEGER DEFAULT 0,
    responde_ping INTEGER DEFAULT 0,
    online        INTEGER DEFAULT 0,
    latencia      REAL,
    ausencias     INTEGER DEFAULT 0,     -- varreduras seguidas sem aparecer
    primeira_vez  REAL,
    ultima_vez    REAL,
    mudou_em      REAL,                  -- quando ficou online/offline
    alertar       INTEGER DEFAULT 0      -- 1 = monitorar de perto e avisar se cair
);
CREATE TABLE IF NOT EXISTS amostras (
    alvo TEXT NOT NULL,                  -- 'internet', 'wan:8.8.8.8', 'dispositivo:<id>'
    ts   REAL NOT NULL,
    ms   REAL                            -- NULL = sem resposta
);
CREATE INDEX IF NOT EXISTS amostras_alvo_ts ON amostras (alvo, ts);
CREATE TABLE IF NOT EXISTS trafego (
    ts       REAL PRIMARY KEY,
    rx_bps   REAL,
    tx_bps   REAL,
    rx_bytes INTEGER,
    tx_bytes INTEGER
);
CREATE TABLE IF NOT EXISTS eventos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL NOT NULL,
    tipo      TEXT NOT NULL,             -- queda, volta, novo, saiu, voltou, alerta, sistema
    gravidade TEXT NOT NULL,             -- ok, info, aviso, critico
    alvo      TEXT,
    titulo    TEXT NOT NULL,
    detalhe   TEXT
);
CREATE INDEX IF NOT EXISTS eventos_ts ON eventos (ts);
CREATE TABLE IF NOT EXISTS fila_alertas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em   REAL NOT NULL,
    resumo      TEXT,
    texto       TEXT NOT NULL,
    tentativas  INTEGER DEFAULT 0,
    ultimo_erro TEXT
);
CREATE TABLE IF NOT EXISTS estado (
    chave TEXT PRIMARY KEY,
    valor TEXT
);
"""

CAMPOS_JSON = ("motivos", "portas", "upnp")
CAMPOS_DISPOSITIVO = ("id", "ip", "mac", "apelido", "nome_dns", "fabricante", "tipo", "motivos", "portas",
                      "portas_em", "upnp", "ttl", "so", "mac_aleatorio", "responde_ping", "online",
                      "latencia", "ausencias", "primeira_vez", "ultima_vez", "mudou_em", "alertar")


class Banco:
    def __init__(self, caminho: str | Path) -> None:
        if str(caminho) != ":memory:":
            Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.con = sqlite3.connect(str(caminho), check_same_thread=False, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        with self.lock:
            if str(caminho) != ":memory:":
                self.con.execute("PRAGMA journal_mode=WAL")
            self.con.execute("PRAGMA synchronous=NORMAL")
            self.con.executescript(ESQUEMA)

    def fechar(self) -> None:
        with self.lock:
            self.con.close()

    def _todos(self, sql: str, params=()) -> list[sqlite3.Row]:
        with self.lock:
            return self.con.execute(sql, params).fetchall()

    def _executar(self, sql: str, params=()) -> sqlite3.Cursor:
        with self.lock:
            return self.con.execute(sql, params)

    # ---------------- dispositivos ----------------

    @staticmethod
    def _dispositivo(linha: sqlite3.Row) -> dict:
        d = dict(linha)
        for campo in CAMPOS_JSON:
            try:
                d[campo] = json.loads(d[campo]) if d[campo] else None
            except ValueError:
                d[campo] = None
        for campo in ("mac_aleatorio", "responde_ping", "online", "alertar"):
            d[campo] = bool(d[campo])
        return d

    def dispositivos(self) -> list[dict]:
        return [self._dispositivo(r) for r in self._todos("SELECT * FROM dispositivos")]

    def dispositivo(self, id_: str) -> dict | None:
        linhas = self._todos("SELECT * FROM dispositivos WHERE id = ?", (id_,))
        return self._dispositivo(linhas[0]) if linhas else None

    def salvar_dispositivo(self, d: dict) -> None:
        valores = []
        for campo in CAMPOS_DISPOSITIVO:
            v = d.get(campo)
            if campo in CAMPOS_JSON:
                v = json.dumps(v, ensure_ascii=False) if v is not None else None
            elif isinstance(v, bool):
                v = int(v)
            valores.append(v)
        marcas = ", ".join("?" for _ in CAMPOS_DISPOSITIVO)
        self._executar(f"INSERT OR REPLACE INTO dispositivos ({', '.join(CAMPOS_DISPOSITIVO)}) "
                       f"VALUES ({marcas})", valores)

    def atualizar_dispositivo(self, id_: str, **campos) -> None:
        campos = {k: v for k, v in campos.items() if k in CAMPOS_DISPOSITIVO and k != "id"}
        if not campos:
            return
        valores = []
        for k, v in campos.items():
            if k in CAMPOS_JSON:
                v = json.dumps(v, ensure_ascii=False) if v is not None else None
            elif isinstance(v, bool):
                v = int(v)
            valores.append(v)
        sets = ", ".join(f"{k} = ?" for k in campos)
        self._executar(f"UPDATE dispositivos SET {sets} WHERE id = ?", [*valores, id_])

    def renomear_dispositivo(self, antigo: str, novo: str) -> None:
        """Troca o identificador (ex.: o MAC passou a ser conhecido) sem perder o histórico."""
        with self.lock:
            self.con.execute("BEGIN")
            try:
                self.con.execute("DELETE FROM dispositivos WHERE id = ?", (novo,))
                self.con.execute("UPDATE dispositivos SET id = ? WHERE id = ?", (novo, antigo))
                self.con.execute("UPDATE amostras SET alvo = ? WHERE alvo = ?",
                                 (f"dispositivo:{novo}", f"dispositivo:{antigo}"))
                self.con.execute("UPDATE eventos SET alvo = ? WHERE alvo = ?",
                                 (f"dispositivo:{novo}", f"dispositivo:{antigo}"))
                self.con.execute("COMMIT")
            except sqlite3.Error:
                self.con.execute("ROLLBACK")
                raise

    def remover_dispositivo(self, id_: str) -> None:
        with self.lock:
            self.con.execute("DELETE FROM dispositivos WHERE id = ?", (id_,))
            self.con.execute("DELETE FROM amostras WHERE alvo = ?", (f"dispositivo:{id_}",))

    # ---------------- amostras de latência ----------------

    def registrar_amostras(self, ts: float, pares: list[tuple[str, float | None]]) -> None:
        if pares:
            with self.lock:
                self.con.executemany("INSERT INTO amostras (alvo, ts, ms) VALUES (?, ?, ?)",
                                     [(alvo, ts, ms) for alvo, ms in pares])

    def serie(self, alvo: str, desde: float, ate: float, baldes: int = 240) -> list[list]:
        """Latência agrupada em baldes: [[ts do meio, média ms ou None, perda %], ...]."""
        passo = max((ate - desde) / max(baldes, 1), 1e-6)
        linhas = self._todos(
            "SELECT CAST((ts - ?) / ? AS INTEGER) AS b, AVG(ms) AS media, COUNT(*) AS n, "
            "SUM(CASE WHEN ms IS NULL THEN 1 ELSE 0 END) AS perdas "
            "FROM amostras WHERE alvo = ? AND ts >= ? AND ts <= ? GROUP BY b ORDER BY b",
            (desde, passo, alvo, desde, ate))
        return [[desde + (r["b"] + 0.5) * passo,
                 None if r["media"] is None else round(r["media"], 2),
                 round(100.0 * r["perdas"] / r["n"], 1)] for r in linhas]

    def estatisticas(self, alvo: str, desde: float) -> dict:
        r = self._todos("SELECT AVG(ms) AS media, MIN(ms) AS minimo, MAX(ms) AS maximo, COUNT(*) AS n, "
                        "SUM(CASE WHEN ms IS NULL THEN 1 ELSE 0 END) AS perdas "
                        "FROM amostras WHERE alvo = ? AND ts >= ?", (alvo, desde))[0]
        n = r["n"] or 0
        return {"media": r["media"], "minimo": r["minimo"], "maximo": r["maximo"], "amostras": n,
                "disponibilidade": round(100.0 * (n - (r["perdas"] or 0)) / n, 2) if n else None}

    # ---------------- tráfego ----------------

    def registrar_trafego(self, ts: float, rx_bps: float, tx_bps: float, rx_bytes: int, tx_bytes: int) -> None:
        self._executar("INSERT OR REPLACE INTO trafego (ts, rx_bps, tx_bps, rx_bytes, tx_bytes) "
                       "VALUES (?, ?, ?, ?, ?)", (ts, rx_bps, tx_bps, rx_bytes, tx_bytes))

    def serie_trafego(self, desde: float, ate: float, baldes: int = 240) -> list[list]:
        """[[ts do meio, download médio bps, upload médio bps], ...]."""
        passo = max((ate - desde) / max(baldes, 1), 1e-6)
        linhas = self._todos(
            "SELECT CAST((ts - ?) / ? AS INTEGER) AS b, AVG(rx_bps) AS rx, AVG(tx_bps) AS tx "
            "FROM trafego WHERE ts >= ? AND ts <= ? GROUP BY b ORDER BY b", (desde, passo, desde, ate))
        return [[desde + (r["b"] + 0.5) * passo, round(r["rx"], 1), round(r["tx"], 1)] for r in linhas]

    def resumo_trafego(self, desde: float, ate: float) -> dict:
        r = self._todos("SELECT SUM(rx_bytes) AS rx, SUM(tx_bytes) AS tx, MAX(rx_bps) AS pico_rx, "
                        "MAX(tx_bps) AS pico_tx, COUNT(*) AS n FROM trafego WHERE ts >= ? AND ts <= ?",
                        (desde, ate))[0]
        pico = self._todos("SELECT ts FROM trafego WHERE ts >= ? AND ts <= ? ORDER BY rx_bps DESC LIMIT 1",
                           (desde, ate))
        return {"rx_bytes": r["rx"] or 0, "tx_bytes": r["tx"] or 0, "pico_rx_bps": r["pico_rx"],
                "pico_tx_bps": r["pico_tx"], "pico_em": pico[0]["ts"] if pico else None, "amostras": r["n"]}

    def consumo_por_dia(self, dias: int, deslocamento_s: int, agora: float | None = None) -> list[dict]:
        """Bytes por dia local (deslocamento_s = fuso em segundos), dos últimos N dias."""
        agora = agora or time.time()
        desde = agora - dias * 86400
        linhas = self._todos(
            "SELECT date(ts + ?, 'unixepoch') AS dia, SUM(rx_bytes) AS rx, SUM(tx_bytes) AS tx "
            "FROM trafego WHERE ts >= ? GROUP BY dia ORDER BY dia", (deslocamento_s, desde))
        return [{"dia": r["dia"], "rx_bytes": r["rx"] or 0, "tx_bytes": r["tx"] or 0} for r in linhas]

    # ---------------- eventos ----------------

    def evento(self, tipo: str, titulo: str, detalhe: str = "", alvo: str | None = None,
               gravidade: str = "info", ts: float | None = None) -> int:
        cur = self._executar("INSERT INTO eventos (ts, tipo, gravidade, alvo, titulo, detalhe) "
                             "VALUES (?, ?, ?, ?, ?, ?)",
                             (ts or time.time(), tipo, gravidade, alvo, titulo, detalhe or None))
        return cur.lastrowid

    def eventos(self, limite: int = 50, antes: int | None = None, tipos: list[str] | None = None,
                alvo: str | None = None) -> list[dict]:
        sql, params = "SELECT * FROM eventos WHERE 1 = 1", []
        if antes:
            sql += " AND id < ?"
            params.append(antes)
        if tipos:
            sql += f" AND tipo IN ({', '.join('?' for _ in tipos)})"
            params += tipos
        if alvo:
            sql += " AND alvo = ?"
            params.append(alvo)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(int(limite), 500)))
        return [dict(r) for r in self._todos(sql, params)]

    # ---------------- fila de alertas ----------------

    def fila_adicionar(self, ts: float, resumo: str, texto: str) -> None:
        self._executar("INSERT INTO fila_alertas (criado_em, resumo, texto) VALUES (?, ?, ?)", (ts, resumo, texto))

    def fila(self) -> list[dict]:
        return [dict(r) for r in self._todos("SELECT * FROM fila_alertas ORDER BY id")]

    def fila_remover(self, id_: int) -> None:
        self._executar("DELETE FROM fila_alertas WHERE id = ?", (id_,))

    def fila_erro(self, id_: int, erro: str) -> None:
        self._executar("UPDATE fila_alertas SET tentativas = tentativas + 1, ultimo_erro = ? WHERE id = ?",
                       (erro, id_))

    def fila_cortar(self, maximo: int) -> None:
        """Numa queda muito longa, guarda só os alertas mais recentes."""
        self._executar("DELETE FROM fila_alertas WHERE id NOT IN "
                       "(SELECT id FROM fila_alertas ORDER BY id DESC LIMIT ?)", (maximo,))

    def fila_limpar(self) -> None:
        self._executar("DELETE FROM fila_alertas")

    # ---------------- estado (chave/valor) ----------------

    def estado(self, chave: str, padrao=None):
        linhas = self._todos("SELECT valor FROM estado WHERE chave = ?", (chave,))
        if not linhas:
            return padrao
        try:
            return json.loads(linhas[0]["valor"])
        except ValueError:
            return padrao

    def definir_estado(self, chave: str, valor) -> None:
        self._executar("INSERT OR REPLACE INTO estado (chave, valor) VALUES (?, ?)",
                       (chave, json.dumps(valor, ensure_ascii=False)))

    # ---------------- limpeza ----------------

    def limpar(self, dias_amostras: int, dias_eventos: int = 90, dias_trafego: int = 31,
               agora: float | None = None) -> None:
        agora = agora or time.time()
        with self.lock:
            self.con.execute("DELETE FROM amostras WHERE ts < ?", (agora - dias_amostras * 86400,))
            self.con.execute("DELETE FROM trafego WHERE ts < ?", (agora - dias_trafego * 86400,))
            self.con.execute("DELETE FROM eventos WHERE ts < ?", (agora - dias_eventos * 86400,))
