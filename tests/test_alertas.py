"""Canais de alerta contra um servidor HTTP local (nenhuma mensagem sai de verdade)."""

import json
import unittest
import urllib.error
import urllib.parse
from io import BytesIO
from unittest import mock

from apoio import Relogio, ServidorHTTPFalso, config_e_banco

from homenoc import alertas
from homenoc.alertas import Alertas, Discord, Telegram, descobrir_chat_ids, descrever_erro, dica_erro


class Canais(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ServidorHTTPFalso()

    @classmethod
    def tearDownClass(cls):
        cls.srv.fechar()

    def setUp(self):
        self.srv.pedidos.clear()
        self.srv.status, self.srv.resposta = 200, b'{"ok":true}'
        p = mock.patch.object(Telegram, "api_base", self.srv.base)
        p.start()
        self.addCleanup(p.stop)

    def test_telegram_envia_formulario_com_user_agent(self):
        Telegram("123:ABC", "987654").enviar("🔴 Internet: OFFLINE")
        pedido = self.srv.pedidos[0]
        self.assertEqual(pedido["caminho"], "/bot123:ABC/sendMessage")
        self.assertTrue(pedido["cabecalhos"]["user-agent"].startswith("HomeNOC/"))   # nada de "Python-urllib"
        self.assertIn("chat_id=987654", pedido["corpo"])
        self.assertIn("text=%F0%9F%94%B4+Internet", pedido["corpo"])

    def test_discord_envia_json(self):
        Discord(f"{self.srv.base}/api/webhooks/1/abc").enviar("🟢 REDE RESTAURADA")
        pedido = self.srv.pedidos[0]
        self.assertEqual(pedido["cabecalhos"]["content-type"], "application/json")
        self.assertEqual(json.loads(pedido["corpo"]), {"content": "🟢 REDE RESTAURADA"})

    def test_erro_do_telegram_vira_mensagem_util(self):
        self.srv.status = 400
        self.srv.resposta = b'{"ok":false,"error_code":400,"description":"Bad Request: chat not found"}'
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            Telegram("123:ABC", "1").enviar("oi")
        self.assertEqual(descrever_erro(ctx.exception), "HTTP 400 Bad Request: chat not found")

    def test_erro_nao_vaza_o_token(self):
        exc = urllib.error.HTTPError("https://api.telegram.org/bot123:SEGREDO/sendMessage", 400, "Bad Request", {},
                                     BytesIO(b'{"ok":false,"description":"Bad Request: chat not found"}'))
        texto = descrever_erro(exc) + (dica_erro("Telegram", exc) or "")
        self.assertIn("chat not found", texto)
        self.assertIn("/start", texto)
        self.assertNotIn("SEGREDO", texto)

    def test_descobrir_chat_id(self):
        self.srv.resposta = json.dumps({"ok": True, "result": [
            {"update_id": 1, "message": {"chat": {"id": 555111, "first_name": "Isaac"}, "text": "/start"}}]}).encode()
        self.assertEqual(descobrir_chat_ids("123:ABC"), [{"id": "555111", "nome": "Isaac"}])

    def test_testar_relata_cada_canal(self):
        config, banco = config_e_banco()
        cfg = config.get()
        cfg["alertas"]["telegram"] = {"token": "123456789:" + "A" * 35, "chat_id": "555111"}
        cfg["alertas"]["healthchecks"]["url"] = f"{self.srv.base}/ping/abc"
        resultados = Alertas(banco, config).testar(cfg)
        self.assertEqual([(r["canal"], r["ok"]) for r in resultados], [("Telegram", True), ("Healthchecks.io", True)])
        texto = urllib.parse.parse_qs(self.srv.pedidos[0]["corpo"])["text"][0]
        self.assertIn("✅ Teste do HomeNOC", texto)

    def test_testar_com_token_errado_da_dica(self):
        self.srv.status = 401
        self.srv.resposta = b'{"ok":false,"error_code":401,"description":"Unauthorized"}'
        config, banco = config_e_banco()
        cfg = config.get()
        cfg["alertas"]["telegram"] = {"token": "123456789:" + "A" * 35, "chat_id": "555111"}
        (r,) = Alertas(banco, config).testar(cfg)
        self.assertFalse(r["ok"])
        self.assertEqual(r["mensagem"], "HTTP 401 Unauthorized")
        self.assertIn("@BotFather", r["dica"])


class Vigia(unittest.TestCase):
    def test_sinal_de_vida_no_healthchecks(self):
        srv = ServidorHTTPFalso()
        try:
            config, banco = config_e_banco()
            config.atualizar({"alertas": {"healthchecks": {"url": f"{srv.base}/ping/uuid"}}})
            a = Alertas(banco, config, Relogio())
            a.sinal_de_vida()
            self.assertEqual(srv.pedidos[0]["caminho"], "/ping/uuid")
            self.assertTrue(a.status["healthchecks"]["ok"])
            srv.status = 404
            a.sinal_de_vida()
            self.assertFalse(a.status["healthchecks"]["ok"])
        finally:
            srv.fechar()

    def test_canais_vem_da_configuracao(self):
        config, _ = config_e_banco()
        self.assertEqual(alertas.canais_de(config.get()), [])
        config.atualizar({"alertas": {"telegram": {"token": "123456789:" + "B" * 35, "chat_id": "42"},
                                      "discord": {"webhook": "https://discord.com/api/webhooks/1/x"}}})
        self.assertEqual([c.nome for c in alertas.canais_de(config.get())], ["Telegram", "Discord"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
