"""Testes da API web: rotas, proteções (CSRF, Host, login) e arquivos estáticos.

Sobe o HomeNOC de verdade numa porta livre do 127.0.0.1, mas sem as rotinas de
fundo: nada aqui faz varredura, ping ou acessa a internet.
"""

from __future__ import annotations

import json
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from apoio import pasta_temporaria

from homenoc import acesso
from homenoc.app import App
from homenoc.servidor import ServidorWeb

ABRIDOR = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TOKEN_TELEGRAM = "123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


def aparelho(**extra) -> dict:
    d = {"id": "mac:aa:bb:cc:dd:ee:ff", "ip": "192.168.0.50", "mac": "aa:bb:cc:dd:ee:ff", "tipo": "tv",
         "fabricante": "Samsung Electronics", "online": True, "alertar": False, "primeira_vez": time.time() - 3600,
         "ultima_vez": time.time(), "motivos": ["nome de TV"], "portas": [8008]}
    d.update(extra)
    return d


class BaseServidor(unittest.TestCase):
    def setUp(self) -> None:
        self.app = App(pasta_temporaria(), porta=0, baixar_fabricantes=False)
        self.app.web = ServidorWeb(self.app, 0)
        self.app.web.iniciar("127.0.0.1")
        self.porta = self.app.web.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.porta}"

    def tearDown(self) -> None:
        if self.app.web.httpd:
            self.app.web.parar()
        self.app.banco.fechar()

    def pedir(self, metodo: str, caminho: str, corpo=None, cabecalhos: dict | None = None, bruto: bytes | None = None,
              csrf: bool = True):
        dados = bruto if bruto is not None else (json.dumps(corpo).encode() if corpo is not None else None)
        req = urllib.request.Request(self.base + caminho, data=dados, method=metodo)
        if metodo == "POST":
            req.add_header("Content-Type", "application/json")
            if csrf:
                req.add_header("X-HomeNOC", "1")
        for k, v in (cabecalhos or {}).items():
            req.add_header(k, v)
        try:
            with ABRIDOR.open(req, timeout=10) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def json(self, metodo: str, caminho: str, corpo=None, **kw):
        status, cabecalhos, conteudo = self.pedir(metodo, caminho, corpo, **kw)
        return status, json.loads(conteudo.decode("utf-8")) if conteudo else None, cabecalhos


