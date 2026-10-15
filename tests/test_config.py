"""Configuração pela tela: valores padrão, validação e segredos que nunca saem inteiros."""

import json
import unittest

from apoio import pasta_temporaria

from homenoc.config import PADRAO, Config, ErroConfig, normalizar_url_zabbix

TOKEN = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.pasta = pasta_temporaria()
        self.config = Config(self.pasta / "config.json")

    def test_padrao_sem_arquivo(self):
        self.assertEqual(self.config.get(), PADRAO)
        self.assertFalse((self.pasta / "config.json").exists())

    def test_salva_e_relê(self):
        self.config.atualizar({"monitor": {"intervalo_s": 30}, "internet": {"alvos": ["9.9.9.9", "1.1.1.1"]}})
        relida = Config(self.pasta / "config.json").get()
        self.assertEqual(relida["monitor"]["intervalo_s"], 30)
        self.assertEqual(relida["monitor"]["confirmacao_s"], 15)      # o resto continua o padrão
        self.assertEqual(relida["internet"]["alvos"], ["9.9.9.9", "1.1.1.1"])

    def test_segredos_mascarados_e_mantidos(self):
        self.config.atualizar({"alertas": {"telegram": {"token": TOKEN, "chat_id": "555111"}}})
        mascarado = self.config.mascarado()
        self.assertEqual(mascarado["alertas"]["telegram"]["token"], "••••Dsaw")
        self.assertNotIn(TOKEN, json.dumps(mascarado))
        # a tela devolve o valor mascarado sem mudar: o token continua o mesmo
        self.config.atualizar({"alertas": {"telegram": {"token": "••••Dsaw", "chat_id": "777"}}})
        self.assertEqual(self.config.get()["alertas"]["telegram"], {"token": TOKEN, "chat_id": "777"})
        # campo apagado: remove o segredo
        self.config.atualizar({"alertas": {"telegram": {"token": ""}}})
        self.assertEqual(self.config.get()["alertas"]["telegram"]["token"], "")

    def test_hash_da_senha_nunca_vai_para_a_tela(self):
        self.config.definir_acesso(True, "ab" * 32, "cd" * 16)
        acesso = self.config.mascarado()["acesso"]
        self.assertEqual(acesso, {"rede_local": True, "senha_definida": True})

    def test_acesso_nao_muda_pelo_formulario_comum(self):
        self.config.atualizar({"acesso": {"rede_local": True}})
        self.assertFalse(self.config.get()["acesso"]["rede_local"])

    def test_erros_com_mensagem_clara(self):
        casos = [
            ({"monitor": {"intervalo_s": 5}}, "entre 15 e 3600"),
            ({"monitor": {"tentativas": "3"}}, "número inteiro"),
            ({"internet": {"alvos": []}}, "de 1 a 4"),
            ({"internet": {"alvos": ["8.8.8.8", "999.1.1.1"]}}, "não é um IP"),
            ({"internet": {"alvos": ["8.8.8.8", "8.8.8.8"]}}, "repetidos"),
            ({"internet": {"alertar": "sim"}}, "verdadeiro ou falso"),
            ({"alertas": {"telegram": {"token": "abc"}}}, "token do Telegram"),
            ({"alertas": {"telegram": {"chat_id": "meu chat"}}}, "chat_id"),
            ({"alertas": {"discord": {"webhook": "https://exemplo.com/x"}}}, "discord.com/api/webhooks"),
            ({"zabbix": {"token": "token com espaço"}}, "token do Zabbix"),
            ({"retencao_dias": 365}, "entre 1 e 90"),
        ]
        for parcial, trecho in casos:
            with self.subTest(parcial=parcial):
                with self.assertRaises(ErroConfig) as ctx:
                    self.config.atualizar(parcial)
                self.assertIn(trecho, str(ctx.exception))
        self.assertEqual(self.config.get(), PADRAO)                  # nada inválido foi salvo

    def test_previa_nao_salva(self):
        previa = self.config.previa({"alertas": {"telegram": {"token": TOKEN, "chat_id": "1"}}})
        self.assertEqual(previa["alertas"]["telegram"]["token"], TOKEN)
        self.assertEqual(self.config.get()["alertas"]["telegram"]["token"], "")

    def test_url_do_zabbix_completada(self):
        self.assertEqual(normalizar_url_zabbix("192.168.1.60/zabbix"), "http://192.168.1.60/zabbix/api_jsonrpc.php")
        self.assertEqual(normalizar_url_zabbix("https://z.lan/zabbix/api_jsonrpc.php"),
                         "https://z.lan/zabbix/api_jsonrpc.php")
        self.assertEqual(normalizar_url_zabbix(""), "")

    def test_arquivo_corrompido_usa_padrao_e_avisa(self):
        (self.pasta / "config.json").write_text("{isso não é json", encoding="utf-8")
        c = Config(self.pasta / "config.json")
        self.assertEqual(c.get(), PADRAO)
        self.assertIn("ignorado", c.aviso)

    def test_aceita_bom_do_bloco_de_notas(self):
        (self.pasta / "config.json").write_text('{"retencao_dias": 14}', encoding="utf-8-sig")
        self.assertEqual(Config(self.pasta / "config.json").get()["retencao_dias"], 14)


if __name__ == "__main__":
    unittest.main(verbosity=2)