class TestRotas(BaseServidor):
    def test_saude_e_estado(self):
        status, dados, _ = self.json("GET", "/api/saude")
        self.assertEqual((status, dados["app"]), (200, "HomeNOC"))
        status, estado, cab = self.json("GET", "/api/estado")
        self.assertEqual(status, 200)
        self.assertIn("no-store", cab["Cache-Control"])
        chaves = ("veredito", "dispositivos", "internet", "trafego", "alertas", "zabbix", "primeiros_passos", "acesso")
        for chave in chaves:
            self.assertIn(chave, estado)
        self.assertTrue(estado["acesso"]["local"])
        self.assertEqual(estado["veredito"]["estado"], "iniciando")

    def test_post_sem_cabecalho_do_homenoc_e_recusado(self):
        status, dados, _ = self.json("POST", "/api/varrer", {}, csrf=False)
        self.assertEqual(status, 403)
        self.assertIn("cabeçalho", dados["erro"])

    def test_host_estranho_e_recusado(self):
        status, dados, _ = self.json("GET", "/api/estado", cabecalhos={"Host": "site-malicioso.example"})
        self.assertEqual(status, 403)
        status, _, _ = self.pedir("GET", "/", cabecalhos={"Host": f"localhost:{self.porta}"})
        self.assertEqual(status, 200)

    def test_config_valida_mascara_e_erros_em_portugues(self):
        status, dados, _ = self.json("POST", "/api/config", {"monitor": {"intervalo_s": 5}})
        self.assertEqual(status, 400)
        self.assertIn("entre 15 e 3600", dados["erro"])
        novo = {"alertas": {"telegram": {"token": TOKEN_TELEGRAM, "chat_id": "42"}}}
        status, cfg, _ = self.json("POST", "/api/config", novo)
        self.assertEqual(status, 200)
        self.assertTrue(cfg["alertas"]["telegram"]["token"].startswith("••••"))
        self.assertNotIn(TOKEN_TELEGRAM, json.dumps(cfg))
        # mandar o valor mascarado de volta mantém o token salvo
        self.json("POST", "/api/config", {"alertas": {"telegram": {"token": cfg["alertas"]["telegram"]["token"]}}})
        self.assertEqual(self.app.config.get()["alertas"]["telegram"]["token"], TOKEN_TELEGRAM)
        _, publico, _ = self.json("GET", "/api/config")
        self.assertNotIn("senha_hash", publico["acesso"])
        self.assertNotIn(TOKEN_TELEGRAM, json.dumps(publico))

    def test_config_nao_altera_acesso(self):
        self.json("POST", "/api/config", {"acesso": {"rede_local": True}})
        self.assertFalse(self.app.config.get()["acesso"]["rede_local"])

    def test_atualizar_aparelho(self):
        self.app.banco.salvar_dispositivo(aparelho())
        status, d, _ = self.json("POST", "/api/dispositivos/mac:aa:bb:cc:dd:ee:ff", {"apelido": "  TV   da sala  "})
        self.assertEqual((status, d["apelido"], d["nome"]), (200, "TV da sala", "TV da sala"))
        status, d, _ = self.json("POST", "/api/dispositivos/mac:aa:bb:cc:dd:ee:ff", {"alertar": True})
        self.assertTrue(d["alertar"])
        trans = self.app.banco.estado("monitor.transicoes", {})
        self.assertEqual(trans["dispositivo:mac:aa:bb:cc:dd:ee:ff"]["status"], "online")   # sem alerta falso
        status, dados, _ = self.json("POST", "/api/dispositivos/nao-existe", {"apelido": "x"})
        self.assertEqual(status, 404)

    def test_historico_e_eventos(self):
        status, dados, _ = self.json("GET", "/api/historico?alvo=../../etc")
        self.assertEqual(status, 400)
        status, dados, _ = self.json("GET", "/api/historico?alvo=internet&periodo=3600")
        self.assertEqual(status, 200)
        self.assertEqual(dados["serie"], [])
        self.app.banco.evento("queda", "Internet caiu", alvo="internet", gravidade="critico")
        self.app.banco.evento("novo", "Novo aparelho: TV", gravidade="aviso")
        status, eventos, _ = self.json("GET", "/api/eventos?tipos=queda,volta&limite=10")
        self.assertEqual([e["titulo"] for e in eventos], ["Internet caiu"])

    def test_trafego(self):
        status, dados, _ = self.json("GET", "/api/trafego?periodo=3600")
        self.assertEqual(status, 200)
        for chave in ("serie", "resumo", "dias", "status"):
            self.assertIn(chave, dados)

    def test_csv(self):
        self.app.banco.salvar_dispositivo(aparelho(apelido="TV; sala"))
        status, cab, conteudo = self.pedir("GET", "/api/dispositivos.csv")
        self.assertEqual(status, 200)
        self.assertIn("text/csv", cab["Content-Type"])
        texto = conteudo.decode("utf-8-sig")
        self.assertTrue(texto.startswith("Nome;Tipo;IP"))
        self.assertIn('"TV; sala"', texto)

    def test_corpo_invalido_ou_grande(self):
        status, dados, _ = self.json("POST", "/api/config", bruto=b"{nao e json")
        self.assertEqual(status, 400)
        status, _, _ = self.pedir("POST", "/api/config", bruto=b"x" * (65 * 1024))
        self.assertEqual(status, 413)

    def test_acesso_pelo_celular(self):
        with mock.patch.object(self.app.web, "trocar_host") as trocar:
            status, dados, _ = self.json("POST", "/api/acesso", {"rede_local": True})
            self.assertEqual(status, 400)
            self.assertIn("senha", dados["erro"])
            status, dados, _ = self.json("POST", "/api/acesso", {"rede_local": True, "senha": "123"})
            self.assertEqual(status, 400)
            status, dados, _ = self.json("POST", "/api/acesso", {"rede_local": True, "senha": "senha-forte"})
            self.assertEqual((status, dados["rede_local"]), (200, True))
            trocar.assert_called_with("0.0.0.0")
        acesso_cfg = self.app.config.get()["acesso"]
        self.assertNotIn("senha-forte", json.dumps(acesso_cfg))
        self.assertTrue(acesso.conferir_senha("senha-forte", acesso_cfg["senha_hash"], acesso_cfg["sal"]))


class TestEstaticos(BaseServidor):
    def test_pagina_e_arquivos(self):
        status, cab, conteudo = self.pedir("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", cab["Content-Type"])
        self.assertEqual(cab["X-Frame-Options"], "DENY")
        self.assertIn(b"HomeNOC", conteudo)
        status, cab, _ = self.pedir("GET", "/app.js")
        self.assertEqual((status, cab["Content-Type"].split(";")[0]), (200, "text/javascript"))
        status, cab, _ = self.pedir("GET", "/fonts/barlow-400.woff2")
        self.assertEqual((status, cab["Content-Type"]), (200, "font/woff2"))

    def test_nao_sai_da_pasta_web(self):
        for caminho in ("/../app.py", "/..", "/%2e%2e/app.py", "/fonts/../../app.py", "/nao-existe.js", "/web/app.js"):
            with self.subTest(caminho=caminho):
                status, _, conteudo = self.pedir("GET", caminho)
                self.assertEqual(status, 404)
                self.assertNotIn(b"import", conteudo)


class TestAcessoRemoto(BaseServidor):
    """Pedidos vindos de outro aparelho da rede (simulado)."""

    def setUp(self) -> None:
        super().setUp()
        remendo = mock.patch("homenoc.acesso.eh_local", return_value=False)
        remendo.start()
        self.addCleanup(remendo.stop)
        espera = mock.patch("homenoc.servidor.time.sleep")      # sem a pausa anti-força-bruta nos testes
        espera.start()
        self.addCleanup(espera.stop)

    def ligar_acesso(self, senha="senha-forte"):
        h, sal = acesso.hash_senha(senha)
        self.app.config.definir_acesso(True, h, sal)

    def test_desligado_recusa_tudo(self):
        status, dados, _ = self.json("GET", "/api/estado")
        self.assertEqual(status, 403)
        self.assertIn("desativado", dados["erro"])

    def test_login(self):
        self.ligar_acesso()
        status, _, _ = self.json("GET", "/api/estado")
        self.assertEqual(status, 401)
        status, sessao, _ = self.json("GET", "/api/sessao")
        self.assertEqual((sessao["local"], sessao["autenticado"]), (False, False))
        status, dados, _ = self.json("POST", "/api/login", {"senha": "errada"})
        self.assertEqual(status, 401)
        status, dados, cab = self.json("POST", "/api/login", {"senha": "senha-forte"})
        self.assertEqual(status, 200)
        cookie = cab["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        valor = cookie.split(";")[0]
        status, estado, _ = self.json("GET", "/api/estado", cabecalhos={"Cookie": valor})
        self.assertEqual(status, 200)
        self.assertFalse(estado["acesso"]["local"])
        self.assertIsNone(estado["pasta_dados"])                 # o celular não vê caminhos do computador
        # mudanças sensíveis só no próprio computador
        sensiveis = (("/api/acesso", {"rede_local": False}), ("/api/encerrar", {}), ("/api/autostart", {"ativo": True}))
        for rota, corpo in sensiveis:
            status, _, _ = self.json("POST", rota, corpo, cabecalhos={"Cookie": valor})
            self.assertEqual(status, 403, rota)
        status, _, _ = self.json("POST", "/api/sair", {}, cabecalhos={"Cookie": valor})
        status, _, _ = self.json("GET", "/api/estado", cabecalhos={"Cookie": valor})
        self.assertEqual(status, 401)

    def test_bloqueio_depois_de_muitas_tentativas(self):
        self.ligar_acesso()
        for _ in range(acesso.TENTATIVAS_MAX):
            self.json("POST", "/api/login", {"senha": "errada"})
        status, dados, _ = self.json("POST", "/api/login", {"senha": "senha-forte"})
        self.assertEqual(status, 429)


class TestEncerrar(BaseServidor):
    def test_encerrar_pela_interface(self):
        status, dados, _ = self.json("POST", "/api/encerrar", {})
        self.assertEqual(status, 200)
        self.assertTrue(self.app.parar.wait(5))


if __name__ == "__main__":
    unittest.main()
